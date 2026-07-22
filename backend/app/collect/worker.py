from app.collect.detail import detail_url, parse_detail
from app.collect.config import DETAIL_TIMEOUT, JOB_PROXY_SECRET, JOB_PROXY_URL
from app.collect.health import llm_healthy
from app.collect.summarize import extract_stacks, summarize

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
    if not await health(http):
        return {"claimed": 0, "done": 0, "failed": 0, "skipped_tick": True}

    batch = await claim_batch(conn, settings.batch_size)
    if on_stage and batch:
        on_stage("배치 점유", f"{len(batch)}건", 0)
    done = failed = 0
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
        if on_stage:
            on_stage("요약 중", f"{job.get('company') or ''} · {title}", f"{i+1}/{len(batch)}")
        try:
            content = await summarizer(prompt, settings, http=http)
        except Exception:  # noqa: BLE001 — 요약 실패도 상세 실패와 동일하게 재시도 캡으로
            content = None
        if content:
            await conn.execute(_DONE_SQL, content, extract_stacks(content), job["id"])
            done += 1
        else:
            await conn.execute(_RETRY_SQL, settings.max_attempts, job["id"])
            failed += 1
    return {"claimed": len(batch), "done": done, "failed": failed, "skipped_tick": False}
