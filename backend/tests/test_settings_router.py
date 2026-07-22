import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from app.routers import settings as settings_router
from app.settings_repo import Settings, SETTINGS_DEFAULTS, _COLUMNS


class FakeConn:
    def __init__(self, store): self.store = store
    async def fetchrow(self, sql, *params):
        if "INSERT" in sql:
            self.store["saved"] = params
            # Return a row dict so put_settings can construct Settings
            return dict(zip(_COLUMNS + ['updated_at'], params + (None,)))
        return None  # get은 기본값 경로


def _app(conn):
    app = FastAPI()
    app.include_router(settings_router.router)

    async def _get_conn():
        yield conn
    app.dependency_overrides[settings_router.get_conn] = _get_conn
    return app


async def test_get_returns_defaults_when_no_row():
    app = _app(FakeConn({}))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/settings")
    assert r.status_code == 200
    assert r.json()["batch_size"] == 20


async def test_put_validates_and_saves():
    store = {}
    app = _app(FakeConn(store))
    body = dict(SETTINGS_DEFAULTS, keywords=["백엔드"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.put("/api/settings", json=body)
    assert r.status_code == 200
    assert store["saved"][0] == ["백엔드"]


async def test_put_rejects_invalid():
    app = _app(FakeConn({}))
    body = dict(SETTINGS_DEFAULTS, keywords=["백엔드"], collect_hour=99)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.put("/api/settings", json=body)
    assert r.status_code == 422
