# 전역 필터(지역·기업) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 공고 목록에 나오기 전에 걸리는 전역 필터 — 지역은 허용목록(이 지역만 표시), 기업은 숨김목록(전체 목록에서 선택 해제) — 을 만든다.

**Architecture:** `app_settings`에 `allowed_regions`/`hidden_companies` 두 배열 컬럼을 추가하고, 목록 쿼리(`build_list_query`)에서 조회 시점에만 적용한다. 필터 UI가 쓸 목록은 전역 필터를 적용하지 않는 `GET /api/facets`로 따로 제공한다(숨긴 기업을 되살리기 위한 escape hatch). 화면은 `/filters` 단일 페이지.

**Tech Stack:** FastAPI + asyncpg + Alembic(백엔드), React 18 + Vite + TypeScript + vitest(프론트).

## Global Constraints

- 적용 시점은 **조회 시점**뿐. 수집기·워커는 건드리지 않는다.
- 지역 = **허용목록**(포함), 기업 = **숨김목록**(제외). 둘 다 **빈 배열이면 해당 절을 아예 붙이지 않는다**(필터 미적용).
- 필터는 **목록 쿼리에만** 적용한다. 공고 상세(`GET /api/jobs/{source}/{job_id}`)는 **수정하지 않는다**.
- `GET /api/facets`는 **전역 필터를 적용하지 않는다**(숨긴 기업도 반환).
- SQL은 전부 `$N` 파라미터. 값 보간 금지.
- 기업 제외는 **정확일치**. `company IS NULL`이면 `NOT (company = ANY(...))`가 NULL이 되어 행이 통째로 빠지므로 `(company IS NULL OR NOT ...)`로 방어한다.
- 지역은 `locations ILIKE '%<지역>%'`를 OR로 결합(정규화된 지역 테이블 없음, 기존 `location` 필터와 동일 방식).
- 설정 저장은 기존 `GET/PUT /api/settings` 재사용. 전용 엔드포인트를 만들지 않는다.
- 파이썬 테스트는 `asyncio_mode=auto` — 평범한 `async def test_...()`, 데코레이터 없음. 실 DB 대신 fake conn.
- 백엔드 테스트: `cd backend && python -m pytest`. 프론트: `cd frontend && npx vitest run`, 타입체크 `npx tsc --noEmit`.

---

### Task 1: 마이그레이션 0005 + Settings 모델 확장

**Files:**
- Create: `backend/migrations/versions/0005_global_filter.py`
- Modify: `backend/app/settings_repo.py` (SETTINGS_DEFAULTS, _COLUMNS, Settings)
- Test: `backend/tests/test_settings_repo.py`

**Interfaces:**
- Produces: `app_settings.allowed_regions text[]`, `app_settings.hidden_companies text[]` (둘 다 `NOT NULL DEFAULT '{}'`); `Settings.allowed_regions: list[str]`, `Settings.hidden_companies: list[str]` (기본 빈 리스트); 두 컬럼이 `_COLUMNS`에 포함되어 UPSERT/SELECT에 자동 반영.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_settings_repo.py` 끝에 추가:

```python
def test_settings_defaults_include_empty_global_filters():
    from app.settings_repo import Settings, SETTINGS_DEFAULTS
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"]))
    assert s.allowed_regions == []
    assert s.hidden_companies == []


def test_upsert_includes_global_filter_columns():
    from app.settings_repo import Settings, SETTINGS_DEFAULTS, build_upsert
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"],
                        allowed_regions=["서울", "경기"], hidden_companies=["미스릴"]))
    sql, params = build_upsert(s)
    assert "allowed_regions" in sql and "hidden_companies" in sql
    assert ["서울", "경기"] in params
    assert ["미스릴"] in params
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && python -m pytest tests/test_settings_repo.py -q`
Expected: FAIL — `Settings` 객체에 `allowed_regions` 속성이 없어 AttributeError/ValidationError.

- [ ] **Step 3: settings_repo.py 확장**

`SETTINGS_DEFAULTS`의 마지막 항목(`discord_webhook_url=""`) 뒤에 추가:

```python
    allowed_regions=[], hidden_companies=[],
```

`_COLUMNS` 리스트 끝에 추가(마지막 줄 `"worker_interval_min", "enabled", "discord_webhook_url",` 뒤):

```python
    "allowed_regions", "hidden_companies",
```

`Settings` 클래스에서 `discord_webhook_url: str = ""` 아래에 추가:

```python
    # 전역 필터 — 빈 배열이면 미적용(지역=전체 표시, 기업=아무것도 숨기지 않음)
    allowed_regions: list[str] = Field(default_factory=list)
    hidden_companies: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_settings_repo.py -q`
Expected: PASS

- [ ] **Step 5: 마이그레이션 작성**

`backend/migrations/versions/0005_global_filter.py`:

```python
"""전역 필터 — allowed_regions / hidden_companies

Revision ID: 0005_global_filter
Revises: 0004_run_log
Create Date: 2026-07-23
"""
from alembic import op

revision = "0005_global_filter"
down_revision = "0004_run_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE app_settings
          ADD COLUMN IF NOT EXISTS allowed_regions  text[] NOT NULL DEFAULT '{}'::text[],
          ADD COLUMN IF NOT EXISTS hidden_companies text[] NOT NULL DEFAULT '{}'::text[];
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE app_settings
          DROP COLUMN IF EXISTS allowed_regions,
          DROP COLUMN IF EXISTS hidden_companies;
        """
    )
```

- [ ] **Step 6: 리비전 체인 검증**

Run: `cd backend && python -m alembic history | head -3`
Expected: `0004_run_log -> 0005_global_filter (head)` 형태로 0005가 head.

- [ ] **Step 7: 전체 백엔드 스위트 확인**

Run: `cd backend && python -m pytest -q`
Expected: 전부 PASS(기존 테스트 회귀 없음).

- [ ] **Step 8: 커밋**

```bash
git add backend/migrations/versions/0005_global_filter.py backend/app/settings_repo.py backend/tests/test_settings_repo.py
git commit -m "feat(filter): app_settings에 전역 필터 컬럼(allowed_regions·hidden_companies) 추가"
```

---

### Task 2: `build_list_query`에 전역 필터 절 추가

**Files:**
- Modify: `backend/app/jobs_repo.py` (`build_list_query`)
- Test: `backend/tests/test_jobs_repo.py`

**Interfaces:**
- Consumes: 없음(순수 함수).
- Produces: `build_list_query(..., allowed_regions: list[str] | None = None, hidden_companies: list[str] | None = None, ...)` — 지역은 `(locations ILIKE $a OR locations ILIKE $b)`, 기업은 `(company IS NULL OR NOT (company = ANY($n::text[])))`. 빈/None이면 절 없음. `list_jobs(conn, **filters)`가 그대로 전달한다(기존 시그니처가 `**filters`라 수정 불필요).

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_jobs_repo.py`의 `test_build_query_ignores_none_and_empty` 뒤에 추가:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && python -m pytest tests/test_jobs_repo.py -q`
Expected: FAIL — `build_list_query() got an unexpected keyword argument 'allowed_regions'`

- [ ] **Step 3: `build_list_query` 확장**

`backend/app/jobs_repo.py`의 시그니처에 두 파라미터를 `keyword` 다음, `limit` 앞에 추가:

```python
    keyword: str | None = None,
    allowed_regions: list[str] | None = None,
    hidden_companies: list[str] | None = None,
    limit: int = 20,
```

`keyword` 처리 블록 바로 뒤(`where = ...` 앞)에 추가:

```python
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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_jobs_repo.py -q`
Expected: PASS (기존 10건 + 신규 4건)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/jobs_repo.py backend/tests/test_jobs_repo.py
git commit -m "feat(filter): 목록 쿼리에 지역 허용·기업 숨김 절 추가"
```

---

### Task 3: `GET /api/jobs`가 설정의 전역 필터를 적용

**Files:**
- Modify: `backend/app/routers/jobs.py`
- Test: `backend/tests/test_jobs_routes.py`

**Interfaces:**
- Consumes: `Settings.allowed_regions` / `Settings.hidden_companies` (Task 1), `build_list_query`의 두 파라미터 (Task 2), `app.settings_repo.get_settings`.
- Produces: `/api/jobs`가 매 요청마다 설정을 읽어 `list_jobs`에 `allowed_regions`/`hidden_companies`를 전달. **상세 엔드포인트는 불변.**

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_jobs_routes.py`의 `override_get_conn` fixture 아래에 fixture를 하나 더 추가한다. **필수** — `_dummy_conn`이 `None`을 yield하므로 실제 `get_settings(None)`은 터진다:

```python
@pytest.fixture(autouse=True)
def stub_settings(monkeypatch):
    """conn이 None인 라우팅 테스트라 get_settings를 기본값으로 대체."""
    from app.settings_repo import Settings, SETTINGS_DEFAULTS

    async def fake_get_settings(conn):
        return Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"]))
    monkeypatch.setattr(jobs_router, "get_settings", fake_get_settings)
```

그리고 파일 끝에 신규 테스트 추가:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && python -m pytest tests/test_jobs_routes.py -q`
Expected: FAIL — `stub_settings` fixture가 `jobs_router.get_settings`를 찾지 못함(AttributeError) 또는 신규 테스트에서 KeyError.

- [ ] **Step 3: 라우터 수정**

`backend/app/routers/jobs.py`의 import에 추가:

```python
from app.settings_repo import get_settings
```

`get_jobs` 본문을 아래로 교체:

```python
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
    # 전역 필터(설정)를 목록에만 적용 — 상세 조회는 영향받지 않는다.
    s = await get_settings(conn)
    return await list_jobs(
        conn,
        status=status,
        source=source,
        location=location,
        tech=tech,
        keyword=keyword,
        allowed_regions=s.allowed_regions,
        hidden_companies=s.hidden_companies,
        limit=limit,
        offset=offset,
    )
```

`get_job_detail`은 **변경하지 않는다.**

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_jobs_routes.py -q`
Expected: PASS (기존 4건 + 신규 1건)

- [ ] **Step 5: 전체 백엔드 확인**

Run: `cd backend && python -m pytest -q`
Expected: 전부 PASS

- [ ] **Step 6: 커밋**

```bash
git add backend/app/routers/jobs.py backend/tests/test_jobs_routes.py
git commit -m "feat(filter): /api/jobs가 설정의 전역 필터를 적용(상세는 불변)"
```

---

### Task 4: `GET /api/facets` — 필터 UI용 지역·기업 목록

**Files:**
- Create: `backend/app/facets_repo.py`
- Create: `backend/app/routers/facets.py`
- Modify: `backend/app/main.py` (라우터 include)
- Test: `backend/tests/test_facets.py`

**Interfaces:**
- Consumes: `app.db.get_conn`.
- Produces: `async get_facets(conn) -> {"regions": [{"name","count"}], "companies": [{"name","count"}]}`, `GET /api/facets`. **전역 필터를 적용하지 않는다.**

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_facets.py`:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && python -m pytest tests/test_facets.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.facets_repo'`

- [ ] **Step 3: `facets_repo.py` 작성**

`backend/app/facets_repo.py`:

```python
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
```

- [ ] **Step 4: 라우터 작성**

`backend/app/routers/facets.py`:

```python
from typing import Any

from fastapi import APIRouter, Depends

from app.db import get_conn
from app.facets_repo import get_facets

router = APIRouter(prefix="/api", tags=["facets"])


@router.get("/facets")
async def read_facets(conn: Any = Depends(get_conn)):
    return await get_facets(conn)
```

- [ ] **Step 5: main.py에 include**

import 블록에 추가:

```python
from app.routers import facets as facets_router
```

`app.include_router(runs_router.router)` 다음 줄에 추가:

```python
app.include_router(facets_router.router)
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_facets.py -q`
Expected: PASS (4건)

- [ ] **Step 7: 커밋**

```bash
git add backend/app/facets_repo.py backend/app/routers/facets.py backend/app/main.py backend/tests/test_facets.py
git commit -m "feat(filter): GET /api/facets — 필터 UI용 지역·기업 목록(전역 필터 미적용)"
```

---

### Task 5: 프론트 API — facets 클라이언트 + Settings 타입 확장

**Files:**
- Create: `frontend/src/filtersApi.ts`
- Modify: `frontend/src/settingsApi.ts` (Settings 인터페이스)
- Test: `frontend/src/filtersApi.test.ts`

**Interfaces:**
- Consumes: `GET /api/facets` (Task 4), `GET/PUT /api/settings`.
- Produces: `interface Facet { name: string; count: number }`, `interface Facets { regions: Facet[]; companies: Facet[] }`, `getFacets(): Promise<Facets>`; `Settings`에 `allowed_regions: string[]`, `hidden_companies: string[]` 추가.

- [ ] **Step 1: 실패하는 테스트 작성**

`frontend/src/filtersApi.test.ts`:

```typescript
import { vi, test, expect, afterEach } from "vitest";
import { getFacets } from "./filtersApi";

afterEach(() => vi.restoreAllMocks());

test("getFacets는 /api/facets를 호출해 목록을 반환한다", async () => {
  const body = {
    regions: [{ name: "서울", count: 362 }],
    companies: [{ name: "미스릴", count: 3 }],
  };
  global.fetch = vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(body) }),
  ) as unknown as typeof fetch;

  const r = await getFacets();
  expect(r.regions[0].name).toBe("서울");
  expect(r.companies[0].count).toBe(3);
  expect((global.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe("/api/facets");
});

test("실패하면 에러를 던진다", async () => {
  global.fetch = vi.fn(() => Promise.resolve({ ok: false })) as unknown as typeof fetch;
  await expect(getFacets()).rejects.toThrow();
});
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd frontend && npx vitest run src/filtersApi.test.ts`
Expected: FAIL — `./filtersApi` 모듈 없음.

- [ ] **Step 3: `filtersApi.ts` 작성**

`frontend/src/filtersApi.ts`:

```typescript
export interface Facet {
  name: string;
  count: number;
}

export interface Facets {
  regions: Facet[];
  companies: Facet[];
}

/** 필터 UI용 목록 — 전역 필터가 적용되지 않아 숨긴 기업도 포함된다. */
export async function getFacets(): Promise<Facets> {
  const r = await fetch("/api/facets");
  if (!r.ok) throw new Error("facets load failed");
  return r.json();
}
```

- [ ] **Step 4: Settings 타입 확장**

`frontend/src/settingsApi.ts`의 `Settings` 인터페이스에서 `discord_webhook_url: string;` 아래에 추가:

```typescript
  allowed_regions: string[];
  hidden_companies: string[];
```

- [ ] **Step 5: 테스트 + 타입체크 확인**

Run: `cd frontend && npx vitest run src/filtersApi.test.ts && npx tsc --noEmit`
Expected: PASS 2건, 타입 에러 0.

- [ ] **Step 6: 커밋**

```bash
git add frontend/src/filtersApi.ts frontend/src/settingsApi.ts frontend/src/filtersApi.test.ts
git commit -m "feat(filter): 프론트 facets 클라이언트 + Settings 타입 확장"
```

---

### Task 6: `/filters` 전역 필터 페이지 + 라우트·rail

**Files:**
- Create: `frontend/src/pages/Filters.tsx`
- Modify: `frontend/src/App.tsx` (라우트 + rail 항목)
- Modify: `frontend/src/index.css` (기업 목록 스타일)
- Test: `frontend/src/pages/Filters.test.tsx`

**Interfaces:**
- Consumes: `getSettings`/`putSettings` + `Settings`(Task 5), `getFacets`/`Facets`(Task 5), 기존 `SPRING_UI`/`stagger`(`../design/springs`).
- Produces: `/filters` 페이지. 지역 체크 = 표시 허용, 기업 체크 = 표시(해제 = 숨김).

- [ ] **Step 1: 실패하는 테스트 작성**

`frontend/src/pages/Filters.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach, afterEach } from "vitest";
import Filters from "./Filters";

const SETTINGS = {
  keywords: ["백엔드"], allowed_wanted_categories: [518], max_career_years: 2,
  max_pages: 9999, collect_hour: 9, batch_size: 20, model: "kanana",
  summary_backend: "local", max_attempts: 5, worker_interval_min: 5,
  enabled: false, discord_webhook_url: "",
  allowed_regions: [] as string[], hidden_companies: [] as string[],
};
const FACETS = {
  regions: [{ name: "서울", count: 362 }, { name: "경기", count: 59 }],
  companies: [{ name: "미스릴", count: 3 }, { name: "토스", count: 2 }],
};

let putBody: Record<string, unknown> | null = null;
function mockFetch() {
  return vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
    const u = String(url);
    let body: unknown = {};
    if (u.includes("/api/facets")) body = FACETS;
    else if (u.includes("/api/settings")) {
      if (init?.method === "PUT") { putBody = JSON.parse(init.body as string); body = putBody; }
      else body = SETTINGS;
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
  });
}

beforeEach(() => { putBody = null; global.fetch = mockFetch() as unknown as typeof fetch; });
afterEach(() => vi.restoreAllMocks());

test("지역·기업 목록을 공고 수와 함께 보여준다", async () => {
  render(<Filters />);
  await waitFor(() => expect(screen.getByLabelText(/서울/)).toBeTruthy());
  expect(screen.getByLabelText(/경기/)).toBeTruthy();
  expect(screen.getByLabelText(/미스릴/)).toBeTruthy();
  expect(screen.getByText(/362/)).toBeTruthy();
});

test("지역을 체크하면 allowed_regions에 담겨 저장된다", async () => {
  render(<Filters />);
  await waitFor(() => expect(screen.getByLabelText(/서울/)).toBeTruthy());
  fireEvent.click(screen.getByLabelText(/서울/));
  fireEvent.click(screen.getByRole("button", { name: "저장" }));
  await waitFor(() => expect(putBody).not.toBeNull());
  expect(putBody!.allowed_regions).toEqual(["서울"]);
});

test("기업 체크를 해제하면 hidden_companies에 담겨 저장된다", async () => {
  render(<Filters />);
  await waitFor(() => expect(screen.getByLabelText(/미스릴/)).toBeTruthy());
  fireEvent.click(screen.getByLabelText(/미스릴/)); // 기본 체크됨 → 해제 = 숨김
  fireEvent.click(screen.getByRole("button", { name: "저장" }));
  await waitFor(() => expect(putBody).not.toBeNull());
  expect(putBody!.hidden_companies).toEqual(["미스릴"]);
});

test("검색으로 기업 목록을 좁힌다", async () => {
  render(<Filters />);
  await waitFor(() => expect(screen.getByLabelText(/미스릴/)).toBeTruthy());
  fireEvent.change(screen.getByLabelText("기업 검색"), { target: { value: "토스" } });
  expect(screen.queryByLabelText(/미스릴/)).toBeNull();
  expect(screen.getByLabelText(/토스/)).toBeTruthy();
});

test("숨김 개수를 요약해 보여준다", async () => {
  render(<Filters />);
  await waitFor(() => expect(screen.getByLabelText(/미스릴/)).toBeTruthy());
  fireEvent.click(screen.getByLabelText(/미스릴/));
  expect(screen.getByText(/2개 중 1개 숨김/)).toBeTruthy();
});
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd frontend && npx vitest run src/pages/Filters.test.tsx`
Expected: FAIL — `./Filters` 모듈 없음.

- [ ] **Step 3: `Filters.tsx` 작성**

`frontend/src/pages/Filters.tsx`:

```tsx
import { useEffect, useMemo, useState } from "react";
import { motion } from "motion/react";
import { getSettings, putSettings, type Settings as S } from "../settingsApi";
import { getFacets, type Facets } from "../filtersApi";
import { SPRING_UI, stagger } from "../design/springs";

/** 전역 필터 — 지역은 허용목록(체크한 지역만 표시), 기업은 숨김목록(해제하면 숨김). */
export default function Filters() {
  const [form, setForm] = useState<S | null>(null);
  const [saved, setSaved] = useState<S | null>(null);
  const [facets, setFacets] = useState<Facets | null>(null);
  const [busy, setBusy] = useState(false);
  const [q, setQ] = useState("");
  const [hiddenFirst, setHiddenFirst] = useState(false);

  useEffect(() => { getSettings().then((s) => { setForm(s); setSaved(s); }); }, []);
  useEffect(() => { getFacets().then(setFacets).catch(() => { /* keep empty */ }); }, []);

  const dirty = !!form && !!saved && JSON.stringify(form) !== JSON.stringify(saved);

  async function save() {
    if (!form) return;
    setBusy(true);
    try {
      const r = await putSettings(form);
      setForm(r);
      setSaved(r);
    } finally {
      setBusy(false);
    }
  }

  const toggleRegion = (name: string) =>
    form && setForm({
      ...form,
      allowed_regions: form.allowed_regions.includes(name)
        ? form.allowed_regions.filter((r) => r !== name)
        : [...form.allowed_regions, name],
    });

  // 체크 = 표시, 해제 = 숨김. 그래서 토글은 hidden_companies에 넣고 빼는 것.
  const toggleCompany = (name: string) =>
    form && setForm({
      ...form,
      hidden_companies: form.hidden_companies.includes(name)
        ? form.hidden_companies.filter((c) => c !== name)
        : [...form.hidden_companies, name],
    });

  const companies = useMemo(() => {
    if (!facets || !form) return [];
    const hidden = new Set(form.hidden_companies);
    const needle = q.trim().toLowerCase();
    const list = facets.companies.filter((c) => c.name.toLowerCase().includes(needle));
    // sort는 안정 정렬 — 백엔드가 준 공고수 내림차순이 그룹 안에서 유지된다.
    return hiddenFirst
      ? [...list].sort((a, b) => Number(hidden.has(b.name)) - Number(hidden.has(a.name)))
      : list;
  }, [facets, form, q, hiddenFirst]);

  const card = (i: number) => ({
    className: "card",
    initial: { opacity: 0, y: 12 },
    animate: { opacity: 1, y: 0 },
    transition: stagger(i),
  });

  return (
    <main className="page">
      <motion.div className="page-head"
        initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={SPRING_UI}>
        <div>
          <h1>전역 필터</h1>
          <p className="sub">공고 목록에 나오기 전에 걸립니다. 숨김은 삭제가 아니라 언제든 되돌릴 수 있습니다.</p>
        </div>
        <button className="btn-primary" onClick={save} disabled={!dirty || busy}>저장</button>
      </motion.div>

      <motion.section {...card(1)}>
        <div className="card-h">지역 · 체크한 지역만 표시</div>
        {!form || !facets ? (
          <p className="caption" style={{ margin: 0 }}>불러오는 중…</p>
        ) : (
          <>
            <p className="caption" style={{ marginTop: 0 }}>
              {form.allowed_regions.length === 0
                ? "선택 없음 — 전체 지역을 표시합니다."
                : `${form.allowed_regions.length}개 지역만 표시 중`}
            </p>
            <div className="chk-grid">
              {facets.regions.map((r) => (
                <label className="chk" key={r.name}>
                  <input type="checkbox" aria-label={`${r.name} (${r.count})`}
                    checked={form.allowed_regions.includes(r.name)}
                    onChange={() => toggleRegion(r.name)} />
                  <span>{r.name}</span>
                  <span className="chk-n">{r.count}</span>
                </label>
              ))}
            </div>
          </>
        )}
      </motion.section>

      <motion.section {...card(2)}>
        <div className="card-h">기업 · 체크 해제하면 숨김</div>
        {!form || !facets ? (
          <p className="caption" style={{ margin: 0 }}>불러오는 중…</p>
        ) : (
          <>
            <div className="run-bar">
              <input className="control" type="search" aria-label="기업 검색" placeholder="기업 검색"
                value={q} onChange={(e) => setQ(e.target.value)} />
              <label className="chk">
                <input type="checkbox" aria-label="숨긴 기업 먼저 보기"
                  checked={hiddenFirst} onChange={(e) => setHiddenFirst(e.target.checked)} />
                <span>숨긴 기업 먼저</span>
              </label>
              <span className="caption">
                {facets.companies.length}개 중 {form.hidden_companies.length}개 숨김
              </span>
            </div>
            <div className="chk-list">
              {companies.map((c) => (
                <label className="chk" key={c.name}>
                  <input type="checkbox" aria-label={`${c.name} (${c.count})`}
                    checked={!form.hidden_companies.includes(c.name)}
                    onChange={() => toggleCompany(c.name)} />
                  <span>{c.name}</span>
                  <span className="chk-n">{c.count}</span>
                </label>
              ))}
            </div>
          </>
        )}
      </motion.section>
    </main>
  );
}
```

- [ ] **Step 4: 라우트 + rail 추가 (App.tsx)**

import에 추가:

```tsx
import Filters from "./pages/Filters";
```

`Rail()`의 운영 NavLink 다음에 추가:

```tsx
      <NavLink to="/filters" title="전역 필터" className={active}>
        ▣
      </NavLink>
```

`<Routes>`의 `/jobs/:source/:jobId` 라우트 다음에 추가:

```tsx
            <Route path="/filters" element={<Filters />} />
```

- [ ] **Step 5: CSS 추가**

`frontend/src/index.css` 끝에 추가:

```css
/* ── 전역 필터 — 체크 목록 ── */
.chk-grid { display: flex; flex-wrap: wrap; gap: 8px 16px; }
.chk-list { display: flex; flex-direction: column; max-height: 420px; overflow-y: auto; }
.chk-list .chk { padding: 7px 2px; border-top: 1px solid var(--glass-edge); }
.chk-list .chk:first-child { border-top: 0; }
.chk {
  display: inline-flex; align-items: center; gap: 8px;
  font-size: 0.9rem; cursor: pointer; user-select: none;
}
.chk input { accent-color: var(--accent); width: 15px; height: 15px; margin: 0; }
.chk-n { color: var(--text-3); font-variant-numeric: tabular-nums; margin-left: auto; }
.chk-list .chk span:nth-of-type(1) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `cd frontend && npx vitest run src/pages/Filters.test.tsx`
Expected: PASS (5건)

- [ ] **Step 7: 전체 프론트 + 타입체크**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: 전부 PASS, 타입 에러 0. (App.test.tsx가 라우팅을 검증한다면 rail 항목 추가로 깨지지 않는지 확인 — 깨지면 그 테스트의 기대값을 새 항목 포함으로 갱신하되 기존 단언은 유지할 것.)

- [ ] **Step 8: 커밋**

```bash
git add frontend/src/pages/Filters.tsx frontend/src/App.tsx frontend/src/index.css frontend/src/pages/Filters.test.tsx
git commit -m "feat(filter): /filters 전역 필터 페이지(지역 허용·기업 숨김)"
```

---

## 최종 검증

- [ ] **백엔드 전체:** `cd backend && python -m pytest -q` → 전부 PASS
- [ ] **프론트 전체:** `cd frontend && npx vitest run && npx tsc --noEmit` → 전부 PASS, 타입 0
- [ ] 배포는 기존 CI/CD가 처리하며 migrate 원샷이 `alembic upgrade head`로 0005를 적용한다.

## 자기 검토 결과

**스펙 커버리지:** 컬럼·모델(T1) · 목록 쿼리 절(T2) · 라우터 적용(T3) · facets API(T4) · 프론트 API(T5) · `/filters` 페이지(T6). 스펙의 모든 항목이 매핑됨. "상세 엔드포인트 미변경"은 T3에서 명시. "facets는 전역 필터 미적용"은 T4 모듈 docstring과 테스트로 고정.

**플레이스홀더:** 없음 — 모든 코드 단계에 실제 코드 포함.

**타입 일관성:** `allowed_regions`/`hidden_companies` 이름이 T1(파이썬)·T2(쿼리 파라미터)·T3(라우터)·T5(TS 인터페이스)·T6(페이지)에서 동일. `Facet{name,count}` 형태가 T4 응답·T5 타입·T6 렌더에서 일치. 빈 배열=미적용 규칙이 T2 구현·T2 테스트·T6 안내 문구에서 동일.
