from typing import Any

from fastapi import APIRouter, Depends, Request

from app.collect.verify import verify_tick
from app.db import get_conn
from app.run_log import logged_run

router = APIRouter(prefix="/api", tags=["verify"])


@router.post("/verify/run", status_code=202)
async def run_verify(request: Request, conn: Any = Depends(get_conn)):
    # 수동 실행은 settings.enabled와 무관 — 배포 직후 첫 검사를 자정까지
    # 기다리지 않고 검증하기 위한 명시적 행동이다(수집기·알림기와 동일 규칙).
    return await logged_run(
        conn, pipeline="verify", trigger="manual",
        run=lambda: verify_tick(conn, http=request.app.state.http),
    )
