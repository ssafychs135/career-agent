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


async def _tick(conn, settings=None, **kw):
    """테스트에서는 레이트리밋 간격을 0으로 — 발송 순서·격리만 검증한다."""
    return await notify_tick(conn, settings or _settings(), gap=0, **kw)


async def test_no_rows_sends_and_marks_nothing():
    conn = FakeConn([])
    sent = []
    out = await _tick(conn, sender=lambda c, e: sent.append(e))
    assert out == {"picked": 0, "sent": 0, "skipped": 0, "failed": 0}
    assert sent == [] and conn.marked == []


async def test_filtered_rows_are_marked_without_sending():
    conn = FakeConn([_row(1, company="미스릴"), _row(2, company="토스")])
    sent = []

    async def sender(content, embeds):
        sent.append([e["title"] for e in embeds])

    out = await _tick(conn, _settings(hidden_companies=["미스릴"]), sender=sender)
    assert out == {"picked": 2, "sent": 1, "skipped": 1, "failed": 0}
    # 걸러진 1번은 발송 없이 소비, 통과한 2번은 발송 후 마킹
    assert conn.marked[0] == [1]
    assert any(2 in m for m in conn.marked[1:])
    assert len(sent) == 1 and "토스" in sent[0][0]


async def test_sends_one_embed_per_message():
    """디스코드가 여러 임베드를 묶은 메시지를 500으로 거절해 한 건씩 보낸다.
    (임베드 9개 묶음은 실패, 같은 9건을 따로 보내면 전부 204로 성공했다.)"""
    conn = FakeConn([_row(i) for i in range(1, 26)])
    sizes = []

    async def sender(content, embeds):
        sizes.append(len(embeds))

    out = await _tick(conn, sender=sender)
    assert out == {"picked": 25, "sent": 25, "skipped": 0, "failed": 0}
    assert sizes == [1] * 25                      # 묶음 발송이 남아있지 않다
    assert [len(m) for m in conn.marked] == [1] * 25   # 건별 마킹


async def test_one_failure_does_not_block_the_rest():
    """이 브랜치의 핵심 회귀 테스트. 예전에는 발송 하나가 실패하면 예외가 틱 전체를
    중단시켰고, 실패한 행이 notified_at=NULL로 남아 다음 틱이 같은 배치를 그대로
    재시도했다 — 5분마다 90분간 같은 실패를 반복하며 영원히 빠져나오지 못했다."""
    conn = FakeConn([_row(i) for i in range(1, 6)])

    async def flaky(content, embeds):
        if embeds[0]["title"].endswith("t2"):
            raise RuntimeError("discord 500")

    out = await _tick(conn, sender=flaky)
    assert out == {"picked": 5, "sent": 4, "skipped": 0, "failed": 1}
    marked = [i for m in conn.marked for i in m]
    assert marked == [1, 3, 4, 5]        # 실패한 2번만 미소비 → 다음 틱에 재시도
    assert 2 not in marked


async def test_all_failures_are_counted_and_nothing_is_marked():
    conn = FakeConn([_row(i) for i in range(1, 4)])

    async def always_fail(content, embeds):
        raise RuntimeError("discord 500")

    out = await _tick(conn, sender=always_fail)
    assert out == {"picked": 3, "sent": 0, "skipped": 0, "failed": 3}
    assert conn.marked == []            # 전부 다음 틱에 재시도된다


async def test_lock_not_acquired_sends_nothing():
    """동시 실행 방지: advisory lock을 못 잡으면 아무것도 조회·발송하지 않는다."""
    conn = FakeConn([_row(1)], lock_ok=False)
    sent = []
    out = await _tick(conn, sender=lambda c, e: sent.append(e))
    assert out == {"picked": 0, "sent": 0, "skipped": 0, "failed": 0}
    assert sent == [] and conn.marked == []


async def test_only_first_message_carries_header_content():
    conn = FakeConn([_row(i) for i in range(1, 13)])
    contents = []

    async def sender(content, embeds):
        contents.append(content)

    await _tick(conn, sender=sender)
    assert "새 채용 공고 12건" in contents[0]
    assert contents[1:] == [None] * 11


async def test_header_goes_to_the_first_successful_message():
    """첫 건이 실패해도 헤더가 사라지면 안 된다. 실패한 시도는 메시지를 만들지
    않으므로, 실제로 전달된 것만 세야 한다(시도 횟수와 전달 횟수는 다르다)."""
    conn = FakeConn([_row(i) for i in range(1, 4)])
    delivered = []

    async def flaky(content, embeds):
        if embeds[0]["title"].endswith("t1"):
            raise RuntimeError("discord 500")   # 실패 — 메시지가 생기지 않는다
        delivered.append(content)

    await _tick(conn, sender=flaky)
    assert len(delivered) == 2
    assert "새 채용 공고" in delivered[0]        # 첫 성공 메시지가 헤더를 받는다
    assert delivered[1] is None                  # 이후에는 붙지 않는다
