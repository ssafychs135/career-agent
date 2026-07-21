from fastapi.testclient import TestClient
from app import main
from app.db import get_conn


class FakeConn:
    async def fetchval(self, sql, *a):
        if "count" in sql.lower():
            return 42
        return 1  # pgvector 존재 여부 쿼리(SELECT 1 ...)


def test_db_health_ok():
    async def fake_conn():
        yield FakeConn()

    main.app.dependency_overrides[get_conn] = fake_conn
    try:
        r = TestClient(main.app).get("/api/db/health")
        assert r.status_code == 200
        assert r.json() == {"ok": True, "jobs_count": 42, "pgvector": True}
    finally:
        main.app.dependency_overrides.clear()


def test_db_health_failure():
    class BoomConn:
        async def fetchval(self, sql, *a):
            raise RuntimeError("db down")

    async def boom_conn():
        yield BoomConn()

    main.app.dependency_overrides[get_conn] = boom_conn
    try:
        r = TestClient(main.app).get("/api/db/health")
        assert r.status_code == 503
    finally:
        main.app.dependency_overrides.clear()
