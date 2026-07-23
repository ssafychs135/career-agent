from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.facets_repo import COMPANIES_SQL, REGIONS_SQL, get_facets
from app.routers import facets as facets_router


class FakeConn:
    def __init__(self, regions, companies):
        self._regions, self._companies = regions, companies
        self.queries = []

    async def fetch(self, sql, *args):
        self.queries.append(sql)
        return self._regions if "locations" in sql else self._companies


def test_regions_sql_counts_jobs_not_location_pairs():
    # 한 공고가 같은 시/도를 두 번 가져도 1로 세야 한다.
    assert "count(DISTINCT (source, job_id))" in REGIONS_SQL
    assert "regexp_split_to_table" in REGIONS_SQL
    assert "ORDER BY count DESC" in REGIONS_SQL


def test_companies_sql_skips_null_and_sorts():
    assert "company IS NOT NULL" in COMPANIES_SQL
    assert "ORDER BY count DESC" in COMPANIES_SQL


async def test_get_facets_shapes_rows():
    conn = FakeConn(
        regions=[{"name": "서울", "count": 362}],
        companies=[{"name": "미스릴", "count": 3}],
    )
    out = await get_facets(conn)
    assert out == {
        "regions": [{"name": "서울", "count": 362}],
        "companies": [{"name": "미스릴", "count": 3}],
    }


async def test_facets_endpoint(monkeypatch):
    app = FastAPI()
    app.include_router(facets_router.router)

    async def _get_conn():
        yield object()
    app.dependency_overrides[facets_router.get_conn] = _get_conn

    async def fake_get_facets(conn):
        return {"regions": [{"name": "서울", "count": 1}], "companies": []}
    monkeypatch.setattr(facets_router, "get_facets", fake_get_facets)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/facets")
    assert r.status_code == 200
    assert r.json()["regions"][0]["name"] == "서울"
