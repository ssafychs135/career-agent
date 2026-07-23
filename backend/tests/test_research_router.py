from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.db  # Plan ② 제공 (계약 1번: get_conn/connect/close)
from app.activity import Activity
from app.routers import research


class _FakePoolConn:
    """로그인 테스트용 fake conn."""
    async def execute(self, sql, *args):
        pass


class _FakeReqConn:
    """요청 스코프 conn 대역. get_settings가 기본 설정을 얻도록 fetchrow가 None을 반환."""
    async def fetchrow(self, sql, *args):
        return None

    async def execute(self, sql, *args):
        pass


class _FakePool:
    """로그인 테스트용 fake pool with acquire()."""
    def __init__(self):
        self._conn = _FakePoolConn()

    def acquire(self):
        conn = self._conn
        class _Ctx:
            async def __aenter__(self):
                return conn
            async def __aexit__(self, *a):
                return False
        return _Ctx()


def make_app(monkeypatch):
    """research 라우터가 붙고 get_conn·app.state.db가 갖춰진 테스트 앱."""
    app = FastAPI()
    app.state.db = _FakePool()  # BackgroundTask로 넘길 풀 자리(러너는 fake라 실사용 안 함)
    app.state.activity = Activity()  # 라우터가 러너로 넘길 activity
    research.init_research(app)
    # 계약 1번 정본 의존성 이름 = get_conn. request 스코프 conn 오버라이드.
    app.dependency_overrides[research.get_conn] = lambda: _FakeReqConn()
    return app


def test_company_trigger_marks_running_then_202(monkeypatch):
    ran = []
    app = make_app(monkeypatch)

    async def fake_company(db, company, url="", *, settings=None, force=False, activity=None):
        ran.append(("company", company, force))

    async def fake_mark(conn, company):
        ran.append(("mark", company))

    monkeypatch.setattr(research.runner, "research_company", fake_company)
    monkeypatch.setattr(research.store, "mark_company_running", fake_mark)

    r = TestClient(app).post("/api/research/company", json={"company": "토스"})
    assert r.status_code == 202
    assert r.json()["status"] == "running"
    assert ("mark", "토스") in ran               # 202 전 running upsert(계약 7번)
    assert ("company", "토스", False) in ran      # BackgroundTask 실행됨


def test_job_trigger_404_when_missing(monkeypatch):
    app = make_app(monkeypatch)

    async def missing(conn, source, job_id):
        return None

    monkeypatch.setattr(research.store, "get_job_meta", missing)
    r = TestClient(app).post(
        "/api/research/job", json={"source": "wanted", "job_id": "999"}
    )
    assert r.status_code == 404


def test_job_trigger_marks_running_then_202(monkeypatch):
    ran = []
    app = make_app(monkeypatch)

    async def found(conn, source, job_id):
        return {"company": "토스"}

    async def fake_mark(conn, source, job_id, company):
        ran.append(("mark", source, job_id, company))

    async def fake_job(db, source, job_id, *, settings=None, force=False, activity=None):
        ran.append((source, job_id, force))

    monkeypatch.setattr(research.store, "get_job_meta", found)
    monkeypatch.setattr(research.store, "mark_job_running", fake_mark)
    monkeypatch.setattr(research.runner, "research_job", fake_job)
    r = TestClient(app).post(
        "/api/research/job", json={"source": "wanted", "job_id": "42", "force": True}
    )
    assert r.status_code == 202
    assert ("mark", "wanted", "42", "토스") in ran  # 202 전 running upsert(계약 7번)
    assert ("wanted", "42", True) in ran


def test_company_trigger_passes_settings_to_runner(monkeypatch):
    """설정 조회는 202 응답 전에 끝나야 한다 — 러너가 몇 분씩 conn을 붙들면 풀이 마른다."""
    seen = {}
    app = make_app(monkeypatch)

    async def fake_company(db, company, url="", *, settings=None, force=False, activity=None):
        seen["settings"] = settings

    async def fake_mark(conn, company):
        pass

    monkeypatch.setattr(research.runner, "research_company", fake_company)
    monkeypatch.setattr(research.store, "mark_company_running", fake_mark)

    r = TestClient(app).post("/api/research/company", json={"company": "토스"})
    assert r.status_code == 202
    assert seen["settings"] is not None
    assert seen["settings"].research_model == ""   # 기본 설정이 전달됨
