from app.collect.worker import worker_tick, CLAIM_SQL
from app.settings_repo import Settings, SETTINGS_DEFAULTS


class Resp:
    def __init__(self, code=200, payload=None): self.status_code = code; self._p = payload
    def json(self): return self._p


class Http:
    def __init__(self, detail_payload): self._d = detail_payload
    async def get(self, url, headers=None, timeout=None):
        return Resp(200, self._d)


class Conn:
    """claim은 1건 반환, 이후 UPDATE 캡처."""
    def __init__(self, claimed): self._claimed = claimed; self.updates = []
    async def fetch(self, sql, *args): return self._claimed
    async def execute(self, sql, *args): self.updates.append((sql, args))


def _settings(**o):
    return Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], **o))


async def test_worker_skips_when_llm_down():
    conn = Conn([])
    async def down(http, base_url=None): return False
    r = await worker_tick(conn, _settings(), http=Http({}), health=down)
    assert r["skipped_tick"] is True
    assert conn.updates == []


async def test_worker_summarizes_and_marks_done():
    claimed = [{"id": 1, "source": "jumpit", "job_id": "5", "company": "A", "title": "T", "attempts": 0}]
    conn = Conn(claimed)
    http = Http({"result": {"responsibility": "일", "qualifications": "q", "preferredRequirements": "p"}})
    async def up(http, base_url=None): return True
    async def summ(prompt, settings, *, http, on_step=None): return "요약본\n기술스택: Go"
    r = await worker_tick(conn, _settings(), http=http, summarizer=summ, health=up)
    assert r["done"] == 1 and r["failed"] == 0
    done_sql = conn.updates[-1][0]
    assert "status='done'" in done_sql


async def test_worker_retry_cap_marks_failed_on_empty():
    claimed = [{"id": 1, "source": "jumpit", "job_id": "5", "company": "A", "title": "T", "attempts": 4}]
    conn = Conn(claimed)
    http = Http({"result": {"responsibility": "일", "qualifications": "q", "preferredRequirements": "p"}})
    async def up(http, base_url=None): return True
    async def summ(prompt, settings, *, http, on_step=None): return None  # 빈 응답
    r = await worker_tick(conn, _settings(max_attempts=5), http=http, summarizer=summ, health=up)
    assert r["failed"] == 1
    assert "failed" in conn.updates[-1][0]


async def test_worker_summarizer_error_routes_to_retry():
    claimed = [{"id": 1, "source": "jumpit", "job_id": "5", "company": "A", "title": "T", "attempts": 0}]
    conn = Conn(claimed)
    http = Http({"result": {"responsibility": "일", "qualifications": "q", "preferredRequirements": "p"}})
    async def up(http, base_url=None): return True
    async def boom(prompt, settings, *, http, on_step=None): raise RuntimeError("llm error mid-call")
    r = await worker_tick(conn, _settings(), http=http, summarizer=boom, health=up)
    assert r["failed"] == 1 and r["done"] == 0
    assert "attempts=attempts+1" in conn.updates[-1][0]  # 재시도 SQL 적용, 크래시 없음
