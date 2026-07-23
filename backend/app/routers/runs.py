from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from app.db import get_conn
from app.run_log import list_runs

router = APIRouter(prefix="/api", tags=["runs"])


@router.get("/runs")
async def get_runs(
    pipeline: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(30, ge=1, le=100),
    conn: Any = Depends(get_conn),
):
    return await list_runs(conn, pipeline=pipeline, status=status, limit=limit)
