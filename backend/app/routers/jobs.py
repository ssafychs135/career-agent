from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.db import get_conn
from app.jobs_repo import get_job, list_jobs
from app.settings_repo import get_settings

router = APIRouter(prefix="/api", tags=["jobs"])


@router.get("/jobs")
async def get_jobs(
    status: Optional[str] = None,
    source: Optional[str] = None,
    location: Optional[str] = None,
    tech: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    conn: Any = Depends(get_conn),
):
    # 전역 필터(설정)를 목록에만 적용 — 상세 조회는 영향받지 않는다.
    s = await get_settings(conn)
    return await list_jobs(
        conn,
        status=status,
        source=source,
        location=location,
        tech=tech,
        keyword=keyword,
        allowed_regions=s.allowed_regions,
        hidden_companies=s.hidden_companies,
        limit=limit,
        offset=offset,
    )


@router.get("/jobs/{source}/{job_id}")
async def get_job_detail(source: str, job_id: str, conn: Any = Depends(get_conn)):
    detail = await get_job(conn, source, job_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="job not found")
    return detail
