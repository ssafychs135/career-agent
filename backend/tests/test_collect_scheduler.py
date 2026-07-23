import types
from app import collect_scheduler as cs
from app.activity import Activity


class FakeSched:
    def __init__(self): self.jobs = {}; self.started = False; self.shutdown_called = False
    def add_job(self, fn, trigger, id=None, **kw): self.jobs[id] = (trigger, kw)
    def reschedule_job(self, job_id, trigger=None, **kw): self.jobs[job_id] = (trigger, kw)
    def start(self): self.started = True
    def shutdown(self, wait=False): self.shutdown_called = True


def _app():
    app = types.SimpleNamespace()
    app.state = types.SimpleNamespace(
        db=object(), http=object(), activity=Activity(), collect_scheduler=None,
    )
    return app


def test_start_registers_two_jobs(monkeypatch):
    monkeypatch.setattr(cs, "AsyncIOScheduler", FakeSched)
    app = _app()
    cs.start_collect_scheduler(app)
    sched = app.state.collect_scheduler
    assert set(sched.jobs) == {"collector", "worker"}
    assert sched.started is True


def test_start_is_idempotent(monkeypatch):
    monkeypatch.setattr(cs, "AsyncIOScheduler", FakeSched)
    app = _app()
    cs.start_collect_scheduler(app)
    first = app.state.collect_scheduler
    cs.start_collect_scheduler(app)
    assert app.state.collect_scheduler is first


class _Conn:
    """pending 유무만 흉내내는 fake conn."""

    def __init__(self, has_pending):
        self._has_pending = has_pending
        self.peeked = False

    async def fetchval(self, sql, *args):
        if "status='pending'" in sql:
            self.peeked = True
            return 1 if self._has_pending else None
        return None


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False
        return _Ctx()


def _worker_ctx(monkeypatch, has_pending):
    from app.settings_repo import Settings, SETTINGS_DEFAULTS
    conn = _Conn(has_pending)
    calls = {"logged_run": 0, "worker_tick": 0}

    async def fake_get_settings(c):
        return Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], enabled=True))
    monkeypatch.setattr(cs, "get_settings", fake_get_settings)

    async def fake_worker_tick(*a, **kw):
        calls["worker_tick"] += 1
        return {"claimed": 0, "done": 0, "failed": 0, "skipped_tick": False}
    monkeypatch.setattr(cs, "worker_tick", fake_worker_tick)

    async def fake_logged_run(c, *, pipeline, trigger, run, **kw):
        calls["logged_run"] += 1
        calls["pipeline"], calls["trigger"] = pipeline, trigger
        return await run()
    monkeypatch.setattr(cs, "logged_run", fake_logged_run)

    return conn, calls, (lambda: (_Pool(conn), object(), Activity()))


async def test_worker_job_skips_entirely_when_no_pending(monkeypatch):
    """대기 0이면 LLM 요청(worker_tick)도, run_log 행(logged_run)도 만들지 않는다."""
    conn, calls, get_ctx = _worker_ctx(monkeypatch, has_pending=False)
    await cs.worker_job(get_ctx)
    assert conn.peeked is True
    assert calls["worker_tick"] == 0, "대기 0인데 워커가 실행됨(LLM 헬스 요청 발생)"
    assert calls["logged_run"] == 0, "대기 0인데 run_log 행이 기록됨"


async def test_worker_job_runs_when_pending_exists(monkeypatch):
    conn, calls, get_ctx = _worker_ctx(monkeypatch, has_pending=True)
    await cs.worker_job(get_ctx)
    assert calls["worker_tick"] == 1
    assert calls["logged_run"] == 1
    assert calls["pipeline"] == "worker" and calls["trigger"] == "scheduled"


def test_reschedule_updates_triggers(monkeypatch):
    monkeypatch.setattr(cs, "AsyncIOScheduler", FakeSched)
    app = _app()
    cs.start_collect_scheduler(app)
    from app.settings_repo import Settings, SETTINGS_DEFAULTS
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], collect_hour=6, worker_interval_min=10))
    cs.reschedule(app, s)
    sched = app.state.collect_scheduler
    assert sched.jobs["collector"][1]["hour"] == 6
    assert sched.jobs["worker"][1]["minutes"] == 10
