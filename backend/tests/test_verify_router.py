from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.activity import Activity
from app.routers import verify as verify_router


class FakeConn:
    def __init__(self):
        self.executed = []
    async def fetchrow(self, sql, *args): return None
    async def execute(self, sql, *args):
        self.executed.append(sql)
        return "UPDATE 0"
    async def fetchval(self, sql, *args): return None


class FakePool:
    """acquire()가 항상 같은 커넥션을 주는 풀 대역. 취득 횟수를 기록한다."""
    def __init__(self, conn):
        self._conn = conn
        self.acquires = 0
    def acquire(self):
        self.acquires += 1
        conn = self._conn
        class _Ctx:
            async def __aenter__(self): return conn
            async def __aexit__(self, *a): return False
        return _Ctx()


def make_app(pool):
    app = FastAPI()
    app.state.http = object()
    app.state.db = pool
    app.state.activity = Activity()
    app.include_router(verify_router.router)
    return app


def test_manual_verify_returns_immediately_and_sweeps_in_background(monkeypatch):
    """전수검사는 수백 건 API 순회(프로덕션 첫 실행 62초)라 응답을 붙들면 클라이언트가
    타임아웃한다 — 성공했는데도 실패로 보인다. 202는 접수만 알리고 작업은 뒤에서 돈다."""
    seen = {}

    async def fake_tick(conn, *, http, on_stage=None):
        seen["conn"] = conn
        return {"checked": 3, "closed": 1, "deleted": 0, "failed": 0}
    monkeypatch.setattr(verify_router, "verify_tick", fake_tick)

    pool_conn = FakeConn()
    pool = FakePool(pool_conn)
    with TestClient(make_app(pool)) as client:
        r = client.post("/api/verify/run")
        assert r.status_code == 202
        # 결과를 응답에 실으면 검사가 끝날 때까지 기다렸다는 뜻이다.
        assert r.json() == {"status": "running"}
    # TestClient는 응답 후 백그라운드 태스크를 실행한다 — 그때 실제로 돌았는지 확인.
    assert "conn" in seen, "백그라운드 태스크가 등록되지 않아 검사가 아예 돌지 않음"


def test_background_sweep_acquires_its_own_pool_connection(monkeypatch):
    """요청 스코프 conn은 응답과 함께 반납되므로 백그라운드에서 쓸 수 없다.
    틱은 풀에서 직접 얻은 커넥션으로 돌고, run_log도 같은 커넥션에 기록된다."""
    seen = {}

    async def fake_tick(conn, *, http, on_stage=None):
        seen["conn"] = conn
        return {"checked": 3, "closed": 1, "deleted": 0, "failed": 0}
    monkeypatch.setattr(verify_router, "verify_tick", fake_tick)

    pool_conn = FakeConn()
    pool = FakePool(pool_conn)
    with TestClient(make_app(pool)) as client:
        client.post("/api/verify/run")

    assert seen["conn"] is pool_conn
    assert pool.acquires == 1, "응답 전에 커넥션을 잡으면 접수만 하는 요청이 풀을 소비한다"
    assert any("run_log" in s for s in pool_conn.executed), "run_log 기록이 없음"


def test_activity_is_wired_so_progress_is_observable(monkeypatch):
    """응답에 결과가 실리지 않으므로 진행 상황은 activity로만 볼 수 있다 —
    on_stage를 연결하지 않으면 분 단위 실행이 화면에서 완전히 침묵한다."""
    mid = {}

    async def fake_tick(conn, *, http, on_stage=None):
        assert on_stage is not None, "on_stage가 연결되지 않음"
        on_stage("생존 확인", "wanted:111", "1/3")
        # 실행 중 스냅샷 — 끝나면 logged_run의 clear가 슬롯을 비운다.
        mid["snap"] = app.state.activity.snapshot()
        return {"checked": 3, "closed": 0, "deleted": 0, "failed": 0}
    monkeypatch.setattr(verify_router, "verify_tick", fake_tick)

    app = make_app(FakePool(FakeConn()))
    with TestClient(app) as client:
        client.post("/api/verify/run")

    # snapshot이 verify를 노출하지 않으면 스케줄 잡의 set_stage("verify")도 죽은 코드다.
    assert mid["snap"]["verify"] == {"stage": "생존 확인", "detail": "wanted:111", "progress": "1/3"}
    assert app.state.activity.snapshot()["verify"] is None   # 끝나면 정리된다
