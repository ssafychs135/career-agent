from app.collect.verify import VERIFY_LOCK_KEY, verify_tick


class Resp:
    def __init__(self, code=200, payload=None):
        self.status_code = code
        self._p = payload if payload is not None else {}
    def json(self): return self._p


class Http:
    """URL에 따라 정해진 응답을 돌려주는 대역. 호출 URL을 기록한다."""
    def __init__(self, by_id=None, boom=False):
        self.by_id = by_id or {}
        self.boom = boom
        self.calls = []
    async def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        if self.boom:
            raise RuntimeError("네트워크 끊김")
        for jid, resp in self.by_id.items():
            if jid in url:
                return resp
        return Resp(200, {})


class Conn:
    def __init__(self, rows, lock=True):
        self.rows = rows
        self.lock = lock
        self.executed = []
        self.expired = 0
    async def fetchval(self, sql, *args):
        if "pg_try_advisory_lock" in sql:
            return self.lock
        return None
    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return "UPDATE 0"
    async def fetch(self, sql, *args):
        return self.rows


def _row(source, job_id):
    return {"id": 1, "source": source, "job_id": job_id}


async def test_returns_zero_when_lock_not_acquired():
    conn = Conn([], lock=False)
    r = await verify_tick(conn, http=Http())
    assert r == {"checked": 0, "closed": 0, "deleted": 0, "failed": 0}
    assert conn.executed == []   # 아무것도 건드리지 않음


async def test_expires_jumpit_by_sql_before_api():
    """점핏 만료는 closed_at이 이미 DB에 있으므로 API 없이 처리한다."""
    conn = Conn([])
    http = Http()
    await verify_tick(conn, http=http)
    sqls = " ".join(s for s, _a in conn.executed)
    assert "posting_state='closed'" in sqls.replace(" ", "").replace("=", "=")
    assert "closed_at" in sqls
    assert http.calls == []      # 만료 처리에 API를 쓰지 않음


async def test_marks_wanted_closed_and_deleted():
    conn = Conn([_row("wanted", "111"), _row("wanted", "222")])
    http = Http({
        "111": Resp(200, {"data": {"job": {"status": "close", "hidden": True}}}),
        "222": Resp(404, {"error_code": 11001}),
    })
    r = await verify_tick(conn, http=http)
    assert r["checked"] == 2 and r["closed"] == 1 and r["deleted"] == 1
    assert r["failed"] == 0


async def test_open_posting_is_not_marked_dead():
    conn = Conn([_row("wanted", "111")])
    http = Http({"111": Resp(200, {"data": {"job": {"status": "active", "hidden": False}}})})
    r = await verify_tick(conn, http=http)
    assert r["closed"] == 0 and r["deleted"] == 0 and r["failed"] == 0
    marks = [a for s, a in conn.executed if "posting_state" in s and "closed_at" not in s]
    assert marks and marks[-1][0] == "open"   # 상태는 open으로 갱신(확인 시각 기록)


async def test_network_failure_counts_as_failed_and_keeps_open():
    """프록시가 죽어도 공고를 숨기면 안 된다."""
    conn = Conn([_row("wanted", "111")])
    r = await verify_tick(conn, http=Http(boom=True))
    assert r["failed"] == 1 and r["closed"] == 0 and r["deleted"] == 0


async def test_jumpit_uses_direct_url_not_proxy():
    conn = Conn([_row("jumpit", "555")])
    http = Http({"555": Resp(200, {"result": {"closedAt": "2030-01-01 00:00:00"}})})
    await verify_tick(conn, http=http)
    assert any("jumpit-api" in u for u in http.calls)
