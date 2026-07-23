from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException

from app import collect_scheduler, db
from app.activity import Activity
from app.claude_client import run_claude
from app.routers import collect as collect_router
from app.routers import db as db_router
from app.routers import facets as facets_router
from app.routers import jobs as jobs_router
from app.routers import runs as runs_router
from app.routers import settings as settings_router
from app.routers import status as status_router
from app.routers import research
from app.settings_repo import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = await db.connect()      # asyncpg 풀(계약 1번)
    # 계약 6a: 스케줄러 훅을 이 단일 lifespan이 소유. ④ 미머지 시점엔 import 실패 → no-op.
    try:
        from app.research.scheduler import start_scheduler, stop_scheduler
    except ImportError:  # 플랜 ④ 미머지 — 스케줄러 없음
        def start_scheduler(app):  # noqa: ARG001
            return None

        def stop_scheduler(app):  # noqa: ARG001
            return None
    app.state.http = httpx.AsyncClient()
    app.state.activity = Activity()
    # stale recovery: 이전 프로세스가 처리 중이던 행을 pending으로 되돌림
    async with app.state.db.acquire() as conn:
        await conn.execute("UPDATE jobs SET status='pending' WHERE status='processing'")
        settings = await get_settings(conn)
    collect_scheduler.start_collect_scheduler(app)
    collect_scheduler.reschedule(app, settings)  # DB 값으로 트리거 정렬
    app.state.reschedule_pipelines = lambda s: collect_scheduler.reschedule(app, s)
    try:
        start_scheduler(app)               # ④ 제공, 멱등·RESEARCH_AUTO_ENABLED false면 no-op
        yield
    finally:
        stop_scheduler(app)                # ④ 제공, 멱등·스케줄러 없으면 no-op
        collect_scheduler.stop_collect_scheduler(app)
        await app.state.http.aclose()
        await db.close(app.state.db)


app = FastAPI(title="career-agent", lifespan=lifespan)
app.include_router(collect_router.router)
app.include_router(db_router.router)
app.include_router(jobs_router.router)
app.include_router(settings_router.router)
app.include_router(status_router.router)
app.include_router(runs_router.router)
app.include_router(facets_router.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/claude-check")
async def claude_check():
    try:
        text = await run_claude("Reply with exactly: OK")
    except Exception as e:  # noqa: BLE001 — 어떤 실패든 503로 표면화
        raise HTTPException(status_code=503, detail=str(e))
    return {"ok": True, "reply": text.strip()}

research.init_research(app)
