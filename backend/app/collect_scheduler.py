import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.collect.collector import collect
from app.collect.worker import worker_tick
from app.settings_repo import get_settings

log = logging.getLogger("collect.scheduler")


async def collector_job(get_ctx) -> None:
    pool, http = get_ctx()
    async with pool.acquire() as conn:
        settings = await get_settings(conn)
        if not settings.enabled:
            return
        await collect(conn, settings, http=http)


async def worker_job(get_ctx) -> None:
    pool, http = get_ctx()
    async with pool.acquire() as conn:
        settings = await get_settings(conn)
        if not settings.enabled:
            return
        await worker_tick(conn, settings, http=http)


def start_collect_scheduler(app) -> None:
    """멱등. collector(cron 매일 collect_hour시)·worker(interval) 잡 등록.

    잡은 항상 등록되고, 각 틱이 settings.enabled를 확인해 no-op한다(플래그 컷오버).
    초기 트리거는 DEFAULT(09시/5분) — 실제 값은 lifespan이 reschedule로 맞춘다.
    """
    if getattr(app.state, "collect_scheduler", None) is not None:
        return
    sched = AsyncIOScheduler()
    get_ctx = lambda: (app.state.db, app.state.http)  # noqa: E731
    sched.add_job(collector_job, "cron", id="collector", hour=9, minute=0, args=[get_ctx])
    sched.add_job(worker_job, "interval", id="worker", minutes=5, args=[get_ctx])
    sched.start()
    app.state.collect_scheduler = sched
    log.info("collect scheduler started")


def stop_collect_scheduler(app) -> None:
    sched = getattr(app.state, "collect_scheduler", None)
    if sched is not None:
        sched.shutdown(wait=False)
        app.state.collect_scheduler = None


def reschedule(app, settings) -> None:
    """collect_hour / worker_interval_min 변경을 즉시 반영."""
    sched = getattr(app.state, "collect_scheduler", None)
    if sched is None:
        return
    sched.reschedule_job("collector", trigger="cron", hour=settings.collect_hour, minute=0)
    sched.reschedule_job("worker", trigger="interval", minutes=settings.worker_interval_min)
