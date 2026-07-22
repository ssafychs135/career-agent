from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from app.routers import collect as collect_router
from app.settings_repo import Settings, SETTINGS_DEFAULTS


class Conn: pass


def _app(monkeypatch, run_result, worker_result):
    app = FastAPI()
    app.state.http = object()
    app.include_router(collect_router.router)

    async def _get_conn():
        yield Conn()
    app.dependency_overrides[collect_router.get_conn] = _get_conn

    async def fake_get_settings(conn):
        return Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"]))
    monkeypatch.setattr(collect_router, "get_settings", fake_get_settings)

    async def fake_collect(conn, s, *, http, on_stage=None): return run_result
    async def fake_worker(conn, s, *, http, on_stage=None): return worker_result
    monkeypatch.setattr(collect_router, "collect", fake_collect)
    monkeypatch.setattr(collect_router, "worker_tick", fake_worker)
    return app


async def test_collect_run(monkeypatch):
    app = _app(monkeypatch, {"scraped": 3, "inserted": 3}, {})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/collect/run")
    assert r.status_code == 202 and r.json()["scraped"] == 3


async def test_worker_run(monkeypatch):
    app = _app(monkeypatch, {}, {"claimed": 2, "done": 2, "failed": 0, "skipped_tick": False})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/collect/worker/run")
    assert r.status_code == 202 and r.json()["done"] == 2
