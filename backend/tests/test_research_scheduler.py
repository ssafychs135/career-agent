from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.research import scheduler


def _app_with_scheduler_lifespan():
    """Plan ②의 단일 lifespan을 재현: startup→start_scheduler, shutdown→stop_scheduler."""

    @asynccontextmanager
    async def lifespan(app):
        app.state.db = object()          # tick이 참조(테스트에선 30분 잡 미발화)
        scheduler.start_scheduler(app)
        try:
            yield
        finally:
            scheduler.stop_scheduler(app)

    return FastAPI(lifespan=lifespan)


def test_disabled_by_default_is_noop(monkeypatch):
    monkeypatch.setattr(scheduler, "RESEARCH_AUTO_ENABLED", False)
    app = _app_with_scheduler_lifespan()
    with TestClient(app):                # lifespan startup/shutdown 실행
        assert app.state.research_scheduler is None   # no-op


def test_enabled_starts_and_stops_in_lifespan(monkeypatch):
    monkeypatch.setattr(scheduler, "RESEARCH_AUTO_ENABLED", True)
    monkeypatch.setattr(scheduler, "RESEARCH_AUTO_INTERVAL_MIN", 30)
    app = _app_with_scheduler_lifespan()
    with TestClient(app):
        sched = app.state.research_scheduler
        assert sched is not None
        assert sched.running
        assert len(sched.get_jobs()) == 1
    assert app.state.research_scheduler is None        # 컨텍스트 종료 시 stop


def test_start_scheduler_is_idempotent(monkeypatch):
    monkeypatch.setattr(scheduler, "RESEARCH_AUTO_ENABLED", True)
    monkeypatch.setattr(scheduler, "RESEARCH_AUTO_INTERVAL_MIN", 30)
    app = _app_with_scheduler_lifespan()
    with TestClient(app):
        first = app.state.research_scheduler
        scheduler.start_scheduler(app)   # 두 번째 호출 — 멱등(같은 스케줄러 유지, 잡 중복 없음)
        assert app.state.research_scheduler is first
        assert len(first.get_jobs()) == 1


async def test_tick_processes_pending(monkeypatch):
    calls = []

    async def pending_companies(db, limit):
        return ["토스"]

    async def pending_jobs(db, limit):
        return [("wanted", "42")]

    async def research_company(db, company, **kw):
        calls.append(("company", company))

    async def research_job(db, source, job_id, **kw):
        calls.append(("job", source, job_id))

    monkeypatch.setattr(scheduler.store, "pending_companies", pending_companies)
    monkeypatch.setattr(scheduler.store, "pending_jobs", pending_jobs)
    monkeypatch.setattr(scheduler.runner, "research_company", research_company)
    monkeypatch.setattr(scheduler.runner, "research_job", research_job)

    await scheduler.tick(lambda: object())
    assert calls == [("company", "토스"), ("job", "wanted", "42")]
