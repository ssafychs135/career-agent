import logging
from datetime import datetime
from urllib.parse import quote

from app.collect.config import JOB_PROXY_SECRET, JOB_PROXY_URL
from app.collect.sources.jumpit import parse_jumpit_positions
from app.collect.sources.wanted import parse_wanted_results, wanted_list_url

log = logging.getLogger("collect.collector")
_UA = {"User-Agent": "Mozilla/5.0"}

INSERT_SQL = (
    "INSERT INTO jobs "
    "(source, job_id, company, title, url, min_career, max_career, tech_stacks, locations, closed_at) "
    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) "
    "ON CONFLICT (source, job_id) DO NOTHING "
    "RETURNING id"
)

# 목록에 다시 보인 공고는 살아있다 — 재검증기의 오판정과 재게시를 자동 복구한다.
# INSERT의 ON CONFLICT DO UPDATE로 합치지 않는 이유: RETURNING id에 중복 행까지
# 잡혀 inserted 카운트가 다시 거짓말을 하게 된다.
REVIVE_SQL = (
    "UPDATE jobs SET posting_state = 'open', state_checked_at = NULL "
    "WHERE posting_state <> 'open' "
    "AND (source, job_id) IN (SELECT unnest($1::text[]), unnest($2::text[]))"
)


def parse_dt(v):
    """소스 API의 closed_at은 ISO 문자열 → asyncpg timestamptz는 datetime을 요구.
    파싱 실패/빈값은 None(NULL). ('Z'·오프셋 포함 ISO 지원)."""
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def dedupe(rows: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in rows:
        key = (r["source"], r["job_id"])
        if not r["job_id"] or key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _row_params(r: dict) -> tuple:
    return (
        r["source"], r["job_id"], r["company"], r["title"], r["url"],
        r["min_career"], r["max_career"], r["tech_stacks"], r["locations"], parse_dt(r["closed_at"]),
    )


async def _scrape(settings, http, on_stage) -> list[dict]:
    cap = max(1, settings.max_pages)
    rows: list[dict] = []
    # 점핏: 키워드별 페이지네이션(빈 페이지에서 종료)
    for kw in settings.keywords:
        for page in range(1, cap + 1):
            if on_stage:
                on_stage("스크레이핑", f"점핏 · {kw} · {page}p", len(rows))
            url = f"https://jumpit-api.saramin.co.kr/api/positions?keyword={quote(kw)}&sort=relation&page={page}"
            try:
                payload = (await http.get(url, headers=_UA)).json()
            except Exception as e:  # noqa: BLE001 — 네트워크/디코딩 실패 → 이 키워드 종료
                log.warning("collect: 점핏 요청 실패 kw=%s page=%d — 이 키워드 중단(누적 %d건): %s: %s",
                            kw, page, len(rows), type(e).__name__, e)
                break
            # 빈 페이지 검사는 try 밖이라 스스로 안전해야 한다(result가 None인 응답 실재).
            # 형식이 깨진 응답과 정상적인 페이지 끝은 구분한다 — 전자만 남긴다(노이즈 방지).
            if not isinstance(payload, dict):
                log.warning("collect: 점핏 응답 형식 이상 kw=%s page=%d (%s) — 이 키워드 중단(누적 %d건)",
                            kw, page, type(payload).__name__, len(rows))
                break
            if not (payload.get("result") or {}).get("positions"):
                break
            try:
                rows.extend(parse_jumpit_positions(payload, settings.keywords, settings.max_career_years))
            except Exception:  # noqa: BLE001 — 이 페이지만 건너뛰고 계속(아래 주석 참조)
                log.warning("collect: 점핏 파싱 실패 kw=%s page=%d — 이 페이지 건너뜀", kw, page)
    # 원티드: 카테고리별 offset 페이지네이션
    for cat in settings.allowed_wanted_categories:
        for page in range(1, cap + 1):
            if on_stage:
                on_stage("스크레이핑", f"원티드 · {cat} · {page}p", len(rows))
            wurl = wanted_list_url(cat, (page - 1) * 20)
            if JOB_PROXY_URL:
                req_url = f"{JOB_PROXY_URL}/?url={quote(wurl, safe='')}"
                hdr = {**_UA, "X-Proxy-Secret": JOB_PROXY_SECRET}
            else:
                req_url, hdr = wurl, _UA
            try:
                payload = (await http.get(req_url, headers=hdr)).json()
            except Exception as e:  # noqa: BLE001 — 네트워크/디코딩 실패 → 이 카테고리 종료
                log.warning("collect: 원티드 요청 실패 cat=%s page=%d — 이 카테고리 중단(누적 %d건): %s: %s",
                            cat, page, len(rows), type(e).__name__, e)
                break
            if not isinstance(payload, dict):
                log.warning("collect: 원티드 응답 형식 이상 cat=%s page=%d (%s) — 이 카테고리 중단(누적 %d건)",
                            cat, page, type(payload).__name__, len(rows))
                break
            if not payload.get("data"):
                break
            # 파싱 실패는 이 페이지만 버리고 계속한다. 예전엔 break였는데, 공고 한 건의
            # 예상 못한 필드 형태가 카테고리 전체 페이지네이션을 끊어 뒤쪽 공고를
            # 통째로 잃었다(원티드 518에서 139건 중 8건만 수집되던 원인).
            try:
                rows.extend(parse_wanted_results(
                    payload, settings.allowed_wanted_categories,
                    settings.keywords, settings.max_career_years,
                ))
            except Exception:  # noqa: BLE001
                log.warning("collect: 원티드 파싱 실패 cat=%s page=%d — 이 페이지 건너뜀", cat, page)
    return rows


async def collect(conn, settings, *, http, on_stage=None) -> dict:
    rows = dedupe(await _scrape(settings, http, on_stage))
    if on_stage:
        on_stage("pending 적재", f"{len(rows)}건", len(rows))
    # RETURNING id로 실제로 새로 들어간 행만 센다 — 중복은 ON CONFLICT로 건너뛰어
    # None을 돌려준다. 행별 INSERT라 수동/스케줄 수집이 겹쳐도 경쟁 안전하다
    # (executemany는 rowcount를 안 줘 스크레이핑 수를 삽입 수로 착각하게 했다).
    inserted = 0
    for r in rows:
        if await conn.fetchval(INSERT_SQL, *_row_params(r)) is not None:
            inserted += 1
    if rows:
        await conn.execute(REVIVE_SQL, [r["source"] for r in rows],
                           [r["job_id"] for r in rows])
    log.info("collect: scraped=%d inserted=%d", len(rows), inserted)
    return {"scraped": len(rows), "inserted": inserted}
