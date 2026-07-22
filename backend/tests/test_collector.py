from app.collect.collector import dedupe, collect, INSERT_SQL
from app.settings_repo import Settings, SETTINGS_DEFAULTS


def test_dedupe_keeps_first():
    rows = [
        {"source": "wanted", "job_id": "1", "title": "a"},
        {"source": "wanted", "job_id": "1", "title": "dup"},
        {"source": "jumpit", "job_id": "1", "title": "b"},
    ]
    out = dedupe(rows)
    assert [r["job_id"] + r["source"] for r in out] == ["1wanted", "1jumpit"]


def test_insert_sql_is_on_conflict_do_nothing():
    assert "INSERT INTO jobs" in INSERT_SQL
    assert "ON CONFLICT (source, job_id) DO NOTHING" in INSERT_SQL


class FakeResp:
    def __init__(self, payload): self._p = payload
    def json(self): return self._p
    def raise_for_status(self): pass


class FakeHttp:
    """점핏 page1에 1건, 원티드 page1에 1건, 이후 빈 페이지."""
    def __init__(self):
        self.calls = []

    async def get(self, url, headers=None):
        self.calls.append(url)
        if "jumpit-api" in url and "page=1" in url:
            return FakeResp({"result": {"positions": [
                {"id": 1, "title": "백엔드 개발자", "companyName": "A", "minCareer": 1}]}})
        if "navigation/v1/results" in url and "offset=0" in url:
            return FakeResp({"data": [
                {"id": 10, "position": "백엔드 엔지니어", "company": {"name": "W"},
                 "annual_from": 1, "category_tag": {"parent_id": 518}}]})
        return FakeResp({"result": {"positions": []}, "data": []})  # 빈 페이지 → 종료


class FakeConn:
    def __init__(self): self.executed = []
    async def executemany(self, sql, args): self.executed.append((sql, args))


async def test_collect_scrapes_and_inserts():
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["백엔드"], max_pages=3))
    conn, http = FakeConn(), FakeHttp()
    result = await collect(conn, s, http=http)
    assert result == {"scraped": 2, "inserted": 2}
    assert conn.executed[0][0] == INSERT_SQL
    assert len(conn.executed[0][1]) == 2  # 2행 executemany


class FakeHttpMalformedJumpit:
    """점핏 page1이 파싱 불가능한 payload({"result": None}) → 파서 예외가 페이징을 끊어야 함."""
    async def get(self, url, headers=None):
        if "jumpit-api" in url:
            return FakeResp({"result": None})
        return FakeResp({"result": {"positions": []}, "data": []})  # 빈 페이지 → 종료


async def test_collect_survives_malformed_jumpit_payload():
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["백엔드"], max_pages=3))
    conn, http = FakeConn(), FakeHttpMalformedJumpit()
    result = await collect(conn, s, http=http)  # 예외 없이 정상 반환되어야 함
    assert result == {"scraped": 0, "inserted": 0}
    assert isinstance(result["scraped"], int) and isinstance(result["inserted"], int)
