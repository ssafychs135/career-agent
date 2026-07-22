from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from app.routers import status as status_router
from app.activity import Activity
from app.settings_repo import Settings, SETTINGS_DEFAULTS


class Conn:
    async def fetch(self, sql, *a):
        if "GROUP BY status" in sql:
            return [{"status": "pending", "n": 7}, {"status": "done", "n": 3}]
        return [{"n": 1}]  # research_running
    async def fetchval(self, sql, *a): return 1


def _app(activity):
    app = FastAPI()
    app.state.activity = activity
    app.state.http = object()
    app.include_router(status_router.router)

    async def _get_conn():
        yield Conn()
    app.dependency_overrides[status_router.get_conn] = _get_conn

    async def fake_get_settings(conn):
        return Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], enabled=True))
    status_router.get_settings = fake_get_settings

    async def fake_health(http, base_url=None): return True
    status_router.llm_healthy = fake_health
    return app


async def test_status_shape():
    act = Activity()
    act.set_stage("worker", "요약 중", "토스", "4/20")
    async with AsyncClient(transport=ASGITransport(app=_app(act)), base_url="http://t") as c:
        r = await c.get("/api/status")
    body = r.json()
    assert r.status_code == 200
    assert body["activity"]["worker"]["stage"] == "요약 중"
    assert body["counts"]["pending"] == 7
    assert body["llm_health"] == "ok"
    assert body["enabled"] is True
