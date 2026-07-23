import inspect

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app import facets_repo
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


def test_facets_never_reference_settings():
    # /api/facets는 전역 필터의 escape hatch — 숨긴 기업도 보여야 다시 켤 수 있다.
    # get_settings/hidden_companies/allowed_regions를 참조하지 않는지 소스로 못박아,
    # 이후 누가 설정을 끌어들이면 이 테스트가 바로 실패하게 한다.
    banned = ("get_settings", "hidden_companies", "allowed_regions")
    for module in (facets_repo, facets_router):
        src = inspect.getsource(module)
        for name in banned:
            assert name not in src, f"{module.__name__} must not reference {name}"
