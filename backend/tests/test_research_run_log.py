from app.routers import research as research_router


class FakeConn:
    def __init__(self):
        self.executed = []

    async def execute(self, sql, *args):
        self.executed.append((sql, args))


class FakePool:
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


async def test_logged_company_writes_run_log(monkeypatch):
    conn = FakeConn()
    pool = FakePool(conn)

    async def fake_research_company(db, company, url="", *, settings=None, force=False, activity=None):
        return "done"
    monkeypatch.setattr(research_router.runner, "research_company", fake_research_company)

    await research_router._logged_company(pool, "미스릴", settings=None, force=False, activity=None)

    inserts = [a for (sql, a) in conn.executed if "INSERT INTO run_log" in sql]
    assert inserts, "run_log INSERT가 실행되어야 함"
    args = inserts[0]
    assert args[0] == "research"      # pipeline
    assert args[1] == "미스릴"         # ref
    assert args[3] == "manual"        # trigger
    assert args[4] == "ok"            # status ("done" → ok)


async def test_logged_job_writes_run_log(monkeypatch):
    conn = FakeConn()
    pool = FakePool(conn)

    async def fake_research_job(db, source, job_id, *, settings=None, force=False, activity=None):
        return "cached"
    monkeypatch.setattr(research_router.runner, "research_job", fake_research_job)

    await research_router._logged_job(
        pool, "wanted", "123", label="백엔드 개발자", settings=None, force=False, activity=None,
    )
    inserts = [a for (sql, a) in conn.executed if "INSERT INTO run_log" in sql]
    args = inserts[0]
    assert args[0] == "research"
    assert args[1] == "wanted:123"    # ref
    assert args[2] == "백엔드 개발자"   # label
    assert args[4] == "skipped"       # "cached" → skipped
