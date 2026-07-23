import asyncio
import json
import pytest
from app.claude_client import run_claude, stream_label


def _lines(*events: dict) -> bytes:
    return ("\n".join(json.dumps(e) for e in events) + "\n").encode()


class FakeStream:
    def __init__(self, data: bytes): self._data = data
    def __aiter__(self): self._it = iter(self._data.splitlines(keepends=True)); return self
    async def __anext__(self):
        try: return next(self._it)
        except StopIteration: raise StopAsyncIteration


class FakeErr:
    async def read(self): return b""


class FakeProc:
    def __init__(self, out=b"", rc=0):
        self.stdout = FakeStream(out); self.returncode = rc; self.stderr = FakeErr()
    async def wait(self): return self.returncode
    def kill(self): pass


def test_stream_label_websearch():
    ev = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "WebSearch", "input": {"query": "당근 매출"}}]}}
    assert stream_label(ev) == '웹 검색: "당근 매출"'


def test_stream_label_webfetch():
    ev = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "WebFetch", "input": {"url": "https://dart.fss.or.kr/x"}}]}}
    assert stream_label(ev) == "페이지 확인: dart.fss.or.kr"


def test_stream_label_text():
    ev = {"type": "assistant", "message": {"content": [{"type": "text", "text": "분석"}]}}
    assert stream_label(ev) == "분석·작성 중"


def test_stream_label_ignores_result():
    assert stream_label({"type": "result", "result": "x"}) is None


async def test_run_claude_returns_final_result(monkeypatch):
    out = _lines(
        {"type": "system", "subtype": "init"},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "WebSearch", "input": {"query": "q"}}]}},
        {"type": "result", "subtype": "success", "result": "최종본"},
    )
    async def fake_exec(*args, **kwargs):
        assert "stream-json" in args and "--verbose" in args
        return FakeProc(out)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    steps = []
    r = await run_claude("hi", on_step=steps.append)
    assert r == "최종본"
    assert steps == ['웹 검색: "q"']


async def test_run_claude_ignores_broken_lines(monkeypatch):
    out = b'not json\n' + _lines({"type": "result", "result": "ok"})
    async def fake_exec(*a, **k): return FakeProc(out)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    assert await run_claude("hi") == "ok"


async def test_run_claude_raises_when_no_result(monkeypatch):
    async def fake_exec(*a, **k): return FakeProc(_lines({"type": "system"}), rc=1)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(RuntimeError):
        await run_claude("hi")


async def test_run_claude_omits_model_flag_when_unset(monkeypatch):
    """model=""이면 명령줄이 현재와 동일해야 한다 — 기존 호출자 무손상."""
    seen = {}

    async def fake_exec(*args, **kwargs):
        seen["args"] = list(args)
        return FakeProc(_lines({"type": "result", "result": "ok"}))

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    assert await run_claude("hi") == "ok"
    assert "--model" not in seen["args"]


async def test_run_claude_passes_model_flag(monkeypatch):
    seen = {}

    async def fake_exec(*args, **kwargs):
        seen["args"] = list(args)
        return FakeProc(_lines({"type": "result", "result": "ok"}))

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    assert await run_claude("hi", model="haiku") == "ok"
    args = seen["args"]
    assert args[args.index("--model") + 1] == "haiku"


async def test_run_claude_keeps_allowed_tools_alongside_model(monkeypatch):
    seen = {}

    async def fake_exec(*args, **kwargs):
        seen["args"] = list(args)
        return FakeProc(_lines({"type": "result", "result": "ok"}))

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    await run_claude("hi", model="opus", allowed_tools="WebSearch")
    args = seen["args"]
    assert args[args.index("--model") + 1] == "opus"
    assert args[args.index("--allowedTools") + 1] == "WebSearch"
