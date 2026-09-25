import json

import pytest

from app.run_log import classify, logged_run


class FakeConn:
    def __init__(self, prev=None):
        self.executed = []  # (sql, args)
        self.prev = prev    # 직전 스케줄 실행 행(없으면 None)

    async def execute(self, sql, *args):
        self.executed.append((sql, args))

    async def fetchrow(self, sql, *args):
        return self.prev


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


async def _scheduled_failure(monkeypatch, prev, error):
    pushed = []
    async def fake_push(msg):
        pushed.append(msg)
    monkeypatch.setattr("app.run_log.push", fake_push)
    conn = FakeConn(prev=prev)
    async def boom():
        raise RuntimeError(error)
    with pytest.raises(RuntimeError):
        await logged_run(conn, pipeline="worker", trigger="scheduled", run=boom)
    assert conn.executed[0][1][4] == "failed"  # 알림을 생략해도 기록은 남는다
    return pushed


_AUTH = "Failed to authenticate: OAuth session expired and could not be refreshed"


async def test_repeated_scheduled_failure_with_same_error_is_not_pushed_again(monkeypatch):
    """워커는 5분마다 돈다. 인증 장애가 이어지는 동안 같은 경보를 하루 288번 보내지 않는다."""
    pushed = await _scheduled_failure(
        monkeypatch, prev={"status": "failed", "error": _AUTH}, error=_AUTH)
    assert pushed == []


async def test_scheduled_failure_with_new_error_is_pushed(monkeypatch):
    pushed = await _scheduled_failure(
        monkeypatch, prev={"status": "failed", "error": "llm down"}, error=_AUTH)
    assert pushed and _AUTH[:40] in pushed[0]


async def test_scheduled_failure_after_success_is_pushed(monkeypatch):
    pushed = await _scheduled_failure(
        monkeypatch, prev={"status": "ok", "error": ""}, error=_AUTH)
    assert pushed and "요약 처리" in pushed[0]
