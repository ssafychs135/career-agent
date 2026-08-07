"""공고 알림 — n8n 03-notifier에서 이관. 순수 로직(임베드·필터) + notify_tick."""
import asyncio
import logging
import re
from datetime import datetime

from app.research.discord import push_embeds

log = logging.getLogger("notify.notifier")

NOTIFY_BATCH = 30       # 한 틱에 다룰 공고 수(원본 값)
EMBED_COLOR = 5814783   # 원본 값
NOTIFY_LOCK_KEY = 8123401  # notify_tick 동시 실행 방지용 advisory lock 키

# 한 메시지에 임베드 하나. 디스코드가 여러 임베드를 묶은 메시지를 code:0 500으로
# 거절하는 것을 확인했다(문서상 한도인 10개·6000자를 모두 지켰는데도). 같은 9건을
# 따로 보내면 전부 204로 성공했다. 건별 발송이라 웹훅 레이트리밋에 여유를 둔다.
SEND_GAP = 0.25         # 초

# 요약 본문 끝의 "기술스택: ..." 줄은 별도 필드로 보여주므로 설명에서 제거.
# 줄머리 마크다운 장식(-, *, #)과 라벨을 감싼 볼드를 함께 허용한다 —
# claude가 "**기술스택**:"으로 쓰면 예전 패턴이 못 잡아 설명에 중복 노출됐다.
_STACK_LINE = re.compile(r"\n?[ \t]*[-*#>]*[ \t]*\**\s*기술스택\s*\**\s*[:：].*$", re.M)


def build_embed(row: dict) -> dict:
    company = (row.get("company") or "").strip()
    title = (row.get("title") or "").strip()
    desc = _STACK_LINE.sub("", row.get("summary") or "", count=1).strip()
    if len(desc) > 400:
        desc = desc[:400] + "…"
    stacks = row.get("tech_stacks") or []
    stacks_s = ", ".join(stacks) if isinstance(stacks, (list, tuple)) else str(stacks)
    career = "~".join(
        str(v) for v in (row.get("min_career"), row.get("max_career")) if v is not None
    ) or "무관"
    return {
        "title": f"{company} — {title}"[:250],
        "url": row.get("url"),
        "color": EMBED_COLOR,
        "description": desc or "(요약 없음)",
        "fields": [
            {"name": "경력", "value": career, "inline": True},
            {"name": "기술스택", "value": (stacks_s or "-")[:1000], "inline": True},
            {"name": "출처", "value": str(row.get("source") or ""), "inline": True},
        ],
    }


def passes_filter(row: dict, allowed_regions, hidden_companies) -> bool:
    """전역 필터를 알림에도 적용. 빈 배열이면 해당 조건 미적용(목록 쿼리와 동일 규칙)."""
    if hidden_companies and (row.get("company") or "").strip() in set(hidden_companies):
        return False
    if allowed_regions:
        locs = row.get("locations") or ""
        if not any(r in locs for r in allowed_regions):
            return False
    return True


SELECT_SQL = (
    "SELECT id, source, job_id, company, title, url, locations, "
    "min_career, max_career, tech_stacks, summary "
    "FROM jobs WHERE status='done' AND notified_at IS NULL "
    "AND posting_state = 'open' "
    "ORDER BY collected_at LIMIT $1"
)
MARK_SQL = "UPDATE jobs SET notified_at=now() WHERE id = ANY($1::bigint[]) AND notified_at IS NULL"


async def notify_tick(conn, settings, *, sender=push_embeds, on_stage=None,
                      gap: float = SEND_GAP) -> dict:
    # 스케줄 틱과 수동 실행은 서로 다른 커넥션이라 SELECT→발송→UPDATE 사이에 겹칠 수 있고,
    # 그러면 아직 마킹되지 않은 같은 행을 양쪽이 각자 보내 중복 발송된다. 한 번에 하나만 돌린다.
    if not await conn.fetchval("SELECT pg_try_advisory_lock($1)", NOTIFY_LOCK_KEY):
        return {"picked": 0, "sent": 0, "skipped": 0, "failed": 0}
    try:
        rows = [dict(r) for r in await conn.fetch(SELECT_SQL, NOTIFY_BATCH)]
        if not rows:
            return {"picked": 0, "sent": 0, "skipped": 0, "failed": 0}

        keep, drop = [], []
        for r in rows:
            target = keep if passes_filter(
                r, settings.allowed_regions, settings.hidden_companies
            ) else drop
            target.append(r)

        # 전역 필터로 걸러진 공고는 발송 없이 소비 — 나중에 숨김을 풀어도 밀린 알림이 쏟아지지 않는다.
        if drop:
            await conn.execute(MARK_SQL, [r["id"] for r in drop])

        header = f"📋 **새 채용 공고 {len(keep)}건** ({datetime.now().strftime('%Y-%m-%d')})"
        sent = failed = 0
        for i, r in enumerate(keep):
            if on_stage:
                on_stage("알림 발송", r.get("company") or "", f"{i + 1}/{len(keep)}")
            try:
                # 헤더는 처음 성공하는 메시지에 붙는다 — 첫 건이 실패해도 잃지 않는다.
                await sender(header if sent == 0 else None, [build_embed(r)])
            except Exception as e:  # noqa: BLE001 — 한 건의 실패가 나머지를 막지 않는다
                failed += 1
                log.warning("notify: 발송 실패 id=%s — 다음 틱에 재시도: %s", r["id"], e)
                continue
            # 건별 마킹 — 성공분만 소비되어 재발송(중복)이 없다.
            await conn.execute(MARK_SQL, [r["id"]])
            sent += 1
            if gap and i < len(keep) - 1:
                await asyncio.sleep(gap)

        return {"picked": len(rows), "sent": sent, "skipped": len(drop), "failed": failed}
    finally:
        await conn.execute("SELECT pg_advisory_unlock($1)", NOTIFY_LOCK_KEY)
