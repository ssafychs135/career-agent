import pytest
from fastapi.testclient import TestClient
from app import main
from app.db import get_conn
from app.routers import jobs as jobs_router


def _dummy_conn():
    # get_conn 의존성 대체: 실제 DB 없이 라우팅만 검증. repo는 monkeypatch로 가로챈다.
    yield None


@pytest.fixture(autouse=True)
def override_get_conn():
    # 정본 계약 1·6번: dependency_overrides는 finally에서 clear(전역 오염 금지).
    main.app.dependency_overrides[get_conn] = _dummy_conn
    try:
        yield
    finally:
        main.app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def stub_settings(monkeypatch):
    """conn이 None인 라우팅 테스트라 get_settings를 기본값으로 대체."""
    from app.settings_repo import Settings, SETTINGS_DEFAULTS

    async def fake_get_settings(conn):
        return Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"]))
    monkeypatch.setattr(jobs_router, "get_settings", fake_get_settings)


def test_list_jobs(monkeypatch):
    async def fake_list_jobs(conn, **filters):
        assert filters["keyword"] == "dev"
        assert filters["limit"] == 20 and filters["offset"] == 0
        return {
            "items": [{"source": "saramin", "job_id": "1",
                       "has_company_research": True, "has_job_research": False}],
            "total": 1, "limit": 20, "offset": 0,
        }

    monkeypatch.setattr(jobs_router, "list_jobs", fake_list_jobs)
    r = TestClient(main.app).get("/api/jobs?keyword=dev")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["source"] == "saramin"
    assert body["items"][0]["has_company_research"] is True


def test_list_jobs_limit_validation():
    r = TestClient(main.app).get("/api/jobs?limit=999")
    assert r.status_code == 422


def test_job_detail_found(monkeypatch):
    async def fake_get_job(conn, source, job_id):
        return {
            "job": {"source": source, "job_id": job_id, "company": "Acme"},
            "companyResearch": {"status": "done", "overview": "안정적"},
            "jobResearch": None,
        }

    monkeypatch.setattr(jobs_router, "get_job", fake_get_job)
    r = TestClient(main.app).get("/api/jobs/saramin/1")
    assert r.status_code == 200
    body = r.json()
    assert body["job"]["company"] == "Acme"
    assert body["companyResearch"]["status"] == "done"
    assert body["jobResearch"] is None


def test_job_detail_not_found(monkeypatch):
    async def fake_get_job(conn, source, job_id):
        return None

    monkeypatch.setattr(jobs_router, "get_job", fake_get_job)
    r = TestClient(main.app).get("/api/jobs/x/y")
    assert r.status_code == 404


def test_list_jobs_applies_global_filters(monkeypatch):
    from app.settings_repo import Settings, SETTINGS_DEFAULTS
    seen = {}

    async def fake_get_settings(conn):
        return Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"],
                               allowed_regions=["서울"], hidden_companies=["미스릴"]))
    monkeypatch.setattr(jobs_router, "get_settings", fake_get_settings)

    async def fake_list_jobs(conn, **filters):
        seen.update(filters)
        return {"items": [], "total": 0, "limit": 20, "offset": 0}
    monkeypatch.setattr(jobs_router, "list_jobs", fake_list_jobs)

    r = TestClient(main.app).get("/api/jobs")
    assert r.status_code == 200
    assert seen["allowed_regions"] == ["서울"]
    assert seen["hidden_companies"] == ["미스릴"]


@pytest.mark.parametrize("source,job_id", [
    ("wanted", "00123"), ("jumpit", "123"), ("jump-it", "abc-123_4"),
    ("custom source", "공고 42"), ("wanted", "a?b#c"), ("wanted", "a:b"),
    ("wanted", "a@b+"),
])
def test_detail_single_encoded_segment_roundtrip(monkeypatch, source, job_id):
    """Mirror frontend segment encoding; no real HTTP, DB or upstream calls."""
    from urllib.parse import quote

    async def fake_get_job(conn, actual_source, actual_job_id):
        assert (actual_source, actual_job_id) == (source, job_id)
        return {"job": {"source": actual_source, "job_id": actual_job_id},
                "companyResearch": None, "jobResearch": None}

    monkeypatch.setattr(jobs_router, "get_job", fake_get_job)
    path = f"/api/jobs/{quote(source, safe='')}/{quote(job_id, safe='')}"
    r = TestClient(main.app).get(path)
    assert r.status_code == 200
    assert r.json()["job"] == {"source": source, "job_id": job_id}
