import asyncio
import json
import re
from urllib.parse import urlparse


class ClaudeError(RuntimeError):
    """claude가 오류 결과(is_error)를 돌려줬다. 결과 문구가 메시지다."""


class ClaudeAuthError(ClaudeError):
    """구독 인증이 풀렸다 — 공고 하나의 문제가 아니라 모든 호출이 실패한다."""


# 실측 문구: "Failed to authenticate: OAuth session expired and could not be refreshed"(운영),
# "Not logged in · Please run /login"(설정 디렉터리가 빈 상태로 재현).
_AUTH_ERROR = re.compile(r"authenticat|not logged in|/login|oauth|invalid api key", re.I)


def _error_for(text: str) -> ClaudeError:
    cls = ClaudeAuthError if _AUTH_ERROR.search(text) else ClaudeError
    return cls(text[:500])


def stream_label(event: dict) -> str | None:
    """stream-json 이벤트 → 사람이 읽는 현재 단계. 해당 없으면 None."""
    if event.get("type") != "assistant":
        return None
    for block in event.get("message", {}).get("content", []):
        if block.get("type") == "tool_use":
            name = block.get("name", "")
            inp = block.get("input", {}) or {}
            if name == "WebSearch":
                return f'웹 검색: "{inp.get("query", "")}"'
            if name == "WebFetch":
                return f"페이지 확인: {urlparse(inp.get('url', '')).netloc}"
            return f"{name} 실행 중"
        if block.get("type") == "text":
            return "분석·작성 중"
    return None


async def run_claude(
    prompt: str,
    *,
    model: str = "",
    allowed_tools: str = "",
    timeout: int = 120,
    claude_bin: str = "claude",
    on_step=None,
) -> str:
    """`claude -p`를 stream-json으로 실행. 이벤트마다 on_step(label) 호출, 최종 result 반환."""
    args = [claude_bin, "-p", prompt, "--output-format", "stream-json", "--verbose"]
    if model:
        args += ["--model", model]
    if allowed_tools:
        args += ["--allowedTools", allowed_tools]

    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )

    result: str | None = None
    # CLI는 실패해도 subtype "success"로 끝내고 오류 문구를 result에 담는다.
    # is_error만이 신호다 — 무시하면 오류 문구가 정상 응답으로 저장된다.
    is_error = False

    async def _consume():
        nonlocal result, is_error
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue  # 비JSON/잘린 라인 무시
            if event.get("type") == "result":
                result = event.get("result")
                is_error = bool(event.get("is_error"))
            elif on_step is not None:
                label = stream_label(event)
                if label:
                    on_step(label)

    try:
        await asyncio.wait_for(_consume(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("claude timed out")
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except asyncio.TimeoutError:
        proc.kill()  # 프로세스는 정리하되 이미 받은 result는 버리지 않음

    if result is not None:
        if is_error:
            raise _error_for(result)
        return result
    if proc.returncode not in (0, None):
        err = (await proc.stderr.read()).decode()[:500]
        raise RuntimeError(f"claude failed ({proc.returncode}): {err}")
    raise RuntimeError("claude produced no result event")
