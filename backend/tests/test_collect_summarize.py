import pytest
from app.collect.health import llm_healthy
from app.collect.summarize import summarize, extract_stacks, SUMMARY_SYSTEM_PROMPT
from app.settings_repo import Settings, SETTINGS_DEFAULTS


class Resp:
    def __init__(self, code=200, payload=None): self.status_code = code; self._p = payload
    def json(self): return self._p


class Http:
    def __init__(self, get_resp=None, post_resp=None): self._g, self._p = get_resp, post_resp; self.posted = None
    async def get(self, url, timeout=None): return self._g
    async def post(self, url, json=None, timeout=None): self.posted = json; return self._p


async def test_llm_healthy_true_on_200():
    assert await llm_healthy(Http(get_resp=Resp(200)), "http://x") is True


async def test_llm_healthy_false_on_error():
    class Boom:
        async def get(self, url, timeout=None): raise RuntimeError("down")
    assert await llm_healthy(Boom(), "http://x") is False


def test_extract_stacks():
    assert extract_stacks("요약...\n기술스택: Python, Django·FastAPI") == ["Python", "Django", "FastAPI"]
    assert extract_stacks("스택 언급 없음") == []


async def test_summarize_local_calls_lmstudio():
    http = Http(post_resp=Resp(200, {"choices": [{"message": {"content": "3줄 요약"}}]}))
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], summary_backend="local"))
    out = await summarize("공고 프롬프트", s, http=http)
    assert out == "3줄 요약"
    assert http.posted["model"] == s.model
    assert http.posted["messages"][0]["content"] == SUMMARY_SYSTEM_PROMPT


async def test_summarize_claude_uses_runner():
    calls = {}
    async def fake_runner(prompt, *, on_step=None, **kw): calls["prompt"] = prompt; return "클로드 요약"
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], summary_backend="claude"))
    out = await summarize("공고 프롬프트", s, http=Http(), runner=fake_runner)
    assert out == "클로드 요약"
    assert "공고 프롬프트" in calls["prompt"]
