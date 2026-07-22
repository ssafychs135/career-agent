from app.collect.config import LLM_BASE_URL


async def llm_healthy(http, base_url: str = LLM_BASE_URL) -> bool:
    try:
        r = await http.get(f"{base_url}/v1/models", timeout=5)
        return r.status_code == 200
    except Exception:  # noqa: BLE001 — 어떤 실패든 down으로 간주
        return False
