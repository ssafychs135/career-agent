import logging
import os

import httpx

log = logging.getLogger("research.discord")


async def push(content: str) -> None:
    """Discord 웹훅으로 알림. 웹훅 미설정/실패는 조용히 무시(리서치 흐름 비차단)."""
    url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(
                url,
                json={"content": content},
                headers={"User-Agent": "career-agent"},
            )
    except Exception as e:  # noqa: BLE001 — 알림 실패는 무시
        log.warning("discord push failed: %s", e)
