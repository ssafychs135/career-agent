from typing import Any

from fastapi import APIRouter, Depends, Request

from app.collect.health import llm_healthy
from app.db import get_conn
from app.settings_repo import get_settings

router = APIRouter(prefix="/api", tags=["status"])


@router.get("/status")
async def read_status(request: Request, conn: Any = Depends(get_conn)):
    settings = await get_settings(conn)
    rows = await conn.fetch("SELECT status, count(*) AS n FROM jobs GROUP BY status")
    counts = {r["status"]: r["n"] for r in rows}
    research_running = await conn.fetchval(
        "SELECT count(*) FROM job_research WHERE status='running'"
    ) or 0
    healthy = await llm_healthy(request.app.state.http)
    return {
        "activity": request.app.state.activity.snapshot(),
        "counts": {
            "pending": counts.get("pending", 0),
            "done": counts.get("done", 0),
            "failed": counts.get("failed", 0),
            "skipped": counts.get("skipped", 0),
            "research_running": research_running,
        },
        "llm_health": "ok" if healthy else "down",
        "enabled": settings.enabled,
        "next_ticks": {"collect_hour": settings.collect_hour,
                       "worker_interval_min": settings.worker_interval_min},
    }
