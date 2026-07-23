import json

import pytest

from app.run_log import classify, logged_run


class FakeConn:
    def __init__(self):
        self.executed = []  # (sql, args)

    async def execute(self, sql, *args):
        self.executed.append((sql, args))


def _run(value):
    async def _r():
        return value
    return _r


def test_classify_collector_and_worker():
    assert classify("collector", {"scraped": 1, "inserted": 1}) == "ok"
    assert classify("worker", {"skipped_tick": True}) == "skipped"
    assert classify("worker", {"skipped_tick": False, "done": 2, "failed": 0}) == "ok"


def test_classify_research_strings():
    assert classify("research", "done") == "ok"
    assert classify("research", "cached") == "skipped"
    assert classify("research", "failed") == "failed"


async def test_logged_run_records_ok_and_returns_result():
    conn = FakeConn()
    cleared = []
    result = await logged_run(
        conn, pipeline="collector", trigger="manual",
        clear=lambda: cleared.append(True),
        run=_run({"scraped": 3, "inserted": 3}),
    )
    assert result == {"scraped": 3, "inserted": 3}
    assert cleared == [True]
    sql, args = conn.executed[0]
    assert "INSERT INTO run_log" in sql
    assert args[0] == "collector"          # pipeline
    assert args[3] == "manual"             # trigger
    assert args[4] == "ok"                 # status
    assert json.loads(args[5]) == {"scraped": 3, "inserted": 3}  # result jsonb


async def test_logged_run_records_failed_and_reraises():
    conn = FakeConn()
    async def boom():
        raise RuntimeError("scrape down")
    with pytest.raises(RuntimeError):
        await logged_run(conn, pipeline="collector", trigger="manual", run=boom)
    sql, args = conn.executed[0]
    assert args[4] == "failed"
    assert "scrape down" in args[6]        # error column


async def test_scheduled_failure_pushes_discord(monkeypatch):
    pushed = []
    async def fake_push(msg):
        pushed.append(msg)
    monkeypatch.setattr("app.run_log.push", fake_push)
    conn = FakeConn()
    async def boom():
        raise RuntimeError("down")
    with pytest.raises(RuntimeError):
        await logged_run(conn, pipeline="collector", trigger="scheduled", run=boom)
    assert pushed and "실패" in pushed[0]


async def test_manual_failure_does_not_push(monkeypatch):
    pushed = []
    async def fake_push(msg):
        pushed.append(msg)
    monkeypatch.setattr("app.run_log.push", fake_push)
    conn = FakeConn()
    async def boom():
        raise RuntimeError("down")
    with pytest.raises(RuntimeError):
        await logged_run(conn, pipeline="collector", trigger="manual", run=boom)
    assert pushed == []


async def test_success_with_record_error_is_not_misclassified(monkeypatch):
    """run 성공 후 record()가 실패해도 '실행 실패'로 오분류/scheduled push 하지 않는다."""
    pushed = []
    async def fake_push(msg):
        pushed.append(msg)
    monkeypatch.setattr("app.run_log.push", fake_push)

    class FailingRecordConn:
        async def execute(self, sql, *args):
            raise RuntimeError("db down")

    with pytest.raises(RuntimeError, match="db down"):
        await logged_run(FailingRecordConn(), pipeline="collector", trigger="scheduled",
                         run=_run({"scraped": 1, "inserted": 1}))
    assert pushed == []  # 성공 실행이므로 실패 알림 없음
