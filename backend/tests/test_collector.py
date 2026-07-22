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


def test_parse_dt_converts_iso_string_to_datetime():
    from datetime import datetime
    from app.collect.collector import parse_dt, _row_params
    # asyncpg timestamptz는 str이 아니라 datetime을 요구 — 소스 API의 ISO 문자열을 변환해야 함.
    assert parse_dt("2026-08-05T23:59:59") == datetime(2026, 8, 5, 23, 59, 59)
    assert parse_dt("2026-08-01T14:59:59+09:00").tzinfo is not None
    assert parse_dt(None) is None
    assert parse_dt("") is None
    assert parse_dt("not-a-date") is None
    # _row_params의 closed_at($10)은 반드시 datetime 또는 None(str이면 asyncpg DataError)
    row = {"source": "jumpit", "job_id": "1", "company": "A", "title": "t", "url": "u",
           "min_career": 0, "max_career": 3, "tech_stacks": [], "locations": "서울",
           "closed_at": "2026-08-05T23:59:59"}
    assert isinstance(_row_params(row)[9], datetime)


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
