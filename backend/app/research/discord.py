import logging
import os

import httpx

log = logging.getLogger("notify.discord")

# 웹훅 출처는 설정(app_settings.discord_webhook_url). 앱 시작·설정 저장 시 갱신하고,
# 미설정이면 env로 폴백한다. (env만 읽던 시절엔 컨테이너에 env가 없어 알림이 전부 죽어 있었다.)
_webhook = ""


def set_webhook(url: str) -> None:
    global _webhook
    _webhook = (url or "").strip()


def _url() -> str:
    return _webhook or os.environ.get("DISCORD_WEBHOOK_URL", "")


async def push(content: str) -> None:
    """Discord 웹훅으로 알림. 웹훅 미설정/실패는 조용히 무시(호출 흐름 비차단)."""
    url = _url()
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


async def push_embeds(content: str | None, embeds: list[dict]) -> None:
    """임베드 카드 발송. push와 달리 실패 시 예외를 던진다 —
    알림기가 성공 여부로 notified_at 마킹을 결정하므로 삼키면 안 된다."""
    url = _url()
    if not url:
        raise RuntimeError("discord webhook not configured")
    payload: dict = {"embeds": embeds}
    if content:
        payload["content"] = content
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, json=payload, headers={"User-Agent": "career-agent"})
        r.raise_for_status()
