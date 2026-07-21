from fastapi import APIRouter, Depends, HTTPException

from app.db import get_conn

router = APIRouter(prefix="/api/db", tags=["db"])


@router.get("/health")
async def db_health(conn=Depends(get_conn)):
    try:
        jobs_count = await conn.fetchval("SELECT count(*) FROM jobs")
        pgvector = await conn.fetchval(
            "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
        )
    except Exception as e:  # noqa: BLE001 — 접속·쿼리 실패를 503으로 표면화
        raise HTTPException(status_code=503, detail=str(e))
    return {"ok": True, "jobs_count": int(jobs_count or 0), "pgvector": pgvector == 1}
