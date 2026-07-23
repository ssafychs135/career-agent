from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.routers import runs as runs_router


def _app(monkeypatch, payload):
    app = FastAPI()
    app.include_router(runs_router.router)

    async def _get_conn():
        yield object()
    app.dependency_overrides[runs_router.get_conn] = _get_conn

    captured = {}
    async def fake_list_runs(conn, *, pipeline=None, status=None, limit=30):
        captured.update(pipeline=pipeline, status=status, limit=limit)
        return payload
    monkeypatch.setattr(runs_router, "list_runs", fake_list_runs)
    return app, captured


async def test_get_runs_returns_items(monkeypatch):
    app, captured = _app(monkeypatch, {"items": [{"id": 1, "pipeline": "collector"}]})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/runs?limit=5&pipeline=collector")
    assert r.status_code == 200
    assert r.json()["items"][0]["pipeline"] == "collector"
    assert captured == {"pipeline": "collector", "status": None, "limit": 5}
