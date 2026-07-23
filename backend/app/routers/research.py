from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel

from app.db import get_conn  # Plan ② 제공 (계약 1번; 테스트 dependency_overrides 대상)
from app.research import runner, store
from app.run_log import logged_run

router = APIRouter(prefix="/api/research", tags=["research"])


async def _logged_company(pool, company: str, *, force: bool, activity) -> None:
    async with pool.acquire() as conn:
        await logged_run(
            conn, pipeline="research", trigger="manual", ref=company, label=company,
            run=lambda: runner.research_company(pool, company, "", force=force, activity=activity),
        )


async def _logged_job(pool, source: str, job_id: str, *, label: str, force: bool, activity) -> None:
    async with pool.acquire() as conn:
        await logged_run(
            conn, pipeline="research", trigger="manual",
            ref=f"{source}:{job_id}", label=label,
            run=lambda: runner.research_job(pool, source, job_id, force=force, activity=activity),
        )


class CompanyReq(BaseModel):
    company: str
    force: bool = False


class JobReq(BaseModel):
    source: str
    job_id: str
    force: bool = False


@router.post("/company", status_code=202)
async def trigger_company(
    req: CompanyReq, bg: BackgroundTasks, request: Request, conn=Depends(get_conn)
):
    # 계약 7번: 202 전 running upsert → 폴링이 즉시 running을 봄.
    await store.mark_company_running(conn, req.company)
    # BackgroundTask에는 요청 스코프 conn(응답 후 반납됨) 대신 풀을 넘겨 러너가 자체 acquire.
    bg.add_task(
        _logged_company, request.app.state.db, req.company,
        force=req.force, activity=request.app.state.activity,
    )
    return {"status": "running", "company": req.company}


@router.post("/job", status_code=202)
async def trigger_job(
    req: JobReq, bg: BackgroundTasks, request: Request, conn=Depends(get_conn)
):
    meta = await store.get_job_meta(conn, req.source, req.job_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="job not found")
    # 계약 7번: 202 전 running upsert.
    await store.mark_job_running(conn, req.source, req.job_id, meta["company"])
    label = meta.get("title") or meta.get("company") or f"{req.source}:{req.job_id}"
    bg.add_task(
        _logged_job, request.app.state.db, req.source, req.job_id,
        label=label, force=req.force, activity=request.app.state.activity,
    )
    return {"status": "running", "source": req.source, "job_id": req.job_id}


def init_research(app) -> None:
    """main.py에서 한 번 호출: 라우터 include만.

    계약 6a: 스케줄러 start/stop은 **Plan ②의 단일 lifespan**이 `start_scheduler(app)`/
    `stop_scheduler(app)`로 소유한다. 여기서 `add_event_handler`로 등록하면 커스텀 lifespan에
    무시되어 자동모드가 조용히 안 뜬다 → 등록하지 않는다.
    """
    app.include_router(router)
