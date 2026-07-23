import logging

from app.claude_client import run_claude
from app.llm_tier import escalate, resolve
from app.research import store
from app.research.config import RESEARCH_TIMEOUT
from app.research.discord import push
from app.research.parse import parse_research_json
from app.research.prompts import (
    RESEARCH_TOOLS,
    build_company_prompt,
    build_job_prompt,
)

log = logging.getLogger("research")


def _model_for(settings) -> str:
    """settings가 없으면(=CLI·구 호출자) 코드 기본 티어."""
    return resolve("research", settings.research_model if settings else "")


async def _run_and_parse(prompt, runner, model, on_step=None) -> tuple[dict, str]:
    """claude 호출 → JSON 파싱. 파싱 실패 시 한 단계 승급해 1회만 재시도.

    반환: (파싱결과, 실제로 성공한 모델). 같은 모델에게 같은 걸 다시 시키는 대신
    승급하므로, 비용이 실제로 어려웠던 실행에만 붙는다.
    """
    text = await runner(prompt, model=model, allowed_tools=RESEARCH_TOOLS,
                        timeout=RESEARCH_TIMEOUT, on_step=on_step)
    try:
        return parse_research_json(text), model
    except ValueError:
        up = escalate(model)
        retry = prompt + "\n\n[재시도] 반드시 JSON 객체 하나만 출력. 그 외 텍스트 금지."
        text = await runner(retry, model=up, allowed_tools=RESEARCH_TOOLS,
                            timeout=RESEARCH_TIMEOUT, on_step=on_step)
        return parse_research_json(text), up


async def research_company(
    db, company, url="", *, settings=None, force=False, runner=run_claude,
    notify=push, activity=None,
) -> str:
    existing = await store.get_company(db, company)
    if existing and existing.get("status") == "done" and not force:
        return "cached"

    await store.mark_company_running(db, company)
    prompt = build_company_prompt(company, url)
    model = _model_for(settings)

    def _step(label):
        if activity is not None:
            activity.add_research(company, "기업 리서치 중", label)

    _step("")  # 시작 시 stage 게시(라벨 없이)
    try:
        parsed, used = await _run_and_parse(prompt, runner, model, on_step=_step)
    except Exception as e:  # noqa: BLE001 — 어떤 실패든 failed로 표면화
        log.warning("company research failed: %s (model=%s): %s", company, model, e)
        # 승급 여부는 예외에 실리지 않으므로 1차 시도 모델을 남긴다.
        await store.save_company(db, company, status="failed", model=model)
        await notify(f"🔴 기업 리서치 실패: {company}")
        if activity is not None:
            activity.clear_research(company)
        return "failed"

    await store.save_company(
        db, company, status="done",
        overview=parsed.get("overview"), stability=parsed.get("stability"),
        data=parsed, sources=parsed.get("sources"), model=used,
    )
    await notify(f"🏢 기업 리서치 완료: {company}")
    if activity is not None:
        activity.clear_research(company)
    return "done"


async def research_job(
    db, source, job_id, *, settings=None, force=False, runner=run_claude,
    notify=push, activity=None,
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

    # ① 기업 리서치 선행(캐시되면 내부에서 skip). 같은 설정을 그대로 넘긴다.
    await research_company(
        db, meta["company"], meta.get("url", "") or "", settings=settings,
        runner=runner, notify=notify, activity=activity,
    )
    company_row = await store.get_company(db, meta["company"])
    overview = (company_row or {}).get("overview", "") or ""

    await store.mark_job_running(db, source, job_id, meta["company"])
    prompt = build_job_prompt(
        overview, meta.get("title", ""), meta.get("tech_stacks", ""),
        meta.get("summary", ""), meta.get("url", ""),
    )
    model = _model_for(settings)
    _step("")  # 시작 시 stage 게시(라벨 없이)
    try:
        parsed, used = await _run_and_parse(prompt, runner, model, on_step=_step)
    except Exception as e:  # noqa: BLE001
        log.warning("job research failed: %s:%s (model=%s): %s", source, job_id, model, e)
        await store.save_job(
            db, source, job_id, meta["company"], status="failed", model=model,
        )
        await notify(f"🔴 공고 리서치 실패: {meta['company']} {source}:{job_id}")
        if activity is not None:
            activity.clear_research(key)
        return "failed"

    await store.save_job(
        db, source, job_id, meta["company"], status="done",
        tech_detail=parsed.get("tech_detail"), role_detail=parsed.get("role_detail"),
        data=parsed, sources=parsed.get("sources"), model=used,
    )
    await notify(f"📋 공고 리서치 완료: {meta['company']} {source}:{job_id}")
    if activity is not None:
        activity.clear_research(key)
    return "done"
