from typing import Any

from fastapi import APIRouter, Depends

from app.db import get_conn
from app.notify.notifier import notify_tick
from app.run_log import logged_run
from app.settings_repo import get_settings

router = APIRouter(prefix="/api", tags=["notify"])


@router.post("/notify/run", status_code=202)
async def run_notify(conn: Any = Depends(get_conn)):
    settings = await get_settings(conn)
    # 수동 실행은 notify_enabled와 무관 — 명시적 행동이므로 항상 동작(컷오버 검증용).
    return await logged_run(
        conn, pipeline="notifier", trigger="manual",
        run=lambda: notify_tick(conn, settings),
    )
