import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from app.research.discord import push

log = logging.getLogger("run_log")

_KO = {"collector": "수집", "worker": "요약 처리", "research": "리서치"}

_INSERT = (
    "INSERT INTO run_log "
    "(pipeline, ref, label, trigger, status, result, error, started_at, finished_at, duration_ms) "
    "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, $10)"
)
_PRUNE = "DELETE FROM run_log WHERE finished_at < now() - interval '30 days'"


def classify(pipeline: str, result: Any) -> str:
    if pipeline == "research":
        return {"done": "ok", "cached": "skipped", "failed": "failed"}.get(result, "ok")
    if pipeline == "worker" and isinstance(result, dict) and result.get("skipped_tick"):
        return "skipped"
    return "ok"


async def record(conn, *, pipeline: str, ref: str, label: str, trigger: str,
                 status: str, result: Any, error: str, started: datetime) -> None:
    finished = datetime.now(timezone.utc)
    duration_ms = int((finished - started).total_seconds() * 1000)
    payload = result if isinstance(result, dict) else {"result": result}
    await conn.execute(_INSERT, pipeline, ref, label, trigger, status,
                       json.dumps(payload), error, started, finished, duration_ms)
    await conn.execute(_PRUNE)


async def logged_run(conn, *, pipeline: str, trigger: str, ref: str = "", label: str = "",
                     clear: Callable[[], None] = lambda: None,
                     run: Callable[[], Any]) -> Any:
    started = datetime.now(timezone.utc)
    try:
        result = await run()
        await record(conn, pipeline=pipeline, ref=ref, label=label, trigger=trigger,
                     status=classify(pipeline, result), result=result, error="", started=started)
        return result
    except Exception as e:  # noqa: BLE001 — 실패도 기록 후 재-raise
        await record(conn, pipeline=pipeline, ref=ref, label=label, trigger=trigger,
                     status="failed", result={}, error=str(e), started=started)
        if trigger == "scheduled":
            first = str(e).splitlines()[0][:200] if str(e) else ""
            await push(f"⚠️ 스케줄 {_KO.get(pipeline, pipeline)} 실패 · {first}")
        raise
    finally:
        clear()
