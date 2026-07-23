import json
from typing import Any

# 리스트 SELECT: 정본 계약 5번 리스트 아이템 컬럼 + 리서치 존재 플래그(EXISTS).
_SELECT = (
    "SELECT source, job_id, company, title, url, locations, "
    "min_career, max_career, status, collected_at, tech_stacks, "
    "COUNT(*) OVER() AS total_count, "
    "EXISTS(SELECT 1 FROM company_research cr WHERE cr.company = jobs.company) "
    "AS has_company_research, "
    "EXISTS(SELECT 1 FROM job_research jr WHERE jr.source = jobs.source "
    "AND jr.job_id = jobs.job_id) AS has_job_research "
    "FROM jobs"
)


def build_list_query(
    *,
    status: str | None = None,
    source: str | None = None,
    location: str | None = None,
    tech: str | None = None,
    keyword: str | None = None,
    allowed_regions: list[str] | None = None,
    hidden_companies: list[str] | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[str, list[Any]]:
    """필터 → 파라미터화된 SELECT SQL과 위치 인자 리스트. 값 보간 없음(전부 $N)."""
    clauses: list[str] = []
    params: list[Any] = []

    def add(template: str, value: Any) -> None:
        params.append(value)
        clauses.append(template.format(n=len(params)))

    if status:
        add("status = ${n}", status)
    if source:
        add("source = ${n}", source)
    if location:
        add("locations ILIKE ${n}", f"%{location}%")
    if tech:
        add("CAST(tech_stacks AS text) ILIKE ${n}", f"%{tech}%")
    if keyword:
        params.append(f"%{keyword}%")
        n = len(params)
        clauses.append(f"(title ILIKE ${n} OR summary ILIKE ${n} OR company ILIKE ${n})")

    # ── 전역 필터(설정) — 빈 값이면 절을 붙이지 않는다 ──
    if allowed_regions:
        # locations는 "서울 강남구, 경기 성남시" 형태의 단일 텍스트 → 지역별 ILIKE를 OR로.
        ors: list[str] = []
        for region in allowed_regions:
            params.append(f"%{region}%")
            ors.append(f"locations ILIKE ${len(params)}")
        clauses.append("(" + " OR ".join(ors) + ")")
    if hidden_companies:
        # company가 NULL이면 NOT(... = ANY(...))가 NULL이 되어 행이 통째로 빠진다 → IS NULL 방어.
        params.append(hidden_companies)
        clauses.append(f"(company IS NULL OR NOT (company = ANY(${len(params)}::text[])))")

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    limit_n = len(params)
    params.append(offset)
    offset_n = len(params)
    sql = (
        f"{_SELECT}{where} "
        # (source, job_id) 유니크 키를 tiebreaker로 — collected_at 동값이 많아(배치 수집)
        # tiebreaker 없으면 OFFSET 페이지네이션이 동값 경계 행을 중복/누락시킴.
        f"ORDER BY collected_at DESC NULLS LAST, source, job_id "
        f"LIMIT ${limit_n} OFFSET ${offset_n}"
    )
    return sql, params


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


def _row_to_summary(row: Any) -> dict[str, Any]:
    item = dict(row)
    item.pop("total_count", None)
    item["tech_stacks"] = _maybe_json(item.get("tech_stacks"))
    return item


async def list_jobs(conn: Any, **filters: Any) -> dict[str, Any]:
    limit = filters.get("limit", 20)
    offset = filters.get("offset", 0)
    sql, params = build_list_query(**filters)
    rows = await conn.fetch(sql, *params)
    total = rows[0]["total_count"] if rows else 0
    return {
        "items": [_row_to_summary(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


_DETAIL_SQL = (
    "SELECT "
    "  j.source, j.job_id, j.company, j.title, j.url, j.locations, "
    "  j.min_career, j.max_career, j.tech_stacks, j.summary, j.status, "
    "  j.attempts, j.collected_at, j.updated_at, j.closed_at, "
    "  cr.overview AS cr_overview, cr.stability AS cr_stability, "
    "  cr.sources AS cr_sources, cr.status AS cr_status, "
    "  cr.researched_at AS cr_researched_at, "
    "  jr.tech_detail AS jr_tech_detail, jr.role_detail AS jr_role_detail, "
    "  jr.sources AS jr_sources, jr.status AS jr_status, "
    "  jr.researched_at AS jr_researched_at, jr.model AS jr_model "
    "FROM jobs j "
    "LEFT JOIN company_research cr ON cr.company = j.company "
    "LEFT JOIN job_research jr ON jr.source = j.source AND jr.job_id = j.job_id "
    "WHERE j.source = $1 AND j.job_id = $2"
)


def _split_detail(row: Any) -> dict[str, Any]:
    d = dict(row)
    job = {
        "source": d["source"],
        "job_id": d["job_id"],
        "company": d["company"],
        "title": d["title"],
        "url": d["url"],
        "locations": d["locations"],
        "min_career": d["min_career"],
        "max_career": d["max_career"],
        "tech_stacks": _maybe_json(d["tech_stacks"]),
        "summary": d["summary"],
        "status": d["status"],
        "attempts": d["attempts"],
        "collected_at": d["collected_at"],
        "updated_at": d["updated_at"],
        "closed_at": d["closed_at"],
    }
    # LEFT JOIN 미스 시 cr_status / jr_status 가 NULL → 해당 블록은 None.
    company_research = None if d["cr_status"] is None else {
        "overview": d["cr_overview"],
        "stability": d["cr_stability"],
        "sources": _maybe_json(d["cr_sources"]),
        "status": d["cr_status"],
        "researched_at": d["cr_researched_at"],
    }
    job_research = None if d["jr_status"] is None else {
        "tech_detail": d["jr_tech_detail"],
        "role_detail": d["jr_role_detail"],
        "sources": _maybe_json(d["jr_sources"]),
        "status": d["jr_status"],
        "researched_at": d["jr_researched_at"],
        "model": d["jr_model"],
    }
    return {"job": job, "companyResearch": company_research, "jobResearch": job_research}


async def get_job(conn: Any, source: str, job_id: str) -> dict[str, Any] | None:
    row = await conn.fetchrow(_DETAIL_SQL, source, job_id)
    if row is None:
        return None
    return _split_detail(row)
