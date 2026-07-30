import types
from app import collect_scheduler as cs
from app.activity import Activity


class FakeSched:
    def __init__(self, **kw):
        self.jobs = {}; self.started = False; self.shutdown_called = False
        self.init_kw = kw
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


def test_start_registers_four_jobs(monkeypatch):
    monkeypatch.setattr(cs, "AsyncIOScheduler", FakeSched)
    app = _app()
    cs.start_collect_scheduler(app)
    sched = app.state.collect_scheduler
    assert set(sched.jobs) == {"collector", "worker", "notifier", "verify"}
    assert sched.started is True


def test_scheduler_is_built_with_seoul_timezone(monkeypatch):
    # 백엔드 컨테이너에 TZ가 없어 프로세스 로컬은 UTC다. 타임존을 명시하지 않으면
    # collect_hour=9가 09:00 UTC = 18:00 KST에 돌아 사용자 의도와 9시간 어긋난다.
    monkeypatch.setattr(cs, "AsyncIOScheduler", FakeSched)
    app = _app()
    cs.start_collect_scheduler(app)
    assert app.state.collect_scheduler.init_kw.get("timezone") == "Asia/Seoul"


def test_cron_triggers_actually_resolve_to_seoul(monkeypatch):
    """APScheduler가 실제로 그 타임존을 크론 트리거에 적용하는지 — 등록 시점과 재스케줄 후 모두."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    sched = AsyncIOScheduler(timezone=cs.SCHED_TZ)
    job = sched.add_job(lambda: None, "cron", id="collector", hour=9, minute=0)
    assert str(job.trigger.timezone) == "Asia/Seoul"
    assert job.trigger.fields[job.trigger.FIELD_NAMES.index("hour")].expressions[0].first == 9
    sched.reschedule_job("collector", trigger="cron", hour=7, minute=0)
    t = sched.get_job("collector").trigger
    assert str(t.timezone) == "Asia/Seoul"   # 재스케줄해도 타임존이 유지되어야 함
    assert t.fields[t.FIELD_NAMES.index("hour")].expressions[0].first == 7


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


def _notify_ctx(monkeypatch, *, enabled, has_unsent):
    from app.settings_repo import Settings, SETTINGS_DEFAULTS
    calls = {"logged_run": 0, "notify_tick": 0}

    class _C:
        async def fetchval(self, sql, *args):
            return 1 if ("notified_at IS NULL" in sql and has_unsent) else None

    conn = _C()

    async def fake_get_settings(c):
        return Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], notify_enabled=enabled))
    monkeypatch.setattr(cs, "get_settings", fake_get_settings)

    async def fake_notify_tick(*a, **kw):
        calls["notify_tick"] += 1
        return {"picked": 0, "sent": 0, "skipped": 0}
    monkeypatch.setattr(cs, "notify_tick", fake_notify_tick)

    async def fake_logged_run(c, *, pipeline, trigger, run, **kw):
        calls["logged_run"] += 1
        calls["pipeline"], calls["trigger"] = pipeline, trigger
        return await run()
    monkeypatch.setattr(cs, "logged_run", fake_logged_run)

    return calls, (lambda: (_Pool(conn), object(), Activity()))


async def test_notifier_job_noop_when_disabled(monkeypatch):
    calls, get_ctx = _notify_ctx(monkeypatch, enabled=False, has_unsent=True)
    await cs.notifier_job(get_ctx)
    assert calls["notify_tick"] == 0 and calls["logged_run"] == 0


async def test_notifier_job_skips_when_nothing_unsent(monkeypatch):
    calls, get_ctx = _notify_ctx(monkeypatch, enabled=True, has_unsent=False)
    await cs.notifier_job(get_ctx)
    assert calls["notify_tick"] == 0, "미전송 0건인데 발송 시도됨"
    assert calls["logged_run"] == 0, "미전송 0건인데 run_log 행이 기록됨"


async def test_notifier_job_runs_when_enabled_and_unsent(monkeypatch):
    calls, get_ctx = _notify_ctx(monkeypatch, enabled=True, has_unsent=True)
    await cs.notifier_job(get_ctx)
    assert calls["notify_tick"] == 1 and calls["logged_run"] == 1
    assert calls["pipeline"] == "notifier" and calls["trigger"] == "scheduled"


def test_start_registers_verify_job_at_midnight(monkeypatch):
    monkeypatch.setattr(cs, "AsyncIOScheduler", FakeSched)
    app = _app()
    cs.start_collect_scheduler(app)
    sched = app.state.collect_scheduler
    assert "verify" in sched.jobs
    trigger, kw = sched.jobs["verify"]
    assert trigger == "cron" and kw["hour"] == 0 and kw["minute"] == 0


async def test_verify_job_noop_when_disabled(monkeypatch):
    """enabled=false면 재검증도 돌지 않는다(수집기·워커와 동일한 컷오버 규칙)."""
    from app.settings_repo import Settings, SETTINGS_DEFAULTS
    calls = {"verify_tick": 0, "logged_run": 0}

    async def fake_get_settings(c):
        return Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], enabled=False))
    monkeypatch.setattr(cs, "get_settings", fake_get_settings)

    async def fake_verify_tick(*a, **kw):
        calls["verify_tick"] += 1
        return {"checked": 0, "closed": 0, "deleted": 0, "failed": 0}
    monkeypatch.setattr(cs, "verify_tick", fake_verify_tick)

    async def fake_logged_run(c, *, pipeline, trigger, run, **kw):
        calls["logged_run"] += 1
        return await run()
    monkeypatch.setattr(cs, "logged_run", fake_logged_run)

    conn = _Conn(has_pending=False)
    await cs.verify_job(lambda: (_Pool(conn), object(), Activity()))
    assert calls == {"verify_tick": 0, "logged_run": 0}


async def test_verify_job_runs_when_enabled(monkeypatch):
    from app.settings_repo import Settings, SETTINGS_DEFAULTS
    calls = {"verify_tick": 0, "pipeline": None, "trigger": None}

    async def fake_get_settings(c):
        return Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], enabled=True))
    monkeypatch.setattr(cs, "get_settings", fake_get_settings)

    async def fake_verify_tick(*a, **kw):
        calls["verify_tick"] += 1
        return {"checked": 1, "closed": 0, "deleted": 0, "failed": 0}
    monkeypatch.setattr(cs, "verify_tick", fake_verify_tick)

    async def fake_logged_run(c, *, pipeline, trigger, run, **kw):
        calls["pipeline"], calls["trigger"] = pipeline, trigger
        return await run()
    monkeypatch.setattr(cs, "logged_run", fake_logged_run)

    conn = _Conn(has_pending=False)
    await cs.verify_job(lambda: (_Pool(conn), object(), Activity()))
    assert calls["verify_tick"] == 1
    assert calls["pipeline"] == "verify" and calls["trigger"] == "scheduled"
