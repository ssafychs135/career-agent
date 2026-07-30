"""공고 생존 재검증 — 매일 open 상태 전수검사.

점핏 만료는 closed_at이 이미 DB에 있어 SQL 한 번으로 끝난다. 나머지는
상세 API를 순회하며 소스별로 판정한다. 판정 불가는 open을 유지한다.
"""
import logging
from datetime import datetime
from urllib.parse import quote

from app.collect.config import DETAIL_TIMEOUT, JOB_PROXY_SECRET, JOB_PROXY_URL
from app.collect.detail import detail_url
from app.collect.liveness import CLOSED, DELETED, jumpit_state, wanted_state

log = logging.getLogger("collect.verify")

VERIFY_LOCK_KEY = 8123402  # 알림기(8123401)와 다른 키
VERIFY_HOUR = 0            # KST 자정(스케줄러 timezone=Asia/Seoul)

_UA = {"User-Agent": "Mozilla/5.0"}

# 점핏 만료는 API 없이 일괄 처리 — closed_at은 수집 시점에 이미 저장돼 있다.
EXPIRE_JUMPIT_SQL = (
    "UPDATE jobs SET posting_state='closed', state_checked_at=now() "
    "WHERE posting_state='open' AND source='jumpit' "
    "AND closed_at IS NOT NULL AND closed_at < now()"
)
SELECT_OPEN_SQL = (
    "SELECT id, source, job_id FROM jobs WHERE posting_state='open' ORDER BY id"
)
MARK_STATE_SQL = (
    "UPDATE jobs SET posting_state=$1, state_checked_at=now() WHERE id=$2"
)


def _request(source: str, job_id: str):
    """(url, headers) — 원티드만 프록시를 경유한다(수집기와 동일 규칙)."""
    url = detail_url(source, job_id)
    if source == "wanted" and JOB_PROXY_URL:
        return (f"{JOB_PROXY_URL}/?url={quote(url, safe='')}",
                {**_UA, "X-Proxy-Secret": JOB_PROXY_SECRET})
    return url, _UA


async def verify_tick(conn, *, http, on_stage=None) -> dict:
    # 스케줄 틱과 수동 실행이 겹치면 같은 행을 두 번 조회·판정한다. 하나만 돌린다.
    if not await conn.fetchval("SELECT pg_try_advisory_lock($1)", VERIFY_LOCK_KEY):
        return {"checked": 0, "closed": 0, "deleted": 0, "failed": 0}
    try:
        await conn.execute(EXPIRE_JUMPIT_SQL)

        rows = [dict(r) for r in await conn.fetch(SELECT_OPEN_SQL)]
        now = datetime.now()
        closed = deleted = failed = 0
        for i, row in enumerate(rows):
            source, job_id = row["source"], row["job_id"]
            if on_stage:
                on_stage("생존 확인", f"{source}:{job_id}", f"{i+1}/{len(rows)}")
            url, hdr = _request(source, job_id)
            try:
                resp = await http.get(url, headers=hdr, timeout=DETAIL_TIMEOUT)
                payload = resp.json()
                status_code = resp.status_code
            except Exception:  # noqa: BLE001 — 판정 불가. 숨기지 않는다.
                failed += 1
                continue
            try:
                state = (wanted_state(status_code, payload) if source == "wanted"
                         else jumpit_state(status_code, payload, now))
            except Exception:  # noqa: BLE001 — 파싱 이상도 판정 불가로 취급
                failed += 1
                continue
            await conn.execute(MARK_STATE_SQL, state, row["id"])
            if state == CLOSED:
                closed += 1
            elif state == DELETED:
                deleted += 1
        log.info("verify: checked=%d closed=%d deleted=%d failed=%d",
                 len(rows), closed, deleted, failed)
        return {"checked": len(rows), "closed": closed,
                "deleted": deleted, "failed": failed}
    finally:
        await conn.execute("SELECT pg_advisory_unlock($1)", VERIFY_LOCK_KEY)
