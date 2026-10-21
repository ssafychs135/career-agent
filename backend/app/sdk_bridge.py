"""Stage-1 offline SDK protocol, deliberately not wired to run_claude.

No Node/root dependency on import or on the disabled entry. Only _exchange is
exercised by local fixture processes. A later reviewed PR must implement live
source attestation, packaging and caller parity before connecting this bridge.
"""
import asyncio
import json
import inspect
import os
import re
import signal
from collections.abc import Mapping, Sequence

from app.claude_client import ClaudeAuthError

LIVE_ENABLED = False  # Source gate; never read a feature flag from the environment.
MAX_LINE = 65_536
MAX_TOTAL = 262_144
MAX_TEXT = 32_768
MAX_STDERR = 16_384
CODES = {"disabled", "auth_unknown", "auth_required", "subscription_limit", "protocol_error", "internal"}
LABELS = {"working": "분석·작성 중", "web_search": "웹 검색 중", "web_fetch": "페이지 확인 중"}


class SDKInterrupted(ClaudeAuthError):
    """Non-content interruption: must not consume attempts or escalate tier."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(f"SDK interrupted: {code}")


def safe_environment(source: Mapping[str, str]) -> dict[str, str]:
    home = source.get("HOME", "")
    if not home.startswith("/") or "\0" in home:
        raise SDKInterrupted("auth_unknown")
    return {"HOME": home, "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}


async def run_sdk(prompt: str, *, model: str = "", allowed_tools: str = "", timeout: int = 120, on_step=None) -> str:
    # No subprocess, SDK import, root path lookup, credential read or fallback.
    # Keep this unconditional: changing LIVE_ENABLED alone is not activation.
    raise SDKInterrupted("disabled")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SDKInterrupted("protocol_error")
        result[key] = value
    return result


def _decode(raw: bytes) -> dict:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (UnicodeError, ValueError, RecursionError):
        raise SDKInterrupted("protocol_error") from None
    if not isinstance(value, dict):
        raise SDKInterrupted("protocol_error")
    return value


def _utf8_size(value: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeError:
        raise SDKInterrupted("protocol_error") from None


def _request(value: dict) -> bytes:
    if (set(value) != {"v", "id", "task", "model", "prompt"}
            or type(value["v"]) is not int or value["v"] != 1
            or not isinstance(value["id"], str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", value["id"])
            or value["task"] not in ("summary", "research")
            or value["model"] not in ("haiku", "sonnet", "opus")
            or not isinstance(value["prompt"], str)
            or _utf8_size(value["prompt"]) > MAX_TEXT):
        raise SDKInterrupted("protocol_error")
    raw = (json.dumps(value, ensure_ascii=False) + "\n").encode()
    if len(raw) > MAX_LINE:
        raise SDKInterrupted("protocol_error")
    return raw


async def _exchange(argv: Sequence[str], request: dict, *, home: str, timeout: float = 120, on_step=None) -> str:
    """Sanitize all phases, including spawn, callbacks and cleanup."""
    code = "internal"
    cancelled = False
    try:
        return await _exchange_impl(argv, request, home=home, timeout=timeout, on_step=on_step)
    except asyncio.CancelledError:
        cancelled = True
    except SDKInterrupted as error:
        if isinstance(error.code, str) and error.code in CODES:
            code = error.code
    except Exception:
        pass
    # Outside the handler: no original exception context or traceback leakage.
    if cancelled:
        raise asyncio.CancelledError from None
    raise SDKInterrupted(code) from None


async def _exchange_impl(argv: Sequence[str], request: dict, *, home: str, timeout: float = 120, on_step=None) -> str:
    """Internal fixture transport. argv is trusted host configuration, NOT wire data.

    Never used by production callers. Tests use only sys.executable and test-owned
    scripts, so backend-only CI needs neither Node nor the repository root.
    """
    payload = _request(request)
    if not argv or not os.path.isabs(argv[0]) or timeout <= 0:
        raise SDKInterrupted("protocol_error")
    spawning = asyncio.create_task(asyncio.create_subprocess_exec(
        *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, env=safe_environment({"HOME": home}), start_new_session=True,
    ))
    spawn_cancelled = False
    try:
        proc = await asyncio.shield(spawning)
    except asyncio.CancelledError:
        try:
            proc = await spawning
        except Exception:
            raise asyncio.CancelledError from None
        spawn_cancelled = True
    terminal = None
    result = None

    async def send():
        proc.stdin.write(payload)
        try:
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            proc.stdin.close()

    async def stdout():
        nonlocal terminal, result
        total = 0
        pending = b""
        while chunk := await proc.stdout.read(4096):
            total += len(chunk)
            if total > MAX_TOTAL:
                raise SDKInterrupted("protocol_error")
            pending += chunk
            while b"\n" in pending:
                raw, pending = pending.split(b"\n", 1)
                if len(raw) + 1 > MAX_LINE or terminal is not None:
                    raise SDKInterrupted("protocol_error")
                event = _decode(raw)
                if type(event.get("v")) is not int or event["v"] != 1 or event.get("id") != request["id"]:
                    raise SDKInterrupted("protocol_error")
                kind = event.get("type")
                if kind == "step" and set(event) == {"v", "id", "type", "label"}:
                    label = event["label"]
                    if not isinstance(label, str) or label not in LABELS or (request["task"] == "summary" and label != "working"):
                        raise SDKInterrupted("protocol_error")
                    if on_step:
                        step_result = on_step(LABELS[label])
                        if inspect.isawaitable(step_result):
                            await step_result
                elif kind == "result" and set(event) == {"v", "id", "type", "text"}:
                    result = event["text"]
                    if not isinstance(result, str) or _utf8_size(result) > MAX_TEXT:
                        raise SDKInterrupted("protocol_error")
                    terminal = "result"
                elif kind == "interrupted" and set(event) == {"v", "id", "type", "code"}:
                    if not isinstance(event["code"], str) or event["code"] not in CODES:
                        raise SDKInterrupted("protocol_error")
                    terminal = event["code"]
                else:
                    raise SDKInterrupted("protocol_error")
            if len(pending) >= MAX_LINE:
                raise SDKInterrupted("protocol_error")
        if pending or terminal is None:
            raise SDKInterrupted("protocol_error")

    async def stderr():
        total = 0
        while chunk := await proc.stderr.read(4096):
            total += len(chunk)
            # Never include stderr (possibly credentials) in exceptions or logs.
            if total > MAX_STDERR:
                raise SDKInterrupted("protocol_error")

    tasks = [] if spawn_cancelled else [asyncio.create_task(fn()) for fn in (send, stdout, stderr, proc.wait)]

    async def cleanup():
        # Kill the group even when the direct child exited: descendants can still
        # hold pipes open. Always reap the direct child; descendants are signalled.
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(proc.pid, sig)
            except ProcessLookupError:
                pass
            if sig == signal.SIGTERM:
                await asyncio.sleep(0.05)
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        async def discard(reader):
            while await reader.read(4096):
                pass
        # Finish pipe EOF delivery before the test/request event loop closes.
        try:
            await asyncio.wait_for(asyncio.gather(discard(proc.stdout), discard(proc.stderr), proc.wait()), 1)
        except asyncio.TimeoutError:
            # asyncio Process exposes no public close(). A group-escaped fixture
            # can retain pipe FDs; bound local transport cleanup, do not claim it
            # has been contained. Activation requires OS-level containment.
            proc._transport.close()
            raise SDKInterrupted("internal") from None
        try:
            await proc.stdin.wait_closed()
        except (BrokenPipeError, ConnectionResetError):
            pass

    cancelled = False
    try:
        if spawn_cancelled:
            raise asyncio.CancelledError
        await asyncio.wait_for(asyncio.gather(*tasks), timeout)
        if proc.returncode != 0:
            raise SDKInterrupted("internal")
        if terminal != "result":
            raise SDKInterrupted(terminal)
        return result
    except asyncio.CancelledError:
        cancelled = True
        raise
    except asyncio.TimeoutError:
        raise SDKInterrupted("internal") from None
    finally:
        # Shield cleanup so cancellation cannot strand the process group.
        cleanup_task = asyncio.create_task(cleanup())
        try:
            await asyncio.shield(cleanup_task)
        except asyncio.CancelledError:
            try:
                await cleanup_task
            except Exception:
                pass
            raise
        except Exception:
            if cancelled:
                raise asyncio.CancelledError from None
            raise
