import logging

from app.claude_client import run_claude
from app.research import store
from app.research.config import RESEARCH_MODEL, RESEARCH_TIMEOUT
from app.research.discord import push
from app.research.parse import parse_research_json
from app.research.prompts import (
    RESEARCH_TOOLS,
    build_company_prompt,
    build_job_prompt,
)

log = logging.getLogger("research")


async def _run_and_parse(prompt, runner, on_step=None) -> dict:
    """claude 호출 → JSON 파싱. 파싱 실패 시 1회만 재시도. on_step은 서브스텝 콜백."""
    text = await runner(prompt, allowed_tools=RESEARCH_TOOLS, timeout=RESEARCH_TIMEOUT, on_step=on_step)
    try:
        return parse_research_json(text)
    except ValueError:
        retry = prompt + "\n\n[재시도] 반드시 JSON 객체 하나만 출력. 그 외 텍스트 금지."
        text = await runner(retry, allowed_tools=RESEARCH_TOOLS, timeout=RESEARCH_TIMEOUT, on_step=on_step)
        return parse_research_json(text)


async def research_company(
    db, company, url="", *, force=False, runner=run_claude, notify=push, activity=None,
) -> str:
    existing = await store.get_company(db, company)
    if existing and existing.get("status") == "done" and not force:
        return "cached"

    await store.mark_company_running(db, company)
    prompt = build_company_prompt(company, url)

    def _step(label):
        if activity is not None:
            activity.add_research(company, "기업 리서치 중", label)

    _step("")  # 시작 시 stage 게시(라벨 없이)
    try:
        parsed = await _run_and_parse(prompt, runner, on_step=_step)
    except Exception as e:  # noqa: BLE001 — 어떤 실패든 failed로 표면화
        log.warning("company research failed: %s: %s", company, e)
        await store.save_company(db, company, status="failed", model=RESEARCH_MODEL)
        await notify(f"🔴 기업 리서치 실패: {company}")
        if activity is not None:
            activity.clear_research(company)
        return "failed"

    await store.save_company(
        db, company, status="done",
        overview=parsed.get("overview"), stability=parsed.get("stability"),
        data=parsed, sources=parsed.get("sources"), model=RESEARCH_MODEL,
    )
    await notify(f"🏢 기업 리서치 완료: {company}")
    if activity is not None:
        activity.clear_research(company)
    return "done"


async def research_job(
    db, source, job_id, *, force=False, runner=run_claude, notify=push, activity=None,
) -> str:
    existing = await store.get_job(db, source, job_id)
    if existing and existing.get("status") == "done" and not force:
        return "cached"

    meta = await store.get_job_meta(db, source, job_id)
    if meta is None:
        raise LookupError(f"job not found: {source}:{job_id}")

    key = f"{source}:{job_id}"

    def _step(label):
        if activity is not None:
            activity.add_research(key, "공고 리서치 중", label)

    # ① 기업 리서치 선행(캐시되면 내부에서 skip)
    await research_company(
        db, meta["company"], meta.get("url", "") or "", runner=runner, notify=notify,
        activity=activity,
    )
    company_row = await store.get_company(db, meta["company"])
    overview = (company_row or {}).get("overview", "") or ""

    await store.mark_job_running(db, source, job_id, meta["company"])
    prompt = build_job_prompt(
        overview, meta.get("title", ""), meta.get("tech_stacks", ""),
        meta.get("summary", ""), meta.get("url", ""),
    )
    _step("")  # 시작 시 stage 게시(라벨 없이)
    try:
        parsed = await _run_and_parse(prompt, runner, on_step=_step)
    except Exception as e:  # noqa: BLE001
        log.warning("job research failed: %s:%s: %s", source, job_id, e)
        await store.save_job(
            db, source, job_id, meta["company"], status="failed", model=RESEARCH_MODEL,
        )
        await notify(f"🔴 공고 리서치 실패: {meta['company']} {source}:{job_id}")
        if activity is not None:
            activity.clear_research(key)
        return "failed"

    await store.save_job(
        db, source, job_id, meta["company"], status="done",
        tech_detail=parsed.get("tech_detail"), role_detail=parsed.get("role_detail"),
        data=parsed, sources=parsed.get("sources"), model=RESEARCH_MODEL,
    )
    await notify(f"📋 공고 리서치 완료: {meta['company']} {source}:{job_id}")
    if activity is not None:
        activity.clear_research(key)
    return "done"
