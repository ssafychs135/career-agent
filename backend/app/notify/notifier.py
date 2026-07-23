"""공고 알림 — n8n 03-notifier에서 이관. 순수 로직(임베드·필터·청크) + notify_tick."""
import re

NOTIFY_BATCH = 30       # 한 틱에 다룰 공고 수(원본 값)
EMBED_CHUNK = 10        # Discord 한 메시지당 임베드 상한
EMBED_COLOR = 5814783   # 원본 값

# 요약 본문 끝의 "기술스택: ..." 줄은 별도 필드로 보여주므로 설명에서 제거.
_STACK_LINE = re.compile(r"\n?기술스택\s*[:：].*$", re.M)


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


def chunk(items: list, size: int = EMBED_CHUNK) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]
