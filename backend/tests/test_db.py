from types import SimpleNamespace

import app.db as db


async def test_connect_uses_database_url(monkeypatch):
    seen = {}

    async def fake_create_pool(dsn, **kw):
        seen["dsn"] = dsn
        seen["kw"] = kw
        return "POOL"

    monkeypatch.setattr(db.asyncpg, "create_pool", fake_create_pool)
    monkeypatch.setenv("DATABASE_URL", "postgresql://n8n:pw@postgres:5432/jobs")
    pool = await db.connect()
    assert pool == "POOL"
    assert seen["dsn"] == "postgresql://n8n:pw@postgres:5432/jobs"
    assert seen["kw"]["min_size"] == 1 and seen["kw"]["max_size"] == 10


async def test_get_conn_yields_from_app_state():
    conn_obj = object()

    class FakeAcquire:
        async def __aenter__(self):
            return conn_obj

        async def __aexit__(self, *a):
            return False

    class FakePool:
        def acquire(self):
            return FakeAcquire()

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=FakePool())))
    gen = db.get_conn(request)
    got = await gen.__anext__()
    assert got is conn_obj
    await gen.aclose()
