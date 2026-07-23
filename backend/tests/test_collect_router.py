from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from app.activity import Activity
from app.routers import collect as collect_router
from app.settings_repo import Settings, SETTINGS_DEFAULTS


class Conn:
    def __init__(self):
        self.executed = []

    async def execute(self, sql, *args):
        self.executed.append((sql, args))


def _app(monkeypatch, run_result, worker_result):
    app = FastAPI()
    app.state.http = object()
    app.state.activity = Activity()
    app.include_router(collect_router.router)

    conn = Conn()
    async def _get_conn():
        yield conn
    app.dependency_overrides[collect_router.get_conn] = _get_conn
    app.state._test_conn = conn  # 테스트에서 run_log insert 검사용

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


async def test_manual_collect_reflects_progress_in_activity(monkeypatch):
    """수동 수집도 실행 중 activity에 노출되고, 완료 후 clear 되어야 /status에서 보임."""
    app = _app(monkeypatch, {"scraped": 5, "inserted": 5}, {})
    mid = {}

    async def fake_collect(conn, s, *, http, on_stage=None):
        on_stage("스크레이핑", "점핏·x·1p", 5)
        mid["snap"] = app.state.activity.snapshot()  # 실행 도중 스냅샷
        return {"scraped": 5, "inserted": 5}
    monkeypatch.setattr(collect_router, "collect", fake_collect)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/collect/run")

    assert r.status_code == 202
    # 실행 중엔 collector 슬롯이 진행상황으로 채워짐(모니터가 볼 수 있음)
    assert mid["snap"]["collector"] == {"stage": "스크레이핑", "detail": "점핏·x·1p", "progress": "5"}
    # 완료 후엔 clear
    assert app.state.activity.snapshot()["collector"] is None


async def test_manual_worker_reflects_progress_in_activity(monkeypatch):
    app = _app(monkeypatch, {}, {"claimed": 1, "done": 1, "failed": 0, "skipped_tick": False})
    mid = {}

    async def fake_worker(conn, s, *, http, on_stage=None):
        on_stage("요약 중", "토스", "1/1")
        mid["snap"] = app.state.activity.snapshot()
        return {"claimed": 1, "done": 1, "failed": 0, "skipped_tick": False}
    monkeypatch.setattr(collect_router, "worker_tick", fake_worker)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/collect/worker/run")

    assert r.status_code == 202
    assert mid["snap"]["worker"] == {"stage": "요약 중", "detail": "토스", "progress": "1/1"}
    assert app.state.activity.snapshot()["worker"] is None


async def test_manual_collect_writes_run_log(monkeypatch):
    app = _app(monkeypatch, {"scraped": 5, "inserted": 5}, {})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post("/api/collect/run")
    inserts = [a for (sql, a) in app.state._test_conn.executed if "INSERT INTO run_log" in sql]
    assert inserts, "run_log INSERT가 실행되어야 함"
    args = inserts[0]
    assert args[0] == "collector" and args[3] == "manual" and args[4] == "ok"
