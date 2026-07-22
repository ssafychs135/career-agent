from typing import Any

from fastapi import APIRouter, Depends, Request

from app.db import get_conn
from app.settings_repo import Settings, get_settings, put_settings

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings", response_model=Settings)
async def read_settings(conn: Any = Depends(get_conn)):
    return await get_settings(conn)


@router.put("/settings", response_model=Settings)
async def write_settings(body: Settings, request: Request, conn: Any = Depends(get_conn)):
    saved = await put_settings(conn, body)
    reschedule = getattr(request.app.state, "reschedule_pipelines", None)
    if reschedule is not None:
        reschedule(saved)  # collect_hour/worker_interval 변경 즉시 반영 (Task 8)
    return saved
