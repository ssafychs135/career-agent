import pytest

from app.notify.notifier import notify_tick
from app.settings_repo import SETTINGS_DEFAULTS, Settings


def _settings(**kw):
    return Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], **kw))


def _row(i, company="미스릴", locations="서울 강남구"):
    return dict(id=i, source="wanted", job_id=str(i), company=company, title=f"t{i}",
                url=f"https://x/{i}", locations=locations, min_career=1, max_career=3,
                tech_stacks=["python"], summary="요약")


class FakeConn:
    def __init__(self, rows, lock_ok=True):
        self._rows = rows
        self._lock_ok = lock_ok
        self.marked = []          # 마킹된 id 묶음(호출 단위)
        self.unlocked = False

    async def fetch(self, sql, *args):
        return self._rows

    async def fetchval(self, sql, *args):
        if "pg_try_advisory_lock" in sql:
            return self._lock_ok
        return None

    async def execute(self, sql, *args):
        if "notified_at=now()" in sql:
            self.marked.append(list(args[0]))
        elif "pg_advisory_unlock" in sql:
            self.unlocked = True


async def test_no_rows_sends_and_marks_nothing():
    conn = FakeConn([])
    sent = []
    out = await notify_tick(conn, _settings(), sender=lambda c, e: sent.append(e))
    assert out == {"picked": 0, "sent": 0, "skipped": 0}
    assert sent == [] and conn.marked == []


async def test_filtered_rows_are_marked_without_sending():
    conn = FakeConn([_row(1, company="미스릴"), _row(2, company="토스")])
    sent = []

    async def sender(content, embeds):
        sent.append([e["title"] for e in embeds])

    out = await notify_tick(conn, _settings(hidden_companies=["미스릴"]), sender=sender)
    assert out == {"picked": 2, "sent": 1, "skipped": 1}
    # 걸러진 1번은 발송 없이 소비, 통과한 2번은 발송 후 마킹
    assert conn.marked[0] == [1]
    assert any(2 in m for m in conn.marked[1:])
    assert len(sent) == 1 and "토스" in sent[0][0]


async def test_chunks_are_marked_per_chunk():
    conn = FakeConn([_row(i) for i in range(1, 26)])  # 25건 → 10/10/5
    async def sender(content, embeds):
        return None
    out = await notify_tick(conn, _settings(), sender=sender)
    assert out == {"picked": 25, "sent": 25, "skipped": 0}
    assert [len(m) for m in conn.marked] == [10, 10, 5]


async def test_mid_chunk_failure_marks_only_successful_chunks():
    """중간 청크가 실패하면 성공분만 소비되고 예외가 전파된다 — 재발송(중복) 방지."""
    conn = FakeConn([_row(i) for i in range(1, 26)])
    calls = {"n": 0}

    async def flaky(content, embeds):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("discord 5xx")

    with pytest.raises(RuntimeError):
        await notify_tick(conn, _settings(), sender=flaky)
    assert [len(m) for m in conn.marked] == [10]   # 1번 청크만 마킹


async def test_lock_not_acquired_sends_nothing():
    """동시 실행 방지: advisory lock을 못 잡으면 아무것도 조회·발송하지 않는다."""
    conn = FakeConn([_row(1)], lock_ok=False)
    sent = []
    out = await notify_tick(conn, _settings(), sender=lambda c, e: sent.append(e))
    assert out == {"picked": 0, "sent": 0, "skipped": 0}
    assert sent == [] and conn.marked == []


async def test_first_chunk_carries_header_content():
    conn = FakeConn([_row(i) for i in range(1, 13)])  # 12건 → 10/2
    contents = []

    async def sender(content, embeds):
        contents.append(content)

    await notify_tick(conn, _settings(), sender=sender)
    assert "새 채용 공고 12건" in contents[0]
    assert contents[1] is None
