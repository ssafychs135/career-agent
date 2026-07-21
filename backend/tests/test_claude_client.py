import asyncio
import json
import pytest
from app.claude_client import run_claude


class FakeProc:
    def __init__(self, out=b"", err=b"", rc=0):
        self._out, self._err, self.returncode = out, err, rc

    async def communicate(self):
        return self._out, self._err

    def kill(self):
        pass


async def test_run_claude_returns_result(monkeypatch):
    async def fake_exec(*args, **kwargs):
        assert args[0] == "claude" and "-p" in args
        return FakeProc(json.dumps({"result": "OK"}).encode())

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    assert await run_claude("hi") == "OK"


async def test_run_claude_passes_allowed_tools(monkeypatch):
    seen = {}

    async def fake_exec(*args, **kwargs):
        seen["args"] = args
        return FakeProc(json.dumps({"result": "x"}).encode())

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    await run_claude("hi", allowed_tools="WebSearch,WebFetch")
    assert "--allowedTools" in seen["args"]
    assert "WebSearch,WebFetch" in seen["args"]


async def test_run_claude_raises_on_nonzero(monkeypatch):
    async def fake_exec(*args, **kwargs):
        return FakeProc(b"", b"boom", rc=1)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(RuntimeError):
        await run_claude("hi")
