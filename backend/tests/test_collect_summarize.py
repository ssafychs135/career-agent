import pytest
from app.collect.summarize import summarize, extract_stacks, SUMMARY_SYSTEM_PROMPT
from app.settings_repo import Settings, SETTINGS_DEFAULTS
from app.collect.config import SUMMARY_TIMEOUT


class NoHttp:
    async def get(self, *args, **kwargs):
        raise AssertionError("summary must not make HTTP requests")

    async def post(self, *args, **kwargs):
        raise AssertionError("summary must not make HTTP requests")


def test_extract_stacks():
    assert extract_stacks("요약...\n기술스택: Python, Django·FastAPI") == ["Python", "Django", "FastAPI"]
    assert extract_stacks("스택 언급 없음") == []


def test_extract_stacks_tolerates_markdown_label():
    # claude는 라벨을 마크다운으로 감싸는 경우가 있다(비결정적, 실측 9건 중 1건).
    # 로컬 LLM은 평문만 냈기 때문에 claude 전환 후에야 드러난 형태다.
    assert extract_stacks("요약\n**기술스택**: Python, LLM") == ["Python", "LLM"]
    assert extract_stacks("요약\n**기술스택:** Python, LLM") == ["Python", "LLM"]
    assert extract_stacks("요약\n- **기술스택**: Python") == ["Python"]
    assert extract_stacks("요약\n### 기술스택: Go") == ["Go"]


@pytest.mark.parametrize("backend", ["local", "claude"])
async def test_summarize_legacy_and_current_settings_use_claude_only(backend):
    calls = []
    async def runner(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return "3줄 요약"
    s = Settings(**dict(SETTINGS_DEFAULTS, summary_backend=backend))
    step = object()
    out = await summarize("공고 프롬프트", s, http=NoHttp(), model="opus",
                          runner=runner, on_step=step)
    assert out == "3줄 요약"
    assert calls[0][0] == f"{SUMMARY_SYSTEM_PROMPT}\n\n공고 프롬프트"
    assert calls[0][1] == {"model": "opus", "timeout": SUMMARY_TIMEOUT, "on_step": step}


async def test_summarize_claude_uses_runner():
    calls = {}
    async def fake_runner(prompt, *, on_step=None, **kw): calls["prompt"] = prompt; return "클로드 요약"
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], summary_backend="claude"))
    out = await summarize("공고 프롬프트", s, http=NoHttp(), runner=fake_runner)
    assert out == "클로드 요약"
    assert "공고 프롬프트" in calls["prompt"]


async def test_summarize_claude_forwards_model():
    calls = {}

    async def fake_runner(prompt, *, model="", on_step=None, **kw):
        calls["model"] = model
        return "클로드 요약"

    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], summary_backend="claude"))
    await summarize("공고", s, http=NoHttp(), model="haiku", runner=fake_runner)
    assert calls["model"] == "haiku"


async def test_summarize_empty_claude_response_is_retryable():
    async def runner(*args, **kwargs):
        return ""
    assert await summarize("공고", Settings(**SETTINGS_DEFAULTS), http=NoHttp(), runner=runner) is None
