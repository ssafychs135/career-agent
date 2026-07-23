from typing import Any

from fastapi import APIRouter, Depends, Request

from app.collect.collector import collect
from app.collect.worker import worker_tick
from app.db import get_conn
from app.run_log import logged_run
from app.settings_repo import get_settings

router = APIRouter(prefix="/api/collect", tags=["collect"])


@router.post("/run", status_code=202)
async def run_collect(request: Request, conn: Any = Depends(get_conn)):
    settings = await get_settings(conn)
    activity = request.app.state.activity
    # 수동 실행도 진행상황을 activity에 반영 + 결과를 run_log에 기록.
    return await logged_run(
        conn, pipeline="collector", trigger="manual",
        clear=lambda: activity.clear("collector"),
        run=lambda: collect(conn, settings, http=request.app.state.http,
                            on_stage=lambda st, d, p: activity.set_stage("collector", st, d, str(p))),
    )


@router.post("/worker/run", status_code=202)
async def run_worker(request: Request, conn: Any = Depends(get_conn)):
    settings = await get_settings(conn)
    activity = request.app.state.activity
    return await logged_run(
        conn, pipeline="worker", trigger="manual",
        clear=lambda: activity.clear("worker"),
        run=lambda: worker_tick(conn, settings, http=request.app.state.http,
                                on_stage=lambda st, d, p: activity.set_stage("worker", st, d, str(p))),
    )
