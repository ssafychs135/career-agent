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
        return self.store.get("row")


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
    assert r.json()["summary_backend"] == "claude"


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


async def test_get_legacy_row_is_effective_claude_without_write_then_save_normalizes():
    legacy = dict(SETTINGS_DEFAULTS, summary_backend="local", model="legacy-model")
    store = {"row": legacy.copy()}
    app = _app(FakeConn(store))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/settings")
        assert r.status_code == 200
        assert r.json()["summary_backend"] == "claude"
        assert r.json()["model"] == "legacy-model"
        assert store == {"row": legacy}
        payload = r.json()
        payload["batch_size"] = 30
        saved = await c.put("/api/settings", json=payload)
    assert saved.status_code == 200
    assert store["saved"][_COLUMNS.index("summary_backend")] == "claude"
    assert store["saved"][_COLUMNS.index("model")] == "legacy-model"
    assert saved.json()["batch_size"] == 30


async def test_put_legacy_backend_normalizes_and_preserves_required_model():
    store = {}
    async with AsyncClient(transport=ASGITransport(app=_app(FakeConn(store))), base_url="http://t") as c:
        r = await c.put("/api/settings", json=dict(SETTINGS_DEFAULTS, summary_backend="local", model="old-model"))
    assert r.status_code == 200
    assert r.json()["summary_backend"] == "claude"
    assert store["saved"][_COLUMNS.index("summary_backend")] == "claude"
    assert store["saved"][_COLUMNS.index("model")] == "old-model"


@pytest.mark.parametrize("invalid", [{"summary_backend": "gpt"}, {"summary_backend": ""},
                                    {"summary_backend": None}, {"model": ""}, {"model": None}])
async def test_put_invalid_legacy_fields_rejected_without_write(invalid):
    store = {}
    async with AsyncClient(transport=ASGITransport(app=_app(FakeConn(store))), base_url="http://t") as c:
        r = await c.put("/api/settings", json=dict(SETTINGS_DEFAULTS, **invalid))
    assert r.status_code == 422
    assert "saved" not in store
