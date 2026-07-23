"""필터 UI가 쓰는 지역·기업 목록. 전역 필터를 적용하지 않는다 —
숨긴 기업도 반환해야 다시 켤 수 있다(escape hatch)."""

# locations는 "서울 강남구, 경기 성남시" 형태의 단일 텍스트.
# 콤마로 쪼개 첫 토큰(시/도)을 취하고, 공고 단위로 중복 제거해 센다
# (한 공고가 같은 시/도를 두 번 가져도 1).
REGIONS_SQL = (
    "SELECT split_part(btrim(part), ' ', 1) AS name, "
    "count(DISTINCT (source, job_id)) AS count "
    "FROM jobs, regexp_split_to_table(locations, ',') AS part "
    "WHERE locations IS NOT NULL AND btrim(part) <> '' "
    "GROUP BY 1 "
    "HAVING split_part(btrim(part), ' ', 1) <> '' "
    "ORDER BY count DESC, name"
)

COMPANIES_SQL = (
    "SELECT company AS name, count(*) AS count FROM jobs "
    "WHERE company IS NOT NULL AND company <> '' "
    "GROUP BY 1 ORDER BY count DESC, name"
)


async def get_facets(conn) -> dict:
    regions = await conn.fetch(REGIONS_SQL)
    companies = await conn.fetch(COMPANIES_SQL)
    return {
        "regions": [dict(r) for r in regions],
        "companies": [dict(r) for r in companies],
    }
