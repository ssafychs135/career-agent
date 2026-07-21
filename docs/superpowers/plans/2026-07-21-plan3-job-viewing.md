# career-agent Plan ③ 공고 조회 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** n8n의 **09 DB 뷰어를 대체**하는 공고 조회 슬라이스를 얹는다. 백엔드에 `GET /api/jobs`(필터·페이지네이션, 리스트 아이템마다 리서치 존재 플래그)와 `GET /api/jobs/{source}/{job_id}`(상세 — **리서치 본문 합본** `{job, companyResearch, jobResearch}`)를 **별도 라우터 파일**로 추가하고, React 프론트에 공고 리스트(필터·페이지네이션)·상세 페이지를 추가한다. 리서치 트리거/본문 열람 UI와 n8n 09 비활성화는 이 플랜 밖(Plan ④·이후) — 다만 **상세 엔드포인트는 리서치 본문 합본의 생산자**이고, Plan ④는 이 형태를 소비만 한다.

**Architecture:** 기존 Walking Skeleton 위에 얹는다. 백엔드는 순수 쿼리빌더(`app/jobs_repo.py`)와 얇은 라우터(`app/routers/jobs.py`)로 분리하고 `main.py`에는 `include_router` **한 줄만** 가산(다른 플랜과 병렬 구현 시 충돌 최소화). DB 접근은 정본 계약대로 Plan ②가 제공하는 `app/db.py`의 **asyncpg** `get_conn` FastAPI 의존성으로 conn을 주입받아 `conn.fetch/fetchrow/fetchval` + 위치 파라미터 `$1`만 쓴다 → 단위 테스트에서는 `dependency_overrides`로 대체(테스트 종료 시 **finally에서 clear**)하므로 라우터/빌더 테스트는 Postgres 없이 돈다. 프론트는 **기존 `src/api.ts`를 확장**(신규 `jobsApi.ts` 금지)해 `getJobs`/`getJob`을 추가하고, 별도 페이지(`src/pages/JobsList.tsx`·`src/pages/JobDetail.tsx`)를 react-router로 라우팅. 기존 상태 화면은 `src/pages/Home.tsx`로 이동하고 `/`에 둔다(기존 `App.test.tsx` 무회귀).

**Tech Stack:** Python 3.12 · FastAPI · asyncpg(Plan ② 제공) · pytest / React 18 · Vite · TypeScript · react-router-dom 6 · vitest / nginx · Docker Compose · Jenkins

## Global Constraints

- 레포 루트: `/Users/sunny/career-agent`. 원격: `ssafychs135/career-agent`(public). 배포: A1(`/home/ubuntu/career-agent`), 기존 Jenkins→`docker compose up -d`→smoke 체인 재사용.
- **커밋 메시지 말미:** `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- 이 플랜은 **git 커밋만** 하고 push/배포는 Task 6(라이브)에서만. 각 태스크 = 실패테스트→확인→구현→통과→커밋.
- **결합 최소화:** 백엔드 신규 코드는 `app/jobs_repo.py`·`app/routers/jobs.py`에만. `app/main.py`는 import 1줄 + `include_router` 1줄만 **가산**(전체 교체 금지). `app/claude_client.py`·`app/db.py`(Plan ②)·기존 라우트는 손대지 않는다. 프론트 jobs 코드는 **기존 `src/api.ts` 확장** + `src/pages/`에만(신규 `jobsApi.ts` 만들지 않음 — 정본 계약 5번).
- **DB 계층 = asyncpg(정본 계약 1번):** 모든 런타임 SQL은 `conn.fetch(...)`·`conn.fetchrow(...)`·`conn.fetchval(...)`와 위치 파라미터(`$1`,`$2`,…)로만 바인딩. SQLAlchemy 런타임 사용 금지. 문자열 보간 금지(ILIKE 패턴의 `%…%`는 값에만).
- **컬럼명(정본 계약 4번):** `jobs`는 `locations`(**TEXT 스칼라**)·`collected_at` 사용. `location`/`created_at` 금지.
- 공개 리포에 개인 취업 결과(회사명·합불) 노출 금지. 실제 데이터는 Postgres에만.

### 선행 조건 계약 (Plan ② / Walking Skeleton) — **반드시 먼저 머지**

이 플랜은 **Plan ②(DB)** 위에서만 임포트가 성립한다. 코드를 시작하기 전에 Plan ②가 다음을 제공해야 한다:

1. **Postgres** 서비스가 `docker-compose.yml`에 있고 career-agent가 소유. n8n init.sql 스키마를 채택한 `jobs` 테이블 + `company_research`·`job_research` 테이블이 마이그레이션(Alembic)으로 존재. `jobs` 컬럼(정본 계약 4번): `source, job_id, company, title, url, min_career, max_career, tech_stacks (text[]), locations (**TEXT 스칼라**), summary, status, attempts, collected_at, updated_at, closed_at, embedding`. `UNIQUE(source, job_id)`.
2. **`backend/app/db.py`** — asyncpg 풀을 앱 lifespan에서 생성(`app.state.db`)하고, 커넥션을 내주는 FastAPI 의존성(정본 계약 1번 시그니처):
   ```python
   # Plan ② 소유. Plan ③는 이 시그니처에만 의존한다(런타임은 asyncpg).
   import asyncpg
   from fastapi import Request

   async def get_conn(request: Request):        # FastAPI dependency
       async with request.app.state.db.acquire() as conn:
           yield conn                           # asyncpg.Connection
   ```
3. **`backend/pyproject.toml`·`backend/Dockerfile`** 에 `asyncpg`가 이미 추가돼 있음(Plan ② 소유). Plan ③는 백엔드 의존성/Dockerfile을 **변경하지 않는다**.

> **컬럼명 정합:** 이 플랜의 SQL은 정본 계약 4번 컬럼명(`locations`·`collected_at`)을 그대로 쓴다. `tech_stacks`만 `text[]`이므로 부분일치 필터는 `CAST(tech_stacks AS text) ILIKE`로 이식성 있게 하고, **`locations`는 TEXT 스칼라라 `locations ILIKE`(CAST 불필요)**. 만약 Plan ②의 실제 스키마가 계약과 다르면 `app/jobs_repo.py`의 SELECT/WHERE만 수정한다(빌더 테스트가 회귀를 잡아준다).
>
> **리서치 테이블 전제:** 상세 엔드포인트는 `company_research`·`job_research`를 LEFT JOIN 하고, 리스트는 두 테이블에 대한 EXISTS 플래그를 계산한다. 이 두 테이블은 채택한 n8n 스키마(Plan ② 마이그레이션)에 이미 존재한다. Plan ④는 여기에 **행을 채워 넣을 뿐** 테이블/응답형태를 바꾸지 않는다(정본 계약 5번: Plan ③가 생산, Plan ④가 소비).
>
> **Plan ② 미머지 상태에서 병렬 착수 시:** `app/db.py`를 Plan ③에서 **만들지 말 것**(소유권 충돌). Task 1(순수 쿼리빌더)은 `app.db` 의존이 없어 단독으로 완주 가능하니 그것부터 진행하고, Task 2~는 Plan ② 머지 후 진행한다.

---

## File Structure

```
career-agent/
├─ backend/
│  ├─ app/
│  │  ├─ jobs_repo.py            # (신규) 순수 쿼리빌더 + list_jobs/get_job 실행(asyncpg)
│  │  ├─ routers/__init__.py     # (신규, 빈 파일)
│  │  ├─ routers/jobs.py         # (신규) GET /api/jobs, GET /api/jobs/{source}/{job_id}
│  │  └─ main.py                 # (가산) include_router 1줄 추가
│  └─ tests/
│     ├─ test_jobs_repo.py       # (신규) 쿼리빌더 단위 테스트(DB 불필요)
│     └─ test_jobs_routes.py     # (신규) 라우터 테스트(repo monkeypatch + get_conn override, finally clear)
├─ frontend/
│  ├─ package.json               # (수정) react-router-dom 추가
│  └─ src/
│     ├─ api.ts                  # (확장) 기존 getHealth/getClaudeCheck에 getJobs/getJob·타입 추가
│     ├─ api.jobs.test.ts        # (신규) getJobs/getJob 테스트
│     ├─ App.tsx                 # (수정) 라우터로 전환(/=Home, /jobs, /jobs/:source/:jobId)
│     └─ pages/
│        ├─ Home.tsx             # (신규) 기존 App 상태화면 이동
│        ├─ JobsList.tsx         # (신규) 리스트·필터·페이지네이션
│        ├─ JobsList.test.tsx    # (신규)
│        ├─ JobDetail.tsx        # (신규) 상세 + 리서치 존재 표시
│        └─ JobDetail.test.tsx   # (신규)
```

각 파일 1책임: `jobs_repo.py`=SQL 생성/실행만, `routers/jobs.py`=HTTP 라우팅/검증만, `api.ts`=HTTP만, 페이지 컴포넌트=표시·상호작용만.

---

## Task 1: 백엔드 jobs 쿼리빌더 (`app/jobs_repo.py`)

**Files:**
- Create: `backend/app/jobs_repo.py`, `backend/tests/test_jobs_repo.py`

**Interfaces:**
- Produces (순수, DB 불필요): `build_list_query(*, status, source, location, tech, keyword, limit, offset) -> tuple[str, list]` — 파라미터화된 SELECT SQL과 위치 인자 리스트를 반환. SELECT는 정본 계약 4·5번 컬럼(`locations`,`collected_at`, …)과 `has_company_research`·`has_job_research` EXISTS 플래그를 포함, `ORDER BY collected_at DESC`.
- Produces (실행, asyncpg): `async def list_jobs(conn, **filters) -> dict` = `{"items": [...], "total": int, "limit": int, "offset": int}`(각 item에 `has_company_research`·`has_job_research`). `async def get_job(conn, source, job_id) -> dict | None` — 정본 계약 5번 형태 `{"job": {...전체 컬럼...}, "companyResearch": {...} | None, "jobResearch": {...} | None}`(company_research·job_research LEFT JOIN 본문).

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_jobs_repo.py`:
```python
from app.jobs_repo import build_list_query


def test_build_query_no_filters():
    sql, params = build_list_query(limit=20, offset=0)
    assert "WHERE" not in sql
    assert "FROM jobs" in sql
    assert "COUNT(*) OVER()" in sql
    assert "has_company_research" in sql
    assert "has_job_research" in sql
    assert "ORDER BY collected_at DESC" in sql
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
    assert "WHERE" not in sql
    assert params == [20, 0]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && python -m pytest tests/test_jobs_repo.py -q`
Expected: FAIL — `ModuleNotFoundError: app.jobs_repo`

- [ ] **Step 3: 구현**

`backend/app/jobs_repo.py`:
```python
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

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    limit_n = len(params)
    params.append(offset)
    offset_n = len(params)
    sql = (
        f"{_SELECT}{where} "
        f"ORDER BY collected_at DESC NULLS LAST "
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
    "  jr.researched_at AS jr_researched_at "
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
        "sources": d["cr_sources"],
        "status": d["cr_status"],
        "researched_at": d["cr_researched_at"],
    }
    job_research = None if d["jr_status"] is None else {
        "tech_detail": d["jr_tech_detail"],
        "role_detail": d["jr_role_detail"],
        "sources": d["jr_sources"],
        "status": d["jr_status"],
        "researched_at": d["jr_researched_at"],
    }
    return {"job": job, "companyResearch": company_research, "jobResearch": job_research}


async def get_job(conn: Any, source: str, job_id: str) -> dict[str, Any] | None:
    row = await conn.fetchrow(_DETAIL_SQL, source, job_id)
    if row is None:
        return None
    return _split_detail(row)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_jobs_repo.py -q`
Expected: PASS (7 passed). `list_jobs`/`get_job`의 실제 DB 실행(asyncpg + LEFT JOIN)은 Task 6(A1 실데이터)에서 검증한다.

- [ ] **Step 5: 커밋**

```bash
cd /Users/sunny/career-agent
git add backend/app/jobs_repo.py backend/tests/test_jobs_repo.py
git commit -m "feat(backend): jobs 쿼리빌더(build_list_query)+list_jobs/get_job(asyncpg)"
```

---

## Task 2: 백엔드 jobs 라우터 (`app/routers/jobs.py`) + main.py mount

**Files:**
- Create: `backend/app/routers/__init__.py`, `backend/app/routers/jobs.py`, `backend/tests/test_jobs_routes.py`
- Modify(가산): `backend/app/main.py` (import 1줄 + include_router 1줄)

**Interfaces:**
- Consumes: `get_conn`(Plan ②의 `app/db.py`, asyncpg 의존성), `list_jobs`·`get_job`(Task 1).
- Produces: `router` (`APIRouter`). `GET /api/jobs?status&source&location&tech&keyword&limit&offset` → `{items,total,limit,offset}`(각 item에 리서치 플래그). `GET /api/jobs/{source}/{job_id}` → `{job, companyResearch, jobResearch}`, 없으면 404. `limit`은 1..100, `offset`≥0(위반 시 422).

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_jobs_routes.py`:
```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && python -m pytest tests/test_jobs_routes.py -q`
Expected: FAIL — `ModuleNotFoundError: app.routers` (또는 `app.db` 부재 시 선행조건 미충족 — 위 "선행 조건 계약" 확인).

- [ ] **Step 3: 구현**

`backend/app/routers/__init__.py`: (빈 파일)

`backend/app/routers/jobs.py`:
```python
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.db import get_conn
from app.jobs_repo import get_job, list_jobs

router = APIRouter(prefix="/api", tags=["jobs"])


@router.get("/jobs")
async def get_jobs(
    status: Optional[str] = None,
    source: Optional[str] = None,
    location: Optional[str] = None,
    tech: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    conn: Any = Depends(get_conn),
):
    return await list_jobs(
        conn,
        status=status,
        source=source,
        location=location,
        tech=tech,
        keyword=keyword,
        limit=limit,
        offset=offset,
    )


@router.get("/jobs/{source}/{job_id}")
async def get_job_detail(source: str, job_id: str, conn: Any = Depends(get_conn)):
    detail = await get_job(conn, source, job_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="job not found")
    return detail
```

`backend/app/main.py` — 아래 2줄만 **가산**(전체 교체 금지, 기존 라우트·claude_check·lifespan 불변):
```python
from app.routers import jobs           # (가산) import
# ... 기존 app = FastAPI(...) 및 라우트들 아래에:
app.include_router(jobs.router)        # (가산) mount 한 줄
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && python -m pytest -q`
Expected: PASS — 기존(claude_client 3 + routes 2) + repo 7 + jobs_routes 4 = 16 passed. 기존 `test_routes.py`가 여전히 통과함을 함께 확인(무회귀).

- [ ] **Step 5: 커밋**

```bash
git add backend/app/routers backend/app/main.py backend/tests/test_jobs_routes.py
git commit -m "feat(backend): /api/jobs 리스트·상세 라우터(main.py mount 1줄 가산)"
```

---

## Task 3: 프론트 jobs API — 기존 `src/api.ts` 확장

**Files:**
- Modify(확장): `frontend/src/api.ts`(기존 `getHealth`/`getClaudeCheck` 불변, 아래 타입·함수 추가)
- Create: `frontend/src/api.jobs.test.ts`

**Interfaces (정본 계약 5번):**
- Produces (in `src/api.ts`): `getJobs(f?: JobsFilters) -> Promise<JobsPage>`(쿼리스트링 빌드, 빈값 제외), `getJob(source, jobId) -> Promise<{ job: Job; companyResearch: CompanyResearch|null; jobResearch: JobResearch|null }>`(비-2xx 시 throw). 타입 `Job`·`JobSummary`·`JobsPage`·`CompanyResearch`·`JobResearch`·`JobDetailResponse` export.

- [ ] **Step 1: 실패하는 테스트 작성**

`frontend/src/api.jobs.test.ts`:
```ts
import { vi, test, expect, beforeEach } from "vitest";
import { getJobs, getJob } from "./api";

beforeEach(() => {
  vi.restoreAllMocks();
});

test("getJobs builds query string and returns page", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ items: [], total: 0, limit: 20, offset: 0 }),
  });
  global.fetch = fetchMock as unknown as typeof fetch;

  const page = await getJobs({ keyword: "dev", status: "open", limit: 20, offset: 0 });
  expect(page.total).toBe(0);
  const url = String(fetchMock.mock.calls[0][0]);
  expect(url).toContain("/api/jobs?");
  expect(url).toContain("keyword=dev");
  expect(url).toContain("status=open");
});

test("getJobs omits empty params", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ items: [], total: 0, limit: 20, offset: 0 }),
  });
  global.fetch = fetchMock as unknown as typeof fetch;

  await getJobs({ status: "", keyword: "dev" });
  const url = String(fetchMock.mock.calls[0][0]);
  expect(url).not.toContain("status=");
  expect(url).toContain("keyword=dev");
});

test("getJob fetches detail endpoint and returns merged shape", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: () =>
      Promise.resolve({
        job: { source: "saramin", job_id: "1", company: "Acme" },
        companyResearch: null,
        jobResearch: null,
      }),
  });
  global.fetch = fetchMock as unknown as typeof fetch;

  const res = await getJob("saramin", "1");
  expect(res.job.source).toBe("saramin");
  expect(res.companyResearch).toBeNull();
  expect(String(fetchMock.mock.calls[0][0])).toBe("/api/jobs/saramin/1");
});

test("getJob throws on 404", async () => {
  global.fetch = vi.fn().mockResolvedValue({ ok: false }) as unknown as typeof fetch;
  await expect(getJob("x", "y")).rejects.toThrow();
});
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd frontend && npm test -- api.jobs`
Expected: FAIL — `getJobs`/`getJob` export 없음.

- [ ] **Step 3: 구현 (기존 `src/api.ts` 하단에 가산 — 기존 두 함수 불변)**

`frontend/src/api.ts`에 아래를 **추가**한다:
```ts
export interface JobSummary {
  source: string;
  job_id: string;
  company: string | null;
  title: string | null;
  url: string | null;
  locations: string | null;
  min_career: number | null;
  max_career: number | null;
  status: string | null;
  collected_at: string | null;
  tech_stacks: string[] | string | null;
  has_company_research: boolean;
  has_job_research: boolean;
}

export interface JobsPage {
  items: JobSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface Job {
  source: string;
  job_id: string;
  company: string | null;
  title: string | null;
  url: string | null;
  locations: string | null;
  min_career: number | null;
  max_career: number | null;
  tech_stacks: string[] | string | null;
  summary: string | null;
  status: string | null;
  attempts: number | null;
  collected_at: string | null;
  updated_at: string | null;
  closed_at: string | null;
}

export interface CompanyResearch {
  overview: string | null;
  stability: string | null;
  sources: unknown;
  status: string;
  researched_at: string | null;
}

export interface JobResearch {
  tech_detail: string | null;
  role_detail: string | null;
  sources: unknown;
  status: string;
  researched_at: string | null;
}

export interface JobDetailResponse {
  job: Job;
  companyResearch: CompanyResearch | null;
  jobResearch: JobResearch | null;
}

export type JobsFilters = Record<string, string | number>;

export async function getJobs(params: JobsFilters = {}): Promise<JobsPage> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== "" && v != null) qs.set(k, String(v));
  }
  const r = await fetch(`/api/jobs?${qs.toString()}`);
  if (!r.ok) throw new Error("jobs 조회 실패");
  return r.json();
}

export async function getJob(source: string, jobId: string): Promise<JobDetailResponse> {
  const r = await fetch(`/api/jobs/${encodeURIComponent(source)}/${encodeURIComponent(jobId)}`);
  if (!r.ok) throw new Error("공고 조회 실패");
  return r.json();
}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd frontend && npm test -- api.jobs`
Expected: PASS (4 passed). 기존 `App.test.tsx`(api.ts의 getHealth/getClaudeCheck 사용)도 무회귀.

- [ ] **Step 5: 커밋**

```bash
git add frontend/src/api.ts frontend/src/api.jobs.test.ts
git commit -m "feat(frontend): api.ts 확장 — getJobs/getJob(리서치 합본 상세)"
```

---

## Task 4: 프론트 라우팅 + 공고 리스트 페이지

**Files:**
- Modify: `frontend/package.json`(react-router-dom 추가), `frontend/src/App.tsx`(라우터로 전환)
- Create: `frontend/src/pages/Home.tsx`(기존 상태화면 이동), `frontend/src/pages/JobsList.tsx`, `frontend/src/pages/JobsList.test.tsx`

**Interfaces:**
- Produces: `/jobs` 라우트의 `JobsList` — 5개 필터 입력(status·source·location·tech·keyword) + "검색" 버튼 + 결과 테이블(각 행은 `/jobs/:source/:job_id` 링크) + 이전/다음 페이지네이션. `getJobs`(Task 3, `src/api.ts`) 소비. 기존 상태화면은 `/`(Home)로 이동해 `App.test.tsx` 무회귀.

- [ ] **Step 1: react-router-dom 설치 + lock 갱신**

```bash
cd /Users/sunny/career-agent/frontend && npm install react-router-dom@^6.28.0
```
Expected: `package.json` dependencies에 `react-router-dom` 추가, `package-lock.json` 갱신(Jenkins `npm ci` 재현성 위해 커밋 대상).

- [ ] **Step 2: 실패하는 테스트 작성**

`frontend/src/pages/JobsList.test.tsx`:
```tsx
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi, test, expect, beforeEach, type Mock } from "vitest";
import JobsList from "./JobsList";
import { getJobs } from "../api";

vi.mock("../api");

beforeEach(() => {
  (getJobs as Mock).mockResolvedValue({
    items: [
      {
        source: "saramin",
        job_id: "1",
        company: "Acme",
        title: "백엔드 개발자",
        url: "http://x",
        locations: "서울, 부산",
        min_career: 0,
        max_career: 3,
        status: "open",
        collected_at: "2026-07-20",
        tech_stacks: ["python"],
        has_company_research: true,
        has_job_research: false,
      },
    ],
    total: 1,
    limit: 20,
    offset: 0,
  });
});

test("renders jobs and links to detail", async () => {
  render(
    <MemoryRouter>
      <JobsList />
    </MemoryRouter>,
  );
  await waitFor(() => expect(screen.getByText("백엔드 개발자")).toBeTruthy());
  const link = screen.getByTestId("job-link") as HTMLAnchorElement;
  expect(link.getAttribute("href")).toBe("/jobs/saramin/1");
  expect(screen.getByTestId("job-total").textContent).toContain("1");
});

test("applies keyword filter on search", async () => {
  render(
    <MemoryRouter>
      <JobsList />
    </MemoryRouter>,
  );
  await waitFor(() => expect(getJobs).toHaveBeenCalled());
  fireEvent.change(screen.getByTestId("filter-keyword"), { target: { value: "backend" } });
  fireEvent.click(screen.getByTestId("search-btn"));
  await waitFor(() =>
    expect(getJobs).toHaveBeenLastCalledWith(expect.objectContaining({ keyword: "backend", offset: 0 })),
  );
});
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `cd frontend && npm test -- JobsList`
Expected: FAIL — `Cannot find module './JobsList'`

- [ ] **Step 4: 구현**

`frontend/src/pages/Home.tsx` (기존 `App.tsx` 본문 이동 — 상태 표시 책임):
```tsx
import { useEffect, useState } from "react";
import { getHealth, getClaudeCheck } from "../api";

export default function Home() {
  const [health, setHealth] = useState("…");
  const [claude, setClaude] = useState("…");

  useEffect(() => {
    getHealth()
      .then((r) => setHealth(r.status))
      .catch(() => setHealth("error"));
    getClaudeCheck()
      .then((r) => setClaude(r.reply))
      .catch(() => setClaude("error"));
  }, []);

  return (
    <main style={{ fontFamily: "sans-serif", padding: 24 }}>
      <h1>career-agent</h1>
      <p>
        API health: <span data-testid="health">{health}</span>
      </p>
      <p>
        claude: <span data-testid="claude">{claude}</span>
      </p>
    </main>
  );
}
```

`frontend/src/App.tsx` (라우터로 전환 — `/`는 Home이라 `App.test.tsx` 그대로 통과):
```tsx
import { BrowserRouter, Routes, Route, Link } from "react-router-dom";
import Home from "./pages/Home";
import JobsList from "./pages/JobsList";
import JobDetail from "./pages/JobDetail";

export default function App() {
  return (
    <BrowserRouter>
      <nav style={{ padding: "8px 24px", borderBottom: "1px solid #ddd", fontFamily: "sans-serif" }}>
        <Link to="/">home</Link> · <Link to="/jobs">공고</Link>
      </nav>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/jobs" element={<JobsList />} />
        <Route path="/jobs/:source/:jobId" element={<JobDetail />} />
      </Routes>
    </BrowserRouter>
  );
}
```

`frontend/src/pages/JobsList.tsx`:
```tsx
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getJobs, type JobSummary } from "../api";

const LIMIT = 20;
const EMPTY = { status: "", source: "", location: "", tech: "", keyword: "" };
type Filters = typeof EMPTY;

export default function JobsList() {
  const [form, setForm] = useState<Filters>(EMPTY);       // 입력 중 값
  const [applied, setApplied] = useState<Filters>(EMPTY); // 확정된 필터
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<JobSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    const params: Record<string, string | number> = { limit: LIMIT, offset };
    for (const [k, v] of Object.entries(applied)) if (v) params[k] = v;
    getJobs(params)
      .then((p) => {
        setItems(p.items);
        setTotal(p.total);
        setError("");
      })
      .catch(() => setError("불러오기 실패"));
  }, [applied, offset]);

  useEffect(() => {
    load();
  }, [load]);

  const onSearch = () => {
    setOffset(0);
    setApplied(form);
  };
  const set = (k: keyof Filters) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [k]: e.target.value });

  return (
    <main style={{ padding: 24, fontFamily: "sans-serif" }}>
      <h1>공고</h1>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
        <input data-testid="filter-status" placeholder="상태" value={form.status} onChange={set("status")} />
        <input data-testid="filter-source" placeholder="소스" value={form.source} onChange={set("source")} />
        <input data-testid="filter-location" placeholder="지역" value={form.location} onChange={set("location")} />
        <input data-testid="filter-tech" placeholder="기술" value={form.tech} onChange={set("tech")} />
        <input data-testid="filter-keyword" placeholder="키워드" value={form.keyword} onChange={set("keyword")} />
        <button data-testid="search-btn" onClick={onSearch}>검색</button>
      </div>
      {error && <p role="alert">{error}</p>}
      <p data-testid="job-total">총 {total}건</p>
      <table style={{ borderCollapse: "collapse", width: "100%" }}>
        <thead>
          <tr>
            <th style={{ textAlign: "left" }}>회사</th>
            <th style={{ textAlign: "left" }}>제목</th>
            <th style={{ textAlign: "left" }}>지역</th>
            <th style={{ textAlign: "left" }}>상태</th>
            <th style={{ textAlign: "left" }}>리서치</th>
          </tr>
        </thead>
        <tbody>
          {items.map((j) => (
            <tr key={`${j.source}:${j.job_id}`}>
              <td>{j.company}</td>
              <td>
                <Link data-testid="job-link" to={`/jobs/${j.source}/${j.job_id}`}>
                  {j.title}
                </Link>
              </td>
              <td>{j.locations}</td>
              <td>{j.status}</td>
              <td>
                {j.has_company_research ? "기업" : "-"} / {j.has_job_research ? "공고" : "-"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ marginTop: 12 }}>
        <button data-testid="prev-btn" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - LIMIT))}>
          이전
        </button>
        <span style={{ margin: "0 8px" }}>{Math.floor(offset / LIMIT) + 1}</span>
        <button data-testid="next-btn" disabled={offset + LIMIT >= total} onClick={() => setOffset(offset + LIMIT)}>
          다음
        </button>
      </div>
    </main>
  );
}
```
*JobsList를 import하는 App은 `./JobDetail`도 import하므로, App.tsx가 타입에러 없이 빌드되도록 이 Step에서 `JobDetail.tsx` 최소 스텁을 함께 만들고 Task 5에서 TDD로 완성한다.*

`frontend/src/pages/JobDetail.tsx` (이 태스크에선 최소 스텁 — Task 5에서 완성):
```tsx
export default function JobDetail() {
  return <main style={{ padding: 24 }}>…</main>;
}
```

- [ ] **Step 5: 테스트·빌드 통과 확인(무회귀 포함)**

Run: `cd frontend && npm test && npm run build`
Expected: 전체 PASS — 기존 `App.test.tsx`(health·claude, `/`=Home) + `api.jobs`(4) + `JobsList`(2) 모두 통과 + `dist/` 빌드 성공.

- [ ] **Step 6: 커밋**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/App.tsx frontend/src/pages
git commit -m "feat(frontend): 라우팅 + 공고 리스트 페이지(필터·페이지네이션)"
```

---

## Task 5: 프론트 공고 상세 페이지 (`src/pages/JobDetail.tsx`)

**Files:**
- Modify: `frontend/src/pages/JobDetail.tsx`(스텁 → 완성)
- Create: `frontend/src/pages/JobDetail.test.tsx`

**Interfaces:**
- Consumes: `getJob`(Task 3, `src/api.ts`) → `{job, companyResearch, jobResearch}`, `useParams`(source·jobId).
- Produces: 공고 상세(제목·회사·지역·상태·요약·원문링크) + **리서치 존재 표시**(companyResearch/jobResearch 가 null인지로 "있음/없음"). 로딩·404 처리. *리서치 본문 열람·트리거 버튼은 Plan ④(상세 응답의 companyResearch/jobResearch 본문을 소비).*

- [ ] **Step 1: 실패하는 테스트 작성**

`frontend/src/pages/JobDetail.test.tsx`:
```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { vi, test, expect, beforeEach, type Mock } from "vitest";
import JobDetail from "./JobDetail";
import { getJob } from "../api";

vi.mock("../api");

beforeEach(() => {
  (getJob as Mock).mockResolvedValue({
    job: {
      source: "saramin",
      job_id: "1",
      company: "Acme",
      title: "백엔드 개발자",
      url: "http://x",
      locations: "서울",
      min_career: 0,
      max_career: 3,
      tech_stacks: ["python"],
      summary: "요약",
      status: "open",
      attempts: 0,
      collected_at: "2026-07-20",
      updated_at: null,
      closed_at: null,
    },
    companyResearch: { status: "done", overview: "안정적", stability: null, sources: null, researched_at: null },
    jobResearch: null,
  });
});

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/jobs/:source/:jobId" element={<JobDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

test("renders detail with research presence", async () => {
  renderAt("/jobs/saramin/1");
  await waitFor(() => expect(screen.getByTestId("job-title").textContent).toBe("백엔드 개발자"));
  expect(screen.getByTestId("job-company").textContent).toBe("Acme");
  expect(screen.getByTestId("research-company").textContent).toContain("있음");
  expect(screen.getByTestId("research-job").textContent).toContain("없음");
  expect(getJob).toHaveBeenCalledWith("saramin", "1");
});

test("shows error when job missing", async () => {
  (getJob as Mock).mockRejectedValue(new Error("404"));
  renderAt("/jobs/x/y");
  await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
});
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd frontend && npm test -- JobDetail`
Expected: FAIL — 스텁이라 `job-title` 등 testid 없음.

- [ ] **Step 3: 구현**

`frontend/src/pages/JobDetail.tsx`:
```tsx
import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { getJob, type JobDetailResponse } from "../api";

export default function JobDetail() {
  const { source, jobId } = useParams();
  const [data, setData] = useState<JobDetailResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!source || !jobId) return;
    getJob(source, jobId)
      .then(setData)
      .catch(() => setError("공고를 찾을 수 없습니다"));
  }, [source, jobId]);

  if (error) {
    return (
      <main style={{ padding: 24, fontFamily: "sans-serif" }}>
        <p role="alert">{error}</p>
        <Link to="/jobs">← 목록</Link>
      </main>
    );
  }
  if (!data) {
    return <main style={{ padding: 24, fontFamily: "sans-serif" }}>불러오는 중…</main>;
  }

  const { job, companyResearch, jobResearch } = data;

  return (
    <main style={{ padding: 24, fontFamily: "sans-serif" }}>
      <Link to="/jobs">← 목록</Link>
      <h1 data-testid="job-title">{job.title}</h1>
      <p data-testid="job-company">{job.company}</p>
      <p>
        {job.locations} · {job.status}
      </p>
      {job.summary && <p>{job.summary}</p>}
      {job.url && (
        <p>
          <a href={job.url} target="_blank" rel="noreferrer">
            원문 보기
          </a>
        </p>
      )}
      <h2>리서치</h2>
      <ul>
        <li data-testid="research-company">기업 리서치: {companyResearch ? "있음" : "없음"}</li>
        <li data-testid="research-job">공고 리서치: {jobResearch ? "있음" : "없음"}</li>
      </ul>
    </main>
  );
}
```

- [ ] **Step 4: 테스트·빌드 통과 확인**

Run: `cd frontend && npm test && npm run build`
Expected: 전체 PASS(App·api.jobs·JobsList·JobDetail) + `dist/` 빌드 성공.

- [ ] **Step 5: 커밋**

```bash
git add frontend/src/pages/JobDetail.tsx frontend/src/pages/JobDetail.test.tsx
git commit -m "feat(frontend): 공고 상세 페이지(리서치 존재 표시)"
```

---

## Task 6: 라이브 검증 (A1 실데이터) — Jenkins 자동배포 + 실공고 조회 ★게이트

**Files:** (코드 변경 없음 — push·배포·검증)

**전제:** Plan ②가 이미 A1에 배포돼 **career-agent Postgres에 실제 `jobs` 데이터가 이전돼 있고**(asyncpg 풀·마이그레이션은 Plan ②의 책임), 백엔드가 그 DB에 붙어 있다. `company_research`·`job_research` 테이블도 스키마에 존재(비어 있어도 LEFT JOIN/EXISTS 안전). 데이터 이전·n8n 재연결 상태는 **controller 확인 필요**.

- [ ] **Step 1: push → Jenkins 자동배포**

```bash
cd /Users/sunny/career-agent && git push origin main
```
Expected: Jenkins가 폴링(≤3분)해 CI(pytest·vitest·compose config) → CD(`up -d --build`) → smoke 통과. Jenkins 빌드 SUCCESS.
```bash
ssh a1 'cd /home/ubuntu/career-agent && git rev-parse --short HEAD'   # push한 커밋과 일치
```

- [ ] **Step 2: 리스트 API 실데이터 검증(리서치 플래그 포함)**

```bash
ssh a1 'curl -s "http://127.0.0.1:80/api/jobs?limit=3" | python3 -c "import sys,json;d=json.load(sys.stdin);i=d[\"items\"][0] if d[\"items\"] else {};print(\"total=\",d[\"total\"],\"n=\",len(d[\"items\"]),\"flags=\",i.get(\"has_company_research\"),i.get(\"has_job_research\"))"'
```
Expected: `total= <N>` (N>0, 이전된 실데이터), `n= <=3`, 각 아이템에 `has_company_research`·`has_job_research`(bool) 존재. total이 0이면 **Plan ②의 데이터 이전 미완료** → controller 에스컬레이트.

- [ ] **Step 3: 필터·페이지네이션 검증**

```bash
# keyword 필터(예: "개발") — 결과 total이 무필터보다 작거나 같아야
ssh a1 'curl -s "http://127.0.0.1:80/api/jobs?keyword=%EA%B0%9C%EB%B0%9C&limit=5" | python3 -c "import sys,json;print(\"kw total=\",json.load(sys.stdin)[\"total\"])"'
# offset 페이지네이션
ssh a1 'curl -s "http://127.0.0.1:80/api/jobs?limit=2&offset=2" | python3 -c "import sys,json;d=json.load(sys.stdin);print(\"offset=\",d[\"offset\"],\"n=\",len(d[\"items\"]))"'
```
Expected: keyword total ≤ 전체 total, offset 응답 정상. *실패 시 흔한 원인: Plan ②의 실제 컬럼명이 계약(`locations`·`collected_at`)과 다름 → `app/jobs_repo.py` SELECT/WHERE 수정.*

- [ ] **Step 4: 상세 API 검증(실제 1건 — 리서치 합본 형태)**

```bash
# 리스트 첫 건의 source/job_id로 상세 조회
ssh a1 'S=$(curl -s "http://127.0.0.1:80/api/jobs?limit=1"); \
  read SRC JID <<<"$(echo "$S" | python3 -c "import sys,json;i=json.load(sys.stdin)[\"items\"][0];print(i[\"source\"],i[\"job_id\"])")"; \
  curl -s "http://127.0.0.1:80/api/jobs/$SRC/$JID" | python3 -c "import sys,json;d=json.load(sys.stdin);print(\"title=\",d[\"job\"][\"title\"],\"company_research=\",d[\"companyResearch\"] is not None,\"job_research=\",d[\"jobResearch\"] is not None)"'
```
Expected: `title= …` + `company_research= False job_research= False`(리서치 행 미존재 시 — Plan ④ 전이므로 정상; 응답 최상위는 `{job, companyResearch, jobResearch}` 형태). 없는 키 조회 시 404:
```bash
ssh a1 'curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:80/api/jobs/nope/nope"'   # 404
```

- [ ] **Step 5: 프론트 E2E(브라우저)**

`https://agent.chs135.com/jobs`(Google Access 로그인 후) → 공고 리스트 렌더·필터 동작·페이지네이션 → 한 건 클릭 → `/jobs/:source/:job_id` 상세 렌더 + 리서치 "없음" 표시 확인.
Expected: 리스트·상세 모두 정상. (스크린샷 근거 첨부 권장.)

- [ ] **Step 6: 완료 확인(커밋 불필요)**

이 태스크는 검증만 — 코드/커밋 없음. Plan ③ 조회 슬라이스가 실데이터로 동작함을 확인.

> **이 플랜 밖(이후 처리):**
> - **n8n 09 워크플로우 비활성화**(active=false): 조회 기능이 09를 완전 대체함을 확인한 뒤 별도로. **controller 확인 필요.**
> - **리서치 트리거/본문 열람 UI**: Plan ④. 상세 엔드포인트는 이미 `companyResearch`·`job_research` 본문을 합본으로 반환(생산자)하므로, Plan ④는 리서치 행을 채우고 그 본문을 **소비·표시**만 하면 된다(상세 응답형태 변경 불필요).
> - **"리서치 완료만" 필터/토글**: 리서치 행 채움에 의존이므로 Plan ④에서 추가.

---

## 완료 기준 (Plan ③ Done)

- `GET /api/jobs`가 필터(status·source·location·tech·keyword)와 페이지네이션(limit≤100·offset)으로 A1 실데이터를 반환하고, **각 아이템에 `has_company_research`·`has_job_research` 플래그**를 포함(정본 계약 5·9번).
- `GET /api/jobs/{source}/{job_id}`가 **`{job, companyResearch, jobResearch}` 합본**(company_research·job_research LEFT JOIN 본문)을 반환(없으면 404) — 이 엔드포인트가 리서치 합본의 생산자.
- 백엔드 DB 접근은 전부 **asyncpg**(`conn.fetch/fetchrow/fetchval` + `$1`), `get_conn`(Plan ②) 의존성 주입, 테스트는 `dependency_overrides`를 finally에서 clear.
- `agent.chs135.com/jobs`에서 리스트·필터·페이지네이션·상세가 브라우저로 동작.
- 백엔드 추가는 `jobs_repo.py`·`routers/jobs.py`에 격리되고 `main.py`는 mount 1줄만 가산(무회귀: 기존 16개 백엔드 테스트 통과). 프론트는 **기존 `src/api.ts` 확장** + 별도 페이지로 추가되고 기존 `App.test.tsx` 통과.
- 리서치 트리거/본문 열람 UI·n8n 09 비활성화는 없음(Plan ④·이후).
</content>
</invoke>
