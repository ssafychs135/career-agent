from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import verify as verify_router


class FakeConn:
    async def fetchrow(self, sql, *args): return None
    async def execute(self, sql, *args): return "UPDATE 0"
    async def fetchval(self, sql, *args): return None


def make_app(monkeypatch):
    app = FastAPI()
    app.state.http = object()
    app.include_router(verify_router.router)
    app.dependency_overrides[verify_router.get_conn] = lambda: FakeConn()
    return app


def test_manual_verify_returns_counts(monkeypatch):
    async def fake_tick(conn, *, http, on_stage=None):
        return {"checked": 3, "closed": 1, "deleted": 0, "failed": 0}
    monkeypatch.setattr(verify_router, "verify_tick", fake_tick)
    app = make_app(monkeypatch)
    r = TestClient(app).post("/api/verify/run")
    assert r.status_code == 202
    assert r.json()["closed"] == 1 and r.json()["checked"] == 3
