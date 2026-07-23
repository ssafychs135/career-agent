from app.collect.detail import detail_url, parse_detail
from app.collect.config import DETAIL_TIMEOUT, JOB_PROXY_SECRET, JOB_PROXY_URL
from app.collect.health import llm_healthy
from app.collect.summarize import extract_stacks, summarize
from app.llm_tier import resolve

_UA = {"User-Agent": "Mozilla/5.0"}

# pending을 원자적으로 점유 → 'processing' 마킹(SKIP LOCKED로 이중 처리 방지).
CLAIM_SQL = (
    "UPDATE jobs SET status='processing', updated_at=now() "
    "WHERE id IN ("
    "  SELECT id FROM jobs WHERE status='pending' "
    "  ORDER BY collected_at LIMIT $1 FOR UPDATE SKIP LOCKED"
    ") RETURNING id, source, job_id, company, title, url, attempts"
)

_DONE_SQL = (
    "UPDATE jobs SET status='done', summary=$1, "
    "tech_stacks=CASE WHEN cardinality(tech_stacks)>0 THEN tech_stacks ELSE $2::text[] END, "
    "attempts=attempts+1, updated_at=now() WHERE id=$3"
)
_RETRY_SQL = (
    "UPDATE jobs SET status=CASE WHEN attempts+1 >= $1 THEN 'failed' ELSE 'pending' END, "
    "attempts=attempts+1, updated_at=now() WHERE id=$2"
)


async def claim_batch(conn, limit: int) -> list[dict]:
    rows = await conn.fetch(CLAIM_SQL, limit)
    return [dict(r) for r in rows]


async def _fetch_detail(http, source, job_id):
    url = detail_url(source, job_id)
    if source == "wanted" and JOB_PROXY_URL:
        from urllib.parse import quote
        url = f"{JOB_PROXY_URL}/?url={quote(url, safe='')}"
        hdr = {**_UA, "X-Proxy-Secret": JOB_PROXY_SECRET}
    else:
        hdr = _UA
    r = await http.get(url, headers=hdr, timeout=DETAIL_TIMEOUT)
    return r.json()


async def worker_tick(conn, settings, *, http, summarizer=summarize,
                      health=llm_healthy, on_stage=None) -> dict:
    # LM Studio 헬스는 local 백엔드일 때만 본다. claude 요약은 맥 상태와 무관하며,
    # 여기에 묶어두면 맥이 꺼졌을 때 claude 요약까지 같이 멈춘다.
    if settings.summary_backend == "local" and not await health(http):
        return {"claimed": 0, "done": 0, "failed": 0, "escalated": 0, "skipped_tick": True}

    batch = await claim_batch(conn, settings.batch_size)
    if on_stage and batch:
        on_stage("배치 점유", f"{len(batch)}건", 0)
    done = failed = escalated = 0
    for i, job in enumerate(batch):
        title = job.get("title") or ""
        try:
            payload = await _fetch_detail(http, job["source"], job["job_id"])
            body = parse_detail(job["source"], payload)
        except Exception:  # noqa: BLE001 — 상세조회 실패
            body = None
        if body is None:
            await conn.execute(_RETRY_SQL, settings.max_attempts, job["id"])
            failed += 1
            continue
        prompt = f"제목: {title}\n회사: {job.get('company') or ''}\n\n{body}"
        # 전에 실패한 적 있는 잡은 한 단계 위 티어로 재시도한다. 단 승급은 claude
        # 백엔드에서만 의미가 있다 — local 분기는 model 인자를 무시하므로, local
        # 모드에서 escalated를 세면 실행 로그에 없던 "·승급" 라벨이 붙는다.
        # attempts는 상세조회 실패로도 오르지만, 그 부정확은 드물고 무해하다.
        is_retry = job["attempts"] > 0 and settings.summary_backend == "claude"
        model = resolve("summary", settings.summary_model, escalated=is_retry)
        if is_retry:
            escalated += 1
        if on_stage:
            on_stage("요약 중", f"{job.get('company') or ''} · {title}", f"{i+1}/{len(batch)}")
        try:
            content = await summarizer(prompt, settings, http=http, model=model)
        except Exception:  # noqa: BLE001 — 요약 실패도 상세 실패와 동일하게 재시도 캡으로
            content = None
        if content:
            await conn.execute(_DONE_SQL, content, extract_stacks(content), job["id"])
            done += 1
        else:
            await conn.execute(_RETRY_SQL, settings.max_attempts, job["id"])
            failed += 1
    return {"claimed": len(batch), "done": done, "failed": failed,
            "escalated": escalated, "skipped_tick": False}
