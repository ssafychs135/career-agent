from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.routers import notify as notify_router


async def test_manual_notify_runs_regardless_of_enabled_flag(monkeypatch):
    from app.settings_repo import Settings, SETTINGS_DEFAULTS
    app = FastAPI()
    app.include_router(notify_router.router)

    class _Conn: pass

    async def _get_conn():
        yield _Conn()
    app.dependency_overrides[notify_router.get_conn] = _get_conn

    async def fake_get_settings(conn):
        # 수동 실행은 마스터 스위치가 꺼져 있어도 동작해야 한다(컷오버 검증용).
        return Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], notify_enabled=False))
    monkeypatch.setattr(notify_router, "get_settings", fake_get_settings)

    seen = {}

    async def fake_logged_run(conn, *, pipeline, trigger, run, **kw):
        seen.update(pipeline=pipeline, trigger=trigger)
        return await run()
    monkeypatch.setattr(notify_router, "logged_run", fake_logged_run)

    async def fake_notify_tick(conn, settings, **kw):
        return {"picked": 3, "sent": 2, "skipped": 1}
    monkeypatch.setattr(notify_router, "notify_tick", fake_notify_tick)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/notify/run")
    assert r.status_code == 202
    assert r.json() == {"picked": 3, "sent": 2, "skipped": 1}
    assert seen == {"pipeline": "notifier", "trigger": "manual"}
