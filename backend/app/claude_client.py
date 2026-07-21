import asyncio
import json


async def run_claude(
    prompt: str,
    *,
    allowed_tools: str = "",
    timeout: int = 120,
    claude_bin: str = "claude",
) -> str:
    """`claude -p`를 실행해 모델 텍스트(result)를 반환. 실패·타임아웃 시 RuntimeError."""
    args = [claude_bin, "-p", prompt, "--output-format", "json"]
    if allowed_tools:
        args += ["--allowedTools", allowed_tools]

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("claude timed out")

    if proc.returncode != 0:
        raise RuntimeError(f"claude failed ({proc.returncode}): {stderr.decode()[:500]}")

    envelope = json.loads(stdout.decode())
    return envelope["result"]
