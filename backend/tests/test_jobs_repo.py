from app.jobs_repo import _split_detail, build_list_query


def test_build_query_no_filters():
    sql, params = build_list_query(limit=20, offset=0)
    assert "WHERE" not in sql.split("FROM jobs", 1)[1]
    assert "FROM jobs" in sql
    assert "COUNT(*) OVER()" in sql
    assert "has_company_research" in sql
    assert "has_job_research" in sql
    assert "ORDER BY collected_at DESC" in sql
    # 결정적 페이지네이션 — (source, job_id) 유니크 tiebreaker로 OFFSET 중복/누락 방지.
    assert "collected_at DESC NULLS LAST, source, job_id" in sql
    assert params == [20, 0]


def test_build_query_status_and_source():
    sql, params = build_list_query(status="open", source="saramin", limit=10, offset=0)
    assert "status = $1" in sql
    assert "source = $2" in sql
    assert params == ["open", "saramin", 10, 0]


def test_build_query_keyword_searches_multiple_columns():
    sql, params = build_list_query(keyword="dev", limit=20, offset=0)
    assert "title ILIKE $1" in sql
    assert "summary ILIKE $1" in sql
    assert "company ILIKE $1" in sql
    assert params[0] == "%dev%"


def test_build_query_tech_casts_tech_stacks():
    sql, params = build_list_query(tech="python", limit=20, offset=0)
    assert "CAST(tech_stacks AS text) ILIKE $1" in sql
    assert params[0] == "%python%"


def test_build_query_location_scalar_ilike():
    sql, params = build_list_query(location="서울", limit=20, offset=0)
    assert "locations ILIKE $1" in sql
    assert "CAST(locations" not in sql
    assert params[0] == "%서울%"


def test_build_query_pagination_positions():
    sql, params = build_list_query(status="open", limit=50, offset=100)
    assert "LIMIT $2 OFFSET $3" in sql
    assert params == ["open", 50, 100]


def test_build_query_ignores_none_and_empty():
    sql, params = build_list_query(status=None, source="", keyword=None, limit=20, offset=0)
    assert "WHERE" not in sql.split("FROM jobs", 1)[1]
    assert params == [20, 0]


def test_build_query_allowed_regions_ors_ilike():
    sql, params = build_list_query(allowed_regions=["서울", "경기"], limit=20, offset=0)
    assert "(locations ILIKE $1 OR locations ILIKE $2)" in sql
    assert params[0] == "%서울%" and params[1] == "%경기%"


def test_build_query_hidden_companies_excludes_with_null_guard():
    sql, params = build_list_query(hidden_companies=["미스릴"], limit=20, offset=0)
    # company가 NULL이면 NOT(...=ANY)가 NULL이 되어 행이 통째로 빠진다 → IS NULL 방어 필수
    assert "(company IS NULL OR NOT (company = ANY($1::text[])))" in sql
    assert params[0] == ["미스릴"]


def test_build_query_empty_global_filters_add_no_clause():
    sql, params = build_list_query(allowed_regions=[], hidden_companies=[], limit=20, offset=0)
    assert "locations ILIKE" not in sql
    assert "company = ANY" not in sql
    assert params == [20, 0]


def test_build_query_global_filters_combine_with_existing():
    sql, params = build_list_query(
        status="done", allowed_regions=["서울"], hidden_companies=["미스릴"], limit=5, offset=10,
    )
    # $N 넘버링 정합 — status $1, 지역 $2, 기업 $3, limit $4, offset $5
    assert "status = $1" in sql
    assert "locations ILIKE $2" in sql
    assert "company = ANY($3::text[])" in sql
    assert "LIMIT $4 OFFSET $5" in sql
    assert params == ["done", "%서울%", ["미스릴"], 5, 10]


def _make_detail_row(*, cr_sources, jr_sources):
    return {
        "source": "saramin",
        "job_id": "123",
        "company": "acme",
        "title": "backend dev",
        "url": "https://example.com/jobs/123",
        "locations": "서울",
        "min_career": 0,
        "max_career": 3,
        "tech_stacks": '["python","fastapi"]',
        "summary": "summary text",
        "status": "open",
        "attempts": 0,
        "collected_at": None,
        "updated_at": None,
        "closed_at": None,
        "cr_overview": "overview",
        "cr_stability": "stable",
        "cr_sources": cr_sources,
        "cr_status": "done",
        "cr_researched_at": None,
        "jr_tech_detail": "tech detail",
        "jr_role_detail": "role detail",
        "jr_sources": jr_sources,
        "jr_status": "done",
        "jr_researched_at": None,
    }


def test_split_detail_unwraps_json_string_sources():
    row = _make_detail_row(
        cr_sources='["https://u1","https://u2"]',
        jr_sources='["https://u1","https://u2"]',
    )
    result = _split_detail(row)
    assert result["companyResearch"]["sources"] == ["https://u1", "https://u2"]
    assert result["jobResearch"]["sources"] == ["https://u1", "https://u2"]


def test_split_detail_passes_through_list_sources():
    row = _make_detail_row(
        cr_sources=["https://u1", "https://u2"],
        jr_sources=["https://u1", "https://u2"],
    )
    result = _split_detail(row)
    assert result["companyResearch"]["sources"] == ["https://u1", "https://u2"]
    assert result["jobResearch"]["sources"] == ["https://u1", "https://u2"]


def test_split_detail_none_sources_stay_none():
    row = _make_detail_row(cr_sources=None, jr_sources=None)
    result = _split_detail(row)
    assert result["companyResearch"]["sources"] is None
    assert result["jobResearch"]["sources"] is None
