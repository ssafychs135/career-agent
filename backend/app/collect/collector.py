import logging
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
    "ON CONFLICT (source, job_id) DO NOTHING"
)


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
        r["min_career"], r["max_career"], r["tech_stacks"], r["locations"], r["closed_at"],
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
            except Exception:  # noqa: BLE001 — 네트워크 실패 시 이 키워드 종료
                break
            parsed = parse_jumpit_positions(payload, settings.keywords, settings.max_career_years)
            if not (payload or {}).get("result", {}).get("positions"):
                break
            rows.extend(parsed)
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
            except Exception:  # noqa: BLE001
                break
            if not (payload or {}).get("data"):
                break
            rows.extend(parse_wanted_results(
                payload, settings.allowed_wanted_categories,
                settings.keywords, settings.max_career_years,
            ))
    return rows


async def collect(conn, settings, *, http, on_stage=None) -> dict:
    rows = dedupe(await _scrape(settings, http, on_stage))
    if on_stage:
        on_stage("pending 적재", f"{len(rows)}건", len(rows))
    if rows:
        await conn.executemany(INSERT_SQL, [_row_params(r) for r in rows])
    log.info("collect: scraped=%d inserted=%d", len(rows), len(rows))
    return {"scraped": len(rows), "inserted": len(rows)}
