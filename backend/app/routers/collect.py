from typing import Any

from fastapi import APIRouter, Depends, Request

from app.collect.collector import collect
from app.collect.worker import worker_tick
from app.db import get_conn
from app.settings_repo import get_settings

router = APIRouter(prefix="/api/collect", tags=["collect"])


@router.post("/run", status_code=202)
async def run_collect(request: Request, conn: Any = Depends(get_conn)):
    settings = await get_settings(conn)
    return await collect(conn, settings, http=request.app.state.http)


@router.post("/worker/run", status_code=202)
async def run_worker(request: Request, conn: Any = Depends(get_conn)):
    settings = await get_settings(conn)
    return await worker_tick(conn, settings, http=request.app.state.http)
