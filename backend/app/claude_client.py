import asyncio
import json
from urllib.parse import urlparse


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
    allowed_tools: str = "",
    timeout: int = 120,
    claude_bin: str = "claude",
    on_step=None,
) -> str:
    """`claude -p`를 stream-json으로 실행. 이벤트마다 on_step(label) 호출, 최종 result 반환."""
    args = [claude_bin, "-p", prompt, "--output-format", "stream-json", "--verbose"]
    if allowed_tools:
        args += ["--allowedTools", allowed_tools]

    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )

    result: str | None = None

    async def _consume():
        nonlocal result
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
        return result
    if proc.returncode not in (0, None):
        err = (await proc.stderr.read()).decode()[:500]
        raise RuntimeError(f"claude failed ({proc.returncode}): {err}")
    raise RuntimeError("claude produced no result event")
