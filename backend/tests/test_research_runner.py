import pytest
from app.research import runner


class Recorder:
    def __init__(self):
        self.saved = []
        self.notified = []
        self.running = []


@pytest.fixture
def wired(monkeypatch):
    """store를 인메모리로, notify를 기록기로 교체."""
    rec = Recorder()
    state = {"company": {}, "job": {}, "job_meta": {}}

    async def get_company(db, company):
        return state["company"].get(company)

    async def get_job(db, source, job_id):
        return state["job"].get((source, job_id))

    async def get_job_meta(db, source, job_id):
        return state["job_meta"].get((source, job_id))

    async def mark_company_running(db, company):
        rec.running.append(("company", company))
        state["company"][company] = {"status": "running"}

    async def mark_job_running(db, source, job_id, company):
        rec.running.append(("job", source, job_id))
        state["job"][(source, job_id)] = {"status": "running"}

    async def save_company(db, company, **kw):
        rec.saved.append(("company", company, kw))
        state["company"][company] = {"status": kw["status"], **kw}

    async def save_job(db, source, job_id, company, **kw):
        rec.saved.append(("job", source, job_id, kw))
        state["job"][(source, job_id)] = {"status": kw["status"], **kw}

    for name, fn in dict(
        get_company=get_company, get_job=get_job, get_job_meta=get_job_meta,
        mark_company_running=mark_company_running, mark_job_running=mark_job_running,
        save_company=save_company, save_job=save_job,
    ).items():
        monkeypatch.setattr(runner.store, name, fn)

    async def notify(msg):
        rec.notified.append(msg)

    rec.state = notify_state = state
    rec.notify = notify
    return rec


def make_runner(*replies):
    replies = list(replies)

    async def fake(prompt, **kw):
        return replies.pop(0)

    return fake


async def test_company_cache_skip(wired):
    wired.state["company"]["토스"] = {"status": "done"}
    out = await runner.research_company(
        None, "토스", runner=make_runner('{"overview":"x"}'), notify=wired.notify,
    )
    assert out == "cached"
    assert wired.saved == []  # 재저장 없음


async def test_company_force_reresearches(wired):
    wired.state["company"]["토스"] = {"status": "done"}
    out = await runner.research_company(
        None, "토스", force=True,
        runner=make_runner('{"overview":"o","stability":"s","sources":["u"]}'),
        notify=wired.notify,
    )
    assert out == "done"
    kind, company, kw = wired.saved[0]
    assert kw["status"] == "done" and kw["overview"] == "o"
    assert wired.notified  # 완료 알림


async def test_company_parse_retry_then_success(wired):
    out = await runner.research_company(
        None, "토스",
        runner=make_runner("헛소리", '{"overview":"o"}'),  # 1차 실패 → 2차 성공
        notify=wired.notify,
    )
    assert out == "done"


async def test_company_failed_after_retry(wired):
    out = await runner.research_company(
        None, "토스",
        runner=make_runner("bad", "still bad"),
        notify=wired.notify,
    )
    assert out == "failed"
    assert wired.saved[-1][2]["status"] == "failed"


async def test_job_precedes_company_then_researches(wired):
    wired.state["job_meta"][("wanted", "42")] = {
        "company": "토스", "title": "백엔드", "tech_stacks": "Java",
        "summary": "s", "url": "https://x",
    }
    out = await runner.research_job(
        None, "wanted", "42",
        runner=make_runner(
            '{"overview":"o"}',                    # 기업 리서치
            '{"tech_detail":"t","role_detail":"r"}',  # 공고 리서치
        ),
        notify=wired.notify,
    )
    assert out == "done"
    kinds = [s[0] for s in wired.saved]
    assert kinds == ["company", "job"]  # 기업 먼저 저장


async def test_job_missing_raises(wired):
    with pytest.raises(LookupError):
        await runner.research_job(
            None, "wanted", "999",
            runner=make_runner('{"x":1}'), notify=wired.notify,
        )
