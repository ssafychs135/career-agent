import pytest

from app.claude_client import ClaudeAuthError
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


async def test_worker_empty_batch_does_not_probe_llm():
    class NoHttp:
        async def get(self, *args, **kwargs):
            raise AssertionError("no local health probe")
    r = await worker_tick(Conn([]), _settings(summary_backend="local"), http=NoHttp())
    assert r == {"claimed": 0, "done": 0, "failed": 0, "escalated": 0, "skipped_tick": False}


async def test_worker_summarizes_and_marks_done():
    claimed = [{"id": 1, "source": "jumpit", "job_id": "5", "company": "A", "title": "T", "attempts": 0}]
    conn = Conn(claimed)
    http = Http({"result": {"responsibility": "일", "qualifications": "q", "preferredRequirements": "p"}})
    async def summ(prompt, settings, *, http, model="", on_step=None): return "요약본\n기술스택: Go"
    r = await worker_tick(conn, _settings(), http=http, summarizer=summ)
    assert r["done"] == 1 and r["failed"] == 0
    done_sql = conn.updates[-1][0]
    assert "status='done'" in done_sql


async def test_worker_retry_cap_marks_failed_on_empty():
    claimed = [{"id": 1, "source": "jumpit", "job_id": "5", "company": "A", "title": "T", "attempts": 4}]
    conn = Conn(claimed)
    http = Http({"result": {"responsibility": "일", "qualifications": "q", "preferredRequirements": "p"}})
    async def summ(prompt, settings, *, http, model="", on_step=None): return None  # 빈 응답
    r = await worker_tick(conn, _settings(max_attempts=5), http=http, summarizer=summ)
    assert r["failed"] == 1
    assert "failed" in conn.updates[-1][0]


async def test_worker_summarizer_error_routes_to_retry():
    claimed = [{"id": 1, "source": "jumpit", "job_id": "5", "company": "A", "title": "T", "attempts": 0}]
    conn = Conn(claimed)
    http = Http({"result": {"responsibility": "일", "qualifications": "q", "preferredRequirements": "p"}})
    async def boom(prompt, settings, *, http, model="", on_step=None): raise RuntimeError("llm error mid-call")
    r = await worker_tick(conn, _settings(), http=http, summarizer=boom)
    assert r["failed"] == 1 and r["done"] == 0
    assert "attempts=attempts+1" in conn.updates[-1][0]  # 재시도 SQL 적용, 크래시 없음


_DETAIL = {"result": {"responsibility": "일", "qualifications": "q", "preferredRequirements": "p"}}


def _claimed(attempts: int):
    return [{"id": 1, "source": "jumpit", "job_id": "5", "company": "A",
             "title": "T", "attempts": attempts}]


async def test_worker_uses_base_tier_for_fresh_job():
    conn = Conn(_claimed(0))
    seen = {}

    async def summ(prompt, settings, *, http, model="", on_step=None):
        seen["model"] = model
        return "요약\n기술스택: Go"

    r = await worker_tick(conn, _settings(summary_backend="claude"),
                          http=Http(_DETAIL), summarizer=summ)
    assert seen["model"] == "haiku"
    assert r["escalated"] == 0


async def test_worker_escalates_previously_failed_job():
    conn = Conn(_claimed(1))
    seen = {}

    async def summ(prompt, settings, *, http, model="", on_step=None):
        seen["model"] = model
        return "요약\n기술스택: Go"

    r = await worker_tick(conn, _settings(summary_backend="claude"),
                          http=Http(_DETAIL), summarizer=summ)
    assert seen["model"] == "sonnet"
    assert r["escalated"] == 1


async def test_worker_setting_override_shifts_the_whole_ladder():
    conn = Conn(_claimed(1))
    seen = {}

    async def summ(prompt, settings, *, http, model="", on_step=None):
        seen["model"] = model
        return "요약"

    await worker_tick(conn, _settings(summary_backend="claude", summary_model="sonnet"),
                      http=Http(_DETAIL), summarizer=summ)
    assert seen["model"] == "opus"


@pytest.mark.parametrize("attempts, tier", [(0, "haiku"), (1, "sonnet")])
async def test_worker_legacy_local_uses_claude_tier_without_health_gate(attempts, tier):
    conn = Conn(_claimed(attempts))
    urls = []
    class DetailOnly(Http):
        async def get(self, url, **kwargs):
            assert "/v1/models" not in url
            urls.append(url)
            return await super().get(url, **kwargs)
    async def summ(prompt, settings, *, http, model="", **kwargs):
        assert settings.summary_backend == "claude"
        assert model == tier
        return "요약"
    r = await worker_tick(conn, _settings(summary_backend="local"),
                          http=DetailOnly(_DETAIL), summarizer=summ)
    assert len(urls) == 1
    assert r["done"] == 1
    assert r["escalated"] == int(attempts > 0)
    assert r["skipped_tick"] is False


async def test_worker_auth_error_releases_batch_without_spending_attempts():
    """인증 만료는 공고 탓이 아니다 — 재시도 횟수를 깎으면 장애가 길어질 때 전부 failed로
    묻힌다. 남은 배치를 그대로 pending으로 돌려놓고, 실행 자체를 실패로 올려 알린다."""
    claimed = [{"id": i, "source": "jumpit", "job_id": str(i), "company": "A",
                "title": "T", "attempts": 0} for i in (1, 2, 3)]
    conn = Conn(claimed)
    calls = []

    async def summ(prompt, settings, *, http, model="", on_step=None):
        calls.append(prompt)
        if len(calls) == 1:
            return "요약본\n기술스택: Go"
        raise ClaudeAuthError("Failed to authenticate: OAuth session expired")

    with pytest.raises(ClaudeAuthError):
        await worker_tick(conn, _settings(summary_backend="claude"), http=Http(_DETAIL),
                          summarizer=summ)

    assert len(calls) == 2  # 인증이 풀린 뒤로는 남은 공고에 claude를 부르지 않는다
    (done_sql, done_args), (release_sql, release_args) = conn.updates
    assert "status='done'" in done_sql and done_args[-1] == 1  # 성공분은 그대로 반영
    assert "status='pending'" in release_sql and "attempts" not in release_sql
    assert release_args == ([2, 3],)  # 실패한 공고와 아직 안 본 공고 모두 되돌림
