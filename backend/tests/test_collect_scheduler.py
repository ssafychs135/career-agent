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
