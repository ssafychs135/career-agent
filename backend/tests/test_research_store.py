import json
from app.research import store


class FakeDB:
    """asyncpg Pool 흉내: fetchrow/fetch/execute 호출·인자 기록."""

    def __init__(self, fetchrow=None, fetch=None):
        self._fetchrow = fetchrow
        self._fetch = fetch or []
        self.calls = []

    async def fetchrow(self, q, *a):
        self.calls.append(("fetchrow", q, a))
        return self._fetchrow

    async def fetch(self, q, *a):
        self.calls.append(("fetch", q, a))
        return self._fetch

    async def execute(self, q, *a):
        self.calls.append(("execute", q, a))
        return "OK"


async def test_get_company_returns_dict():
    db = FakeDB(fetchrow={"company": "토스", "status": "done"})
    assert await store.get_company(db, "토스") == {"company": "토스", "status": "done"}


async def test_get_company_none_when_missing():
    assert await store.get_company(FakeDB(fetchrow=None), "x") is None


async def test_mark_company_running_upserts_running():
    db = FakeDB()
    await store.mark_company_running(db, "토스")
    q, a = db.calls[0][1], db.calls[0][2]
    assert "company_research" in q and "running" in q
    assert a == ("토스",)


async def test_save_company_serializes_jsonb():
    db = FakeDB()
    await store.save_company(
        db, "토스", status="done", overview="o", stability="s",
        data={"k": "v"}, sources=["u1"], model="m",
    )
    args = db.calls[0][2]
    # data·sources는 json.dumps 된 문자열로 전달
    assert json.loads(args[3]) == {"k": "v"}
    assert json.loads(args[4]) == ["u1"]
    assert "done" in db.calls[0][1] or "done" in args


async def test_save_job_upsert_and_null_json():
    db = FakeDB()
    await store.save_job(db, "wanted", "42", "토스", status="failed")
    q, a = db.calls[0][1], db.calls[0][2]
    assert "job_research" in q
    assert a[0] == "wanted" and a[1] == "42" and a[2] == "토스"


async def test_pending_companies_maps_rows():
    db = FakeDB(fetch=[{"company": "A"}, {"company": "B"}])
    assert await store.pending_companies(db, 5) == ["A", "B"]


async def test_pending_jobs_maps_tuples():
    db = FakeDB(fetch=[{"source": "s", "job_id": "1"}])
    assert await store.pending_jobs(db, 5) == [("s", "1")]
