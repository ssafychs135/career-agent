import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.research import runner, store
from app.research.config import (
    RESEARCH_AUTO_ENABLED,
    RESEARCH_AUTO_INTERVAL_MIN,
    RESEARCH_AUTO_LIMIT,
)

log = logging.getLogger("research.scheduler")


async def tick(get_pool, get_activity=lambda: None) -> None:
    """미리서치 대상 회사/공고를 limit만큼 처리(자동모드 잡 본체)."""
    db = get_pool()
    activity = get_activity()
    for company in await store.pending_companies(db, RESEARCH_AUTO_LIMIT):
        await runner.research_company(db, company, activity=activity)
    for source, job_id in await store.pending_jobs(db, RESEARCH_AUTO_LIMIT):
        await runner.research_job(db, source, job_id, activity=activity)


def start_scheduler(app) -> None:
    """계약 6a: Plan ②의 단일 lifespan이 startup에서 호출.

    **멱등**(이미 시작됐으면 그대로 반환) · `RESEARCH_AUTO_ENABLED=false`면 **no-op**.
    `add_event_handler`를 쓰지 않는다 — 커스텀 lifespan이 있으면 Starlette가 무시하므로.
    자동모드가 켜져 있으면 interval 잡 1개로 스케줄러를 시작해 `app.state`에 보관한다.
    """
    if getattr(app.state, "research_scheduler", None) is not None:
        return  # 멱등: 이미 시작됨
    if not RESEARCH_AUTO_ENABLED:
        app.state.research_scheduler = None
        log.info("research auto-mode disabled (RESEARCH_AUTO_ENABLED=false)")
        return
    sched = AsyncIOScheduler()
    # tick은 get_pool()로 풀을 얻는다 → app.state.db(Plan ② lifespan이 채움)를 지연 참조.
    sched.add_job(
        tick, "interval", minutes=RESEARCH_AUTO_INTERVAL_MIN,
        args=[lambda: app.state.db, lambda: app.state.activity],
    )
    sched.start()
    app.state.research_scheduler = sched
    log.info("research auto-mode enabled: every %d min", RESEARCH_AUTO_INTERVAL_MIN)


def stop_scheduler(app) -> None:
    """계약 6a: lifespan의 finally에서 호출. **멱등** — 스케줄러 없으면 no-op."""
    sched = getattr(app.state, "research_scheduler", None)
    if sched is not None:
        sched.shutdown(wait=False)
        app.state.research_scheduler = None
