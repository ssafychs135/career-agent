"""Self-contained offline fixtures: no Node, SDK, repository root or login."""
import asyncio
import json
import os
import signal
import sys
import traceback
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app import sdk_bridge as sdk
from app.claude_client import ClaudeAuthError

REQ = {"v": 1, "id": "test_1", "task": "summary", "model": "haiku", "prompt": "fixture"}
RESULT = {"v": 1, "id": "test_1", "type": "result", "text": "fixture result"}


async def run(tmp_path, source, *, req=None, timeout=2, on_step=None):
    script = tmp_path / "fixture.py"
    script.write_text(source)
    return await sdk._exchange([sys.executable, str(script)], req or REQ, home=str(tmp_path), timeout=timeout, on_step=on_step)


def output(*events):
    return "import sys\nsys.stdin.read()\n" + "\n".join(f"print({json.dumps(json.dumps(e))})" for e in events)


@pytest.mark.asyncio
async def test_disabled_without_node_or_spawn(monkeypatch):
    monkeypatch.setenv("CAREER_AGENT_SDK_ENABLED", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-not-secret")
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as spawn:
        with pytest.raises(ClaudeAuthError, match="disabled"):
            await sdk.run_sdk("never sent", model="haiku")
        spawn.assert_not_called()
    assert sdk.LIVE_ENABLED is False


def test_environment_allowlist():
    env = {key: "fixture" for key in ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY", "AWS_PROFILE", "GOOGLE_APPLICATION_CREDENTIALS", "NODE_OPTIONS", "LD_PRELOAD", "HTTPS_PROXY", "CLAUDE_CONFIG_DIR", "PATH"]}
    env["HOME"] = "/fixture/home"
    assert sdk.safe_environment(env) == {"HOME": "/fixture/home", "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    for home in ("", "relative", "/bad\0home"):
        with pytest.raises(sdk.SDKInterrupted):
            sdk.safe_environment({"HOME": home})


@pytest.mark.asyncio
async def test_result_and_progress(tmp_path):
    labels = []
    step = {"v": 1, "id": "test_1", "type": "step", "label": "working"}
    assert await run(tmp_path, output(step, RESULT), on_step=labels.append) == "fixture result"
    assert labels == ["분석·작성 중"]


@pytest.mark.parametrize("code", sorted(sdk.CODES))
@pytest.mark.asyncio
async def test_interruptions_do_not_become_results(tmp_path, code):
    with pytest.raises(sdk.SDKInterrupted) as error:
        await run(tmp_path, output({"v": 1, "id": "test_1", "type": "interrupted", "code": code}))
    assert error.value.code == code
    assert isinstance(error.value, ClaudeAuthError)


@pytest.mark.parametrize("raw", [
    "not json\n", "{}\n", "[]\n", "\n", '{"v":1,"v":1,"id":"test_1","type":"result","text":"x"}\n',
    json.dumps({**RESULT, "v": True}) + "\n", json.dumps({**RESULT, "v": 2}) + "\n",
    json.dumps({**RESULT, "id": "wrong"}) + "\n", json.dumps({**RESULT, "text": None}) + "\n",
    json.dumps({**RESULT, "tools": ["Bash"]}) + "\n",
    json.dumps(RESULT) + "\n" + json.dumps(RESULT) + "\n",
    json.dumps(RESULT), json.dumps({**RESULT, "text": "x" * (sdk.MAX_TEXT + 1)}) + "\n",
    "x" * sdk.MAX_LINE, json.dumps({"v": 1, "id": "test_1", "type": "step", "label": "web_search"}) + "\n" + json.dumps(RESULT) + "\n",
], ids=lambda v: str(len(v)) + "-bytes")
@pytest.mark.asyncio
async def test_strict_hostile_protocol(tmp_path, raw):
    source = f"import sys\nsys.stdin.read()\nsys.stdout.write({raw!r})\n"
    with pytest.raises(sdk.SDKInterrupted, match="protocol_error"):
        await run(tmp_path, source)


@pytest.mark.asyncio
async def test_stderr_concurrent_and_capped(tmp_path):
    source = "import sys\nsys.stdin.read()\nsys.stderr.write('fixture' * 1000)\n" + f"print({json.dumps(json.dumps(RESULT))})\n"
    assert await run(tmp_path, source) == "fixture result"
    with pytest.raises(sdk.SDKInterrupted, match="protocol_error"):
        await run(tmp_path, "import sys\nwhile True: sys.stderr.write('x'*4096); sys.stderr.flush()\n")


@pytest.mark.asyncio
async def test_aggregate_bounded(tmp_path):
    step = {"v": 1, "id": "test_1", "type": "step", "label": "working"}
    with pytest.raises(sdk.SDKInterrupted, match="protocol_error"):
        await run(tmp_path, f"import sys\nfor i in range(10000): print({json.dumps(json.dumps(step))})\n")


@pytest.mark.asyncio
async def test_nonzero_even_after_result(tmp_path):
    with pytest.raises(sdk.SDKInterrupted, match="internal"):
        await run(tmp_path, output(RESULT) + "\nraise SystemExit(1)")


@pytest.mark.asyncio
async def test_invalid_utf8(tmp_path):
    with pytest.raises(sdk.SDKInterrupted, match="protocol_error"):
        await run(tmp_path, "import os\nos.write(1, b'\\xff\\n')")


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.asyncio
async def test_timeout_cancel_reaps_child_and_grandchild(tmp_path, cancel):
    marker = tmp_path / "pids"
    # Parent catches TERM, kills and wait()s its own child. Bridge must signal
    # the group, then reap its direct child even when cancellation interrupts it.
    source = f'''import subprocess,sys,os,signal,time
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
def end(*_):
    child.terminate()
    child.wait()
    sys.exit(0)
signal.signal(signal.SIGTERM, end)
open({str(marker)!r}, 'w').write(str(os.getpid())+' '+str(child.pid))
while True: time.sleep(1)
'''
    task = asyncio.create_task(run(tmp_path, source, timeout=0.5 if not cancel else 10))
    for _ in range(100):
        if marker.exists():
            break
        await asyncio.sleep(0.01)
    assert marker.exists()
    pids = [int(v) for v in marker.read_text().split()]
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(sdk.SDKInterrupted):
            await task
    for pid in pids:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


@pytest.mark.asyncio
async def test_callback_failure_cleans_process(tmp_path):
    step = {"v": 1, "id": "test_1", "type": "step", "label": "working"}
    def fail(_):
        raise ValueError("SYNTHETIC_SENTINEL")
    with pytest.raises(sdk.SDKInterrupted) as error:
        await run(tmp_path, output(step, RESULT), on_step=fail)
    assert_safe_error(error.value, "internal")


@pytest.mark.parametrize("field,value", [("v", True), ("id", "bad id"), ("task", "Bash"), ("model", "api"), ("prompt", "x" * (sdk.MAX_TEXT + 1)), ("env", {})], ids=lambda v: str(v)[:30])
@pytest.mark.asyncio
async def test_bad_request_never_spawns(field, value):
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as spawn:
        with pytest.raises(sdk.SDKInterrupted):
            await sdk._exchange([sys.executable], {**REQ, field: value}, home="/fixture")
        spawn.assert_not_called()


def test_existing_consumers_keep_legacy_runner():
    import inspect
    from app.claude_client import run_claude
    from app.collect.summarize import summarize
    from app.research.runner import research_company, research_job
    for consumer in (summarize, research_company, research_job):
        assert inspect.signature(consumer).parameters["runner"].default is run_claude


@pytest.mark.asyncio
async def test_cancellation_during_spawn_reaps_child(tmp_path, monkeypatch):
    marker = tmp_path / 'spawnpid'
    original = asyncio.create_subprocess_exec
    async def delayed(*args, **kwargs):
        proc = await original(*args, **kwargs)
        marker.write_text(str(proc.pid))
        await asyncio.sleep(0.1)
        return proc
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', delayed)
    task = asyncio.create_task(run(tmp_path, 'import time; time.sleep(60)'))
    for _ in range(100):
        if marker.exists():
            break
        await asyncio.sleep(0.005)
    assert marker.exists()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)


@pytest.mark.asyncio
async def test_unpaired_surrogate_result_rejected(tmp_path):
    raw = '{"v":1,"id":"test_1","type":"result","text":"\\ud800"}\n'
    with pytest.raises(sdk.SDKInterrupted, match='protocol_error'):
        await run(tmp_path, f'import sys\nsys.stdout.write({raw!r})')


def assert_safe_error(error, code):
    assert type(error) is sdk.SDKInterrupted
    assert error.code == code
    assert error.__context__ is None
    assert error.__cause__ is None
    assert "SYNTHETIC_SENTINEL" not in "".join(traceback.format_exception(error))


@pytest.mark.asyncio
async def test_deep_json_is_protocol_interruption(tmp_path):
    raw = '{"v":1,"id":"test_1","type":"result","text":' + '[' * 10000 + '0' + ']' * 10000 + '}'
    assert len(raw.encode()) + 1 < sdk.MAX_LINE
    with pytest.raises(sdk.SDKInterrupted) as error:
        await run(tmp_path, "import sys;sys.stdin.read();print(" + repr(raw) + ")")
    assert_safe_error(error.value, "protocol_error")


@pytest.mark.asyncio
async def test_spawn_path_is_sanitized(tmp_path):
    executable = str(tmp_path / "SYNTHETIC_SENTINEL")
    with pytest.raises(sdk.SDKInterrupted) as error:
        await sdk._exchange([executable], REQ, home=str(tmp_path))
    assert_safe_error(error.value, "internal")


@pytest.mark.asyncio
async def test_transport_cleanup_exception_boundary():
    with patch.object(sdk, "_exchange_impl", new=AsyncMock(side_effect=OSError("SYNTHETIC_SENTINEL"))):
        with pytest.raises(sdk.SDKInterrupted) as error:
            await sdk._exchange([sys.executable], REQ, home="/tmp")
    assert_safe_error(error.value, "internal")


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.asyncio
async def test_real_cleanup_failure_and_cancellation(tmp_path, cancel):
    original = asyncio.create_subprocess_exec
    spawned = []
    async def spawn(*args, **kwargs):
        proc = await original(*args, **kwargs)
        spawned.append(proc)
        proc.stdin.wait_closed = AsyncMock(side_effect=OSError("SYNTHETIC_SENTINEL"))
        return proc
    with patch("asyncio.create_subprocess_exec", side_effect=spawn):
        task = asyncio.create_task(run(tmp_path, "import sys,time;sys.stdin.read();time.sleep(10)" if cancel else output(RESULT)))
        if cancel:
            for _ in range(100):
                if spawned:
                    break
                await asyncio.sleep(0.01)
            assert spawned
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(sdk.SDKInterrupted) as error:
                await task
            assert_safe_error(error.value, "internal")
    assert spawned[0].returncode is not None
    with pytest.raises(ProcessLookupError):
        os.kill(spawned[0].pid, 0)


@pytest.mark.asyncio
async def test_cancellation_during_failed_spawn():
    entered = asyncio.Event()
    async def fail(*args, **kwargs):
        entered.set()
        await asyncio.sleep(0.05)
        raise OSError("SYNTHETIC_SENTINEL")
    with patch("asyncio.create_subprocess_exec", side_effect=fail):
        task = asyncio.create_task(sdk._exchange([sys.executable], REQ, home="/tmp"))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
