import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from app.research.discord import push

log = logging.getLogger("run_log")

_KO = {"collector": "수집", "worker": "요약 처리", "research": "리서치", "notifier": "알림 발송"}

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


async def _finish(conn, *, pipeline, trigger, ref, label, status, result, error, started):
    await record(conn, pipeline=pipeline, ref=ref, label=label, trigger=trigger,
                 status=status, result=result, error=error, started=started)
    if status == "failed" and trigger == "scheduled":
        first = error.splitlines()[0][:200] if error else ""
        await push(f"⚠️ 스케줄 {_KO.get(pipeline, pipeline)} 실패 · {first}")


async def logged_run(conn, *, pipeline: str, trigger: str, ref: str = "", label: str = "",
                     clear: Callable[[], None] = lambda: None,
                     run: Callable[[], Any]) -> Any:
    started = datetime.now(timezone.utc)
    try:
        try:
            result = await run()
        except Exception as e:  # noqa: BLE001 — 실패도 기록 후 재-raise
            await _finish(conn, pipeline=pipeline, trigger=trigger, ref=ref, label=label,
                          status="failed", result={}, error=str(e), started=started)
            raise
        # 성공 기록은 run의 except 밖 — 기록/prune 오류가 '실행 실패'로 오분류되지 않도록.
        await _finish(conn, pipeline=pipeline, trigger=trigger, ref=ref, label=label,
                      status=classify(pipeline, result), result=result, error="", started=started)
        return result
    finally:
        clear()


async def logged_pool_run(pool, *, pipeline: str, trigger: str, ref: str = "", label: str = "",
                          clear: Callable[[], None] = lambda: None,
                          run: Callable[[], Any]) -> Any:
    """research용: run() 동안 풀 커넥션을 잡지 않고 기록 시점에만 acquire.

    러너가 풀을 직접 써 자체 커넥션을 취득하므로, 여기서 커넥션을 run 내내 붙들면
    풀 고갈/교착이 발생한다(멀티분 Claude 호출). 기록 한 줄을 위해서만 짧게 acquire.
    """
    started = datetime.now(timezone.utc)
    try:
        try:
            result = await run()
        except Exception as e:  # noqa: BLE001
            async with pool.acquire() as conn:
                await _finish(conn, pipeline=pipeline, trigger=trigger, ref=ref, label=label,
                              status="failed", result={}, error=str(e), started=started)
            raise
        async with pool.acquire() as conn:
            await _finish(conn, pipeline=pipeline, trigger=trigger, ref=ref, label=label,
                          status=classify(pipeline, result), result=result, error="", started=started)
        return result
    finally:
        clear()


_SELECT = (
    "SELECT id, pipeline, ref, label, trigger, status, result, error, "
    "started_at, finished_at, duration_ms FROM run_log"
)


def build_runs_query(*, pipeline: str | None = None, status: str | None = None,
                     limit: int = 30) -> tuple[str, list]:
    where: list[str] = []
    params: list = []
    if pipeline:
        params.append(pipeline)
        where.append(f"pipeline = ${len(params)}")
    if status:
        params.append(status)
        where.append(f"status = ${len(params)}")
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)
    sql = f"{_SELECT}{clause} ORDER BY finished_at DESC LIMIT ${len(params)}"
    return sql, params


def _row_to_item(row) -> dict:
    d = dict(row)
    res = d.get("result")
    if isinstance(res, str):
        d["result"] = json.loads(res)
    for k in ("started_at", "finished_at"):
        v = d.get(k)
        if v is not None:
            d[k] = v.isoformat()
    return d


async def list_runs(conn, *, pipeline: str | None = None, status: str | None = None,
                    limit: int = 30) -> dict:
    sql, params = build_runs_query(pipeline=pipeline, status=status, limit=limit)
    rows = await conn.fetch(sql, *params)
    return {"items": [_row_to_item(r) for r in rows]}
