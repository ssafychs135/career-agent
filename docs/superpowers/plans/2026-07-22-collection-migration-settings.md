# 수집 이관 + 설정 관리 + 라이브 모니터 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** n8n 공고 수집(원티드+점핏) 파이프라인을 career-agent 백엔드로 이관하고, 운영 변수를 DB 기반 설정 페이지에서 관리하며, 세 파이프라인(수집·요약·claude 리서치)의 실행 단계를 실시간 모니터한다.

**Architecture:** FastAPI 프로세스 내 APScheduler에 collector(매일)·worker(주기) 잡을 추가하고, 모두 `app_settings` 싱글턴 행의 `enabled` 플래그로 게이트한다. 실행 중 파이프라인은 인메모리 Activity Registry(`app.state.activity`)에 현재 단계를 게시하고, `claude_client`는 `stream-json`을 파싱해 서브스텝을 `on_step` 콜백으로 흘린다. 프론트는 설정/상태 두 페이지를 폴링으로 소비한다.

**Tech Stack:** Python 3.11, FastAPI, asyncpg, httpx, APScheduler, Pydantic v2, Alembic / React 18 + Vite + TypeScript + vitest + react-router-dom v6 + motion.

## Global Constraints

- 스크레이핑 테스트는 **녹화된 fixture JSON**만 사용 — 라이브 외부 API 호출 금지.
- 키워드 이중역할 보존: **점핏=검색어(query)**, **원티드=제목 필터(`title_hit`, 단어경계 정규식 `(^|[^A-Za-z0-9])kw([^A-Za-z0-9]|$)`, 대소문자 무시)**.
- 수집기 dedup: `INSERT … ON CONFLICT (source, job_id) DO NOTHING` (jobs 테이블에 `UNIQUE (source, job_id)` 이미 존재 — 0001_baseline).
- 워커 배치 점유: `SELECT … FOR UPDATE SKIP LOCKED` 로 `status='processing'` 마킹. 스케줄러 기동 시 stale `processing → pending` 리셋.
- 비밀/인프라는 env 유지: `JOB_PROXY_URL`, `JOB_PROXY_SECRET`, `LLM_BASE_URL`(기본 `http://host.docker.internal:1234`). DB 편집 대상은 운영 손잡이 + `discord_webhook_url`뿐.
- 두 스케줄 잡은 `settings.enabled`로 게이트. **수동 트리거(`/api/collect/run`, `/api/collect/worker/run`)는 `enabled` 무관 실행**(워커 수동도 LLM 헬스게이트는 적용).
- `summary_backend ∈ {'local','claude'}`. `local`=LM Studio `/v1/chat/completions`, `claude`=`run_claude`.
- 시드값(현 n8n): keywords=`SEARCH_KEYWORDS` env 분해, categories=`[518,507]`, max_career_years=`2`, max_pages=`9999`, collect_hour=`9`, batch_size=`20`, model=`kanana-1.5-8b-instruct-2505-mlx`, summary_backend=`local`, max_attempts=`5`, worker_interval_min=`5`, enabled=`false`, discord_webhook_url=`DISCORD_WEBHOOK_URL` env.
- 기존 테스트 스타일 준수: 순수 함수(SQL 빌더/정규화/파서) 단위 테스트 + DI(`runner=`, `http=`, `notify=`)로 부수효과 격리. `pytest asyncio_mode=auto`.
- LLM 요약 시스템 프롬프트(verbatim 보존): `너는 채용공고를 3줄로 요약하고 핵심 자격요건을 뽑는 도우미다. 답변의 맨 마지막 줄에 반드시 '기술스택: 키워드1, 키워드2' 형식으로 공고에 등장한 기술 스택을 쉼표로 구분해 나열하라.`

## 파일 구조

```
backend/app/
├── collect/
│   ├── __init__.py
│   ├── config.py            신규: LLM_BASE_URL, JOB_PROXY_URL/SECRET, SUMMARY_TIMEOUT
│   ├── sources/
│   │   ├── __init__.py
│   │   ├── common.py        신규: strip_tags, title_hit, career_ok
│   │   ├── jumpit.py        신규: parse_jumpit_positions
│   │   └── wanted.py        신규: parse_wanted_results, wanted_list_url
│   ├── collector.py         신규: dedupe, collect (scrape+insert)
│   ├── detail.py            신규: detail_url, parse_detail
│   ├── health.py            신규: llm_healthy
│   ├── summarize.py         신규: summary_system_prompt, extract_stacks, summarize
│   └── worker.py            신규: claim_batch, worker_tick
├── settings_repo.py         신규: Settings 모델, SETTINGS_DEFAULTS, build_upsert, get_settings, put_settings
├── activity.py              신규: Activity Registry
├── claude_client.py         수정: stream-json 파싱 + on_step
├── routers/
│   ├── settings.py          신규: GET/PUT /api/settings
│   ├── collect.py           신규: POST /api/collect/run, /worker/run
│   └── status.py            신규: GET /api/status
├── collect_scheduler.py     신규: collector·worker 잡 등록 + reschedule (research/scheduler.py 미러)
└── main.py                  수정: 라우터 등록 + collect_scheduler 훅 + activity 초기화

backend/migrations/versions/0003_app_settings.py   신규

frontend/src/
├── settingsApi.ts           신규
├── statusApi.ts             신규
├── components/ChipInput.tsx 신규
├── components/Segmented.tsx 신규
├── pages/Settings.tsx       신규
├── pages/Status.tsx         신규
└── App.tsx                  수정: /settings, /status 라우트 + 내비
```

---

# Phase 1 — 설정 기반

### Task 1: 설정 모델 + 저장소 + 마이그레이션

**Files:**
- Create: `backend/app/settings_repo.py`
- Create: `backend/migrations/versions/0003_app_settings.py`
- Test: `backend/tests/test_settings_repo.py`

**Interfaces:**
- Produces:
  - `class Settings(BaseModel)` — 필드: `keywords: list[str]`, `allowed_wanted_categories: list[int]`, `max_career_years: int`, `max_pages: int`, `collect_hour: int`, `batch_size: int`, `model: str`, `summary_backend: Literal['local','claude']`, `max_attempts: int`, `worker_interval_min: int`, `enabled: bool`, `discord_webhook_url: str`, `updated_at: datetime | None = None`
  - `SETTINGS_DEFAULTS: dict`
  - `build_upsert(s: Settings) -> tuple[str, list]`
  - `async get_settings(conn) -> Settings`
  - `async put_settings(conn, s: Settings) -> Settings`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_settings_repo.py
import pytest
from pydantic import ValidationError
from app.settings_repo import Settings, SETTINGS_DEFAULTS, build_upsert


def _valid(**over):
    base = dict(
        keywords=["백엔드", "데이터 엔지니어"], allowed_wanted_categories=[518, 507],
        max_career_years=2, max_pages=9999, collect_hour=9, batch_size=20,
        model="kanana-1.5-8b-instruct-2505-mlx", summary_backend="local",
        max_attempts=5, worker_interval_min=5, enabled=False, discord_webhook_url="",
    )
    base.update(over)
    return base


def test_defaults_are_valid():
    Settings(**SETTINGS_DEFAULTS)  # 검증 통과


def test_keywords_trimmed_and_nonempty():
    s = Settings(**_valid(keywords=["  백엔드 ", "", "  "]))
    assert s.keywords == ["백엔드"]


def test_keywords_all_empty_rejected():
    with pytest.raises(ValidationError):
        Settings(**_valid(keywords=["", "   "]))


def test_collect_hour_range():
    with pytest.raises(ValidationError):
        Settings(**_valid(collect_hour=24))


def test_summary_backend_enum():
    with pytest.raises(ValidationError):
        Settings(**_valid(summary_backend="gpt"))


def test_batch_size_bounds():
    with pytest.raises(ValidationError):
        Settings(**_valid(batch_size=0))
    with pytest.raises(ValidationError):
        Settings(**_valid(batch_size=101))


def test_build_upsert_is_singleton_and_parameterized():
    sql, params = build_upsert(Settings(**_valid(keywords=["x"])))
    assert "INSERT INTO app_settings" in sql
    assert "id" in sql and "ON CONFLICT (id) DO UPDATE SET" in sql
    assert "$1" in sql and "$12" in sql  # 12개 편집 컬럼
    assert params[0] == ["x"]            # keywords 배열 그대로(asyncpg text[])
    assert params[1] == [518, 507]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_settings_repo.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.settings_repo'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/settings_repo.py
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

SETTINGS_DEFAULTS = dict(
    keywords=[], allowed_wanted_categories=[518, 507], max_career_years=2,
    max_pages=9999, collect_hour=9, batch_size=20,
    model="kanana-1.5-8b-instruct-2505-mlx", summary_backend="local",
    max_attempts=5, worker_interval_min=5, enabled=False, discord_webhook_url="",
)

# UPSERT 컬럼 순서(단일 소스 오브 트루스). updated_at은 now()로 별도 처리.
_COLUMNS = [
    "keywords", "allowed_wanted_categories", "max_career_years", "max_pages",
    "collect_hour", "batch_size", "model", "summary_backend", "max_attempts",
    "worker_interval_min", "enabled", "discord_webhook_url",
]


class Settings(BaseModel):
    keywords: list[str]
    allowed_wanted_categories: list[int]
    max_career_years: int = Field(ge=0)
    max_pages: int = Field(ge=1)
    collect_hour: int = Field(ge=0, le=23)
    batch_size: int = Field(ge=1, le=100)
    model: str = Field(min_length=1)
    summary_backend: Literal["local", "claude"]
    max_attempts: int = Field(ge=1, le=20)
    worker_interval_min: int = Field(ge=1)
    enabled: bool
    discord_webhook_url: str = ""
    updated_at: Optional[datetime] = None

    @field_validator("keywords")
    @classmethod
    def _clean_keywords(cls, v: list[str]) -> list[str]:
        cleaned = [k.strip() for k in v if k and k.strip()]
        if not cleaned:
            raise ValueError("keywords must have at least one non-empty value")
        return cleaned


def build_upsert(s: Settings) -> tuple[str, list]:
    """싱글턴(id=1) UPSERT. 편집 컬럼만 파라미터화, updated_at=now()."""
    cols = ", ".join(_COLUMNS)
    placeholders = ", ".join(f"${i}" for i in range(1, len(_COLUMNS) + 1))
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in _COLUMNS)
    sql = (
        f"INSERT INTO app_settings (id, {cols}, updated_at) "
        f"VALUES (1, {placeholders}, now()) "
        f"ON CONFLICT (id) DO UPDATE SET {updates}, updated_at = now() "
        f"RETURNING {cols}, updated_at"
    )
    params = [getattr(s, c) for c in _COLUMNS]
    return sql, params


async def get_settings(conn) -> Settings:
    row = await conn.fetchrow(
        f"SELECT {', '.join(_COLUMNS)}, updated_at FROM app_settings WHERE id = 1"
    )
    if row is None:
        return Settings(**SETTINGS_DEFAULTS)
    return Settings(**dict(row))


async def put_settings(conn, s: Settings) -> Settings:
    sql, params = build_upsert(s)
    row = await conn.fetchrow(sql, *params)
    return Settings(**dict(row))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_settings_repo.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Write the migration**

```python
# backend/migrations/versions/0003_app_settings.py
"""app_settings 싱글턴 + env 시드

Revision ID: 0003_app_settings
Revises: 0002_research
Create Date: 2026-07-22
"""
import os

from alembic import op

revision = "0003_app_settings"
down_revision = "0002_research"
branch_labels = None
depends_on = None


def _pg_text_array(items: list[str]) -> str:
    inner = ", ".join("'" + s.replace("'", "''") + "'" for s in items)
    return "ARRAY[" + inner + "]::text[]" if items else "'{}'::text[]"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
          id                        int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
          keywords                  text[]  NOT NULL,
          allowed_wanted_categories int[]   NOT NULL,
          max_career_years          int     NOT NULL,
          max_pages                 int     NOT NULL,
          collect_hour              int     NOT NULL,
          batch_size                int     NOT NULL,
          model                     text    NOT NULL,
          summary_backend           text    NOT NULL CHECK (summary_backend IN ('local','claude')),
          max_attempts              int     NOT NULL,
          worker_interval_min       int     NOT NULL,
          enabled                   boolean NOT NULL DEFAULT false,
          discord_webhook_url       text    NOT NULL DEFAULT '',
          updated_at                timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    keywords = [k.strip() for k in os.environ.get("SEARCH_KEYWORDS", "").split(",") if k.strip()]
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").replace("'", "''")
    op.execute(
        f"""
        INSERT INTO app_settings
          (id, keywords, allowed_wanted_categories, max_career_years, max_pages,
           collect_hour, batch_size, model, summary_backend, max_attempts,
           worker_interval_min, enabled, discord_webhook_url)
        VALUES
          (1, {_pg_text_array(keywords)}, ARRAY[518,507]::int[], 2, 9999,
           9, 20, 'kanana-1.5-8b-instruct-2505-mlx', 'local', 5,
           5, false, '{webhook}')
        ON CONFLICT (id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app_settings;")
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/settings_repo.py backend/migrations/versions/0003_app_settings.py backend/tests/test_settings_repo.py
git commit -m "feat(settings): app_settings 싱글턴 모델·저장소·마이그레이션"
```

---

### Task 2: 설정 라우터 (GET/PUT)

**Files:**
- Create: `backend/app/routers/settings.py`
- Modify: `backend/app/main.py` (라우터 등록)
- Test: `backend/tests/test_settings_router.py`

**Interfaces:**
- Consumes: `Settings`, `get_settings`, `put_settings` (Task 1)
- Produces: `GET /api/settings -> Settings`, `PUT /api/settings` (body `Settings`) `-> Settings`. PUT는 `app.state.reschedule_pipelines`(있으면) 호출 — Task 8이 채우는 훅.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_settings_router.py
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from app.routers import settings as settings_router
from app.settings_repo import Settings, SETTINGS_DEFAULTS


class FakeConn:
    def __init__(self, store): self.store = store
    async def fetchrow(self, sql, *params):
        if "INSERT" in sql:
            self.store["saved"] = params
        return None  # get은 기본값 경로


def _app(conn):
    app = FastAPI()
    app.include_router(settings_router.router)

    async def _get_conn():
        yield conn
    app.dependency_overrides[settings_router.get_conn] = _get_conn
    return app


async def test_get_returns_defaults_when_no_row():
    app = _app(FakeConn({}))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/settings")
    assert r.status_code == 200
    assert r.json()["batch_size"] == 20


async def test_put_validates_and_saves():
    store = {}
    app = _app(FakeConn(store))
    body = dict(SETTINGS_DEFAULTS, keywords=["백엔드"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.put("/api/settings", json=body)
    assert r.status_code == 200
    assert store["saved"][0] == ["백엔드"]


async def test_put_rejects_invalid():
    app = _app(FakeConn({}))
    body = dict(SETTINGS_DEFAULTS, keywords=["백엔드"], collect_hour=99)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.put("/api/settings", json=body)
    assert r.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_settings_router.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.routers.settings'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/routers/settings.py
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.db import get_conn
from app.settings_repo import Settings, get_settings, put_settings

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings", response_model=Settings)
async def read_settings(conn: Any = Depends(get_conn)):
    return await get_settings(conn)


@router.put("/settings", response_model=Settings)
async def write_settings(body: Settings, request: Request, conn: Any = Depends(get_conn)):
    saved = await put_settings(conn, body)
    reschedule = getattr(request.app.state, "reschedule_pipelines", None)
    if reschedule is not None:
        reschedule(saved)  # collect_hour/worker_interval 변경 즉시 반영 (Task 8)
    return saved
```

- [ ] **Step 4: Register the router**

In `backend/app/main.py`, add import and `include_router`:

```python
from app.routers import settings as settings_router  # 기존 import 블록에 추가
```
```python
app.include_router(settings_router.router)  # 기존 include_router 라인들 아래
```

- [ ] **Step 5: Run tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_settings_router.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/settings.py backend/app/main.py backend/tests/test_settings_router.py
git commit -m "feat(settings): GET/PUT /api/settings 라우터 + reschedule 훅 시임"
```

---

# Phase 2 — 수집 파이프라인 (백엔드)

### Task 3: 소스 파서 (원티드·점핏, 순수 함수)

**Files:**
- Create: `backend/app/collect/__init__.py` (빈 파일)
- Create: `backend/app/collect/config.py`
- Create: `backend/app/collect/sources/__init__.py` (빈 파일)
- Create: `backend/app/collect/sources/common.py`
- Create: `backend/app/collect/sources/jumpit.py`
- Create: `backend/app/collect/sources/wanted.py`
- Test: `backend/tests/test_collect_sources.py`

**Interfaces:**
- Produces:
  - `strip_tags(s) -> str`, `title_hit(title, keywords) -> bool`, `career_ok(min_career, max_years) -> bool` (common.py)
  - `parse_jumpit_positions(payload: dict, keywords, max_years) -> list[dict]` (jumpit.py)
  - `wanted_list_url(cat, offset) -> str`, `parse_wanted_results(payload, cats, keywords, max_years) -> list[dict]` (wanted.py)
  - 정규화 dict 키: `source, job_id, company, title, url, min_career, max_career, tech_stacks(list[str]), locations(str), closed_at`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_collect_sources.py
from app.collect.sources.common import title_hit, career_ok, strip_tags
from app.collect.sources.jumpit import parse_jumpit_positions
from app.collect.sources.wanted import parse_wanted_results, wanted_list_url


def test_title_hit_word_boundary():
    assert title_hit("백엔드 개발자", ["백엔드"]) is True
    assert title_hit("백엔드개발자", ["백엔드"]) is False   # 단어경계 없음
    assert title_hit("Backend Engineer", ["backend"]) is True  # 대소문자 무시


def test_career_ok():
    assert career_ok(1, 2) is True
    assert career_ok(3, 2) is False
    assert career_ok(None, 2) is True          # min 없음 → 통과
    assert career_ok(5, float("nan")) is True   # max 없음 → 통과


def test_strip_tags():
    assert strip_tags("<b>Py</b>thon ") == "Python"


def test_parse_jumpit_filters_and_normalizes():
    payload = {"result": {"positions": [
        {"id": 1, "title": "백엔드 개발자", "companyName": "A", "minCareer": 1,
         "maxCareer": 3, "techStacks": ["Python", {"stack": "Django"}], "locations": ["서울"]},
        {"id": 2, "title": "프론트 개발자", "companyName": "B", "minCareer": 0},  # 키워드 불일치
        {"id": 3, "title": "백엔드 시니어", "companyName": "C", "minCareer": 5},  # 연차 초과
    ]}}
    out = parse_jumpit_positions(payload, ["백엔드"], 2)
    assert len(out) == 1
    r = out[0]
    assert r["source"] == "jumpit" and r["job_id"] == "1" and r["company"] == "A"
    assert r["url"] == "https://jumpit.saramin.co.kr/position/1"
    assert r["tech_stacks"] == ["Python", "Django"]
    assert r["locations"] == "서울"


def test_parse_wanted_filters_by_category_and_title():
    payload = {"data": [
        {"id": 10, "position": "백엔드 엔지니어", "company": {"name": "W"},
         "annual_from": 1, "annual_to": 3, "skill_tags": [{"title": "Go"}],
         "category_tag": {"parent_id": 518},
         "address": {"location": "서울", "district": "강남구"}, "due_time": None},
        {"id": 11, "position": "백엔드 엔지니어", "company": {"name": "X"},
         "annual_from": 0, "category_tag": {"parent_id": 999}},  # 카테고리 제외
    ]}
    out = parse_wanted_results(payload, [518, 507], ["백엔드"], 2)
    assert len(out) == 1
    r = out[0]
    assert r["source"] == "wanted" and r["job_id"] == "10"
    assert r["url"] == "https://www.wanted.co.kr/wd/10"
    assert r["tech_stacks"] == ["Go"]
    assert r["locations"] == "서울 강남구"


def test_wanted_list_url_offset():
    url = wanted_list_url(518, 40)
    assert "job_group_id=518" in url and "offset=40" in url and "limit=20" in url
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_collect_sources.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.collect'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/collect/config.py
import os

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://host.docker.internal:1234")
JOB_PROXY_URL = os.environ.get("JOB_PROXY_URL", "")
JOB_PROXY_SECRET = os.environ.get("JOB_PROXY_SECRET", "")
SUMMARY_TIMEOUT = int(os.environ.get("SUMMARY_TIMEOUT", "120"))
DETAIL_TIMEOUT = int(os.environ.get("DETAIL_TIMEOUT", "20"))
```

```python
# backend/app/collect/sources/common.py
import math
import re

_TAG = re.compile(r"<[^>]*>")


def strip_tags(s) -> str:
    return _TAG.sub("", s or "").strip()


def title_hit(title: str, keywords) -> bool:
    t = title or ""
    for kw in keywords:
        pat = r"(^|[^A-Za-z0-9])" + re.escape(kw) + r"([^A-Za-z0-9]|$)"
        if re.search(pat, t, re.IGNORECASE):
            return True
    return False


def career_ok(min_career, max_years) -> bool:
    if max_years is None or (isinstance(max_years, float) and math.isnan(max_years)):
        return True
    if min_career is None:
        return True
    return min_career <= max_years


def _stack_name(t) -> str:
    if isinstance(t, str):
        return strip_tags(t)
    return strip_tags(t.get("stack") or t.get("name") or t.get("title") or "")
```

```python
# backend/app/collect/sources/jumpit.py
from app.collect.sources.common import _stack_name, career_ok, strip_tags, title_hit


def parse_jumpit_positions(payload: dict, keywords, max_years) -> list[dict]:
    positions = (payload or {}).get("result", {}).get("positions", []) or []
    out = []
    for p in positions:
        title = strip_tags(p.get("title"))
        min_career = p.get("minCareer")
        if not title_hit(title, keywords) or not career_ok(min_career, max_years):
            continue
        locs = p.get("locations") or []
        out.append({
            "source": "jumpit", "job_id": str(p.get("id") or ""),
            "company": p.get("companyName") or "", "title": title,
            "url": f"https://jumpit.saramin.co.kr/position/{p.get('id')}",
            "min_career": min_career, "max_career": p.get("maxCareer"),
            "tech_stacks": [_stack_name(t) for t in (p.get("techStacks") or [])],
            "locations": ", ".join(locs) if isinstance(locs, list) else str(locs or ""),
            "closed_at": p.get("closedAt"),
        })
    return out
```

```python
# backend/app/collect/sources/wanted.py
from app.collect.sources.common import _stack_name, career_ok, title_hit


def wanted_list_url(cat: int, offset: int) -> str:
    return (
        "https://www.wanted.co.kr/api/chaos/navigation/v1/results"
        f"?job_group_id={cat}&country=kr&job_sort=job.latest_order"
        f"&locations=all&years=-1&limit=20&offset={offset}"
    )


def parse_wanted_results(payload: dict, cats, keywords, max_years) -> list[dict]:
    data = (payload or {}).get("data", []) or []
    out = []
    for p in data:
        parent = (p.get("category_tag") or {}).get("parent_id")
        if cats and parent is not None and parent not in cats:
            continue
        title = p.get("position") or ""
        min_career = p.get("annual_from")
        max_career = p.get("annual_to")
        if max_career is not None and max_career > 20:
            max_career = None
        if not title_hit(title, keywords) or not career_ok(min_career, max_years):
            continue
        addr = p.get("address") or {}
        loc = " ".join(x for x in [addr.get("location"), addr.get("district")] if x)
        out.append({
            "source": "wanted", "job_id": str(p.get("id") or ""),
            "company": (p.get("company") or {}).get("name") or "", "title": title,
            "url": f"https://www.wanted.co.kr/wd/{p.get('id')}",
            "min_career": min_career, "max_career": max_career,
            "tech_stacks": [_stack_name(t) for t in (p.get("skill_tags") or [])],
            "locations": loc, "closed_at": p.get("due_time"),
        })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_collect_sources.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/collect/ backend/tests/test_collect_sources.py
git commit -m "feat(collect): 원티드·점핏 소스 파서(순수) + 키워드 이중역할 보존"
```

---

### Task 4: 수집기 (스크레이프 + dedup + INSERT)

**Files:**
- Create: `backend/app/collect/collector.py`
- Test: `backend/tests/test_collector.py`

**Interfaces:**
- Consumes: `parse_jumpit_positions`, `parse_wanted_results`, `wanted_list_url` (Task 3); `Settings` (Task 1); `config.JOB_PROXY_URL/SECRET`
- Produces:
  - `dedupe(rows: list[dict]) -> list[dict]` — `(source, job_id)` 최초만.
  - `INSERT_SQL: str` — 파라미터화된 단건 INSERT(`ON CONFLICT DO NOTHING`).
  - `async collect(conn, settings: Settings, *, http, on_stage=None) -> dict` — `{"scraped": n, "inserted": m}`. `http`는 `.get(url, headers=...) -> resp(.json())` 를 가진 객체(httpx.AsyncClient 또는 페이크).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_collector.py
from app.collect.collector import dedupe, collect, INSERT_SQL
from app.settings_repo import Settings, SETTINGS_DEFAULTS


def test_dedupe_keeps_first():
    rows = [
        {"source": "wanted", "job_id": "1", "title": "a"},
        {"source": "wanted", "job_id": "1", "title": "dup"},
        {"source": "jumpit", "job_id": "1", "title": "b"},
    ]
    out = dedupe(rows)
    assert [r["job_id"] + r["source"] for r in out] == ["1wanted", "1jumpit"]


def test_insert_sql_is_on_conflict_do_nothing():
    assert "INSERT INTO jobs" in INSERT_SQL
    assert "ON CONFLICT (source, job_id) DO NOTHING" in INSERT_SQL


class FakeResp:
    def __init__(self, payload): self._p = payload
    def json(self): return self._p
    def raise_for_status(self): pass


class FakeHttp:
    """점핏 page1에 1건, 원티드 page1에 1건, 이후 빈 페이지."""
    def __init__(self):
        self.calls = []

    async def get(self, url, headers=None):
        self.calls.append(url)
        if "jumpit-api" in url and "page=1" in url:
            return FakeResp({"result": {"positions": [
                {"id": 1, "title": "백엔드 개발자", "companyName": "A", "minCareer": 1}]}})
        if "navigation/v1/results" in url and "offset=0" in url:
            return FakeResp({"data": [
                {"id": 10, "position": "백엔드 엔지니어", "company": {"name": "W"},
                 "annual_from": 1, "category_tag": {"parent_id": 518}}]})
        return FakeResp({"result": {"positions": []}, "data": []})  # 빈 페이지 → 종료


class FakeConn:
    def __init__(self): self.executed = []
    async def executemany(self, sql, args): self.executed.append((sql, args))


async def test_collect_scrapes_and_inserts():
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["백엔드"], max_pages=3))
    conn, http = FakeConn(), FakeHttp()
    result = await collect(conn, s, http=http)
    assert result == {"scraped": 2, "inserted": 2}
    assert conn.executed[0][0] == INSERT_SQL
    assert len(conn.executed[0][1]) == 2  # 2행 executemany
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_collector.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.collect.collector'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/collect/collector.py
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
```

> 참고: `inserted`는 dedup 후 시도 건수. `ON CONFLICT DO NOTHING`으로 실제 신규는 이보다 적을 수 있으나, executemany는 개별 rowcount를 주지 않으므로 "시도 건수"로 보고한다(스펙의 카운트 정의와 일치).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_collector.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/collect/collector.py backend/tests/test_collector.py
git commit -m "feat(collect): 수집기 스크레이프+dedup+ON CONFLICT INSERT"
```

---

### Task 5: LLM 헬스 + 요약(local|claude 스위치)

**Files:**
- Create: `backend/app/collect/health.py`
- Create: `backend/app/collect/summarize.py`
- Test: `backend/tests/test_collect_summarize.py`

**Interfaces:**
- Consumes: `config.LLM_BASE_URL, SUMMARY_TIMEOUT`; `run_claude` (기존)
- Produces:
  - `async llm_healthy(http, base_url=LLM_BASE_URL) -> bool`
  - `SUMMARY_SYSTEM_PROMPT: str`
  - `extract_stacks(content: str) -> list[str]`
  - `async summarize(prompt, settings, *, http, runner=run_claude, on_step=None) -> str | None` — 요약 텍스트 또는 None(빈 응답).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_collect_summarize.py
import pytest
from app.collect.health import llm_healthy
from app.collect.summarize import summarize, extract_stacks, SUMMARY_SYSTEM_PROMPT
from app.settings_repo import Settings, SETTINGS_DEFAULTS


class Resp:
    def __init__(self, code=200, payload=None): self.status_code = code; self._p = payload
    def json(self): return self._p


class Http:
    def __init__(self, get_resp=None, post_resp=None): self._g, self._p = get_resp, post_resp; self.posted = None
    async def get(self, url, timeout=None): return self._g
    async def post(self, url, json=None, timeout=None): self.posted = json; return self._p


async def test_llm_healthy_true_on_200():
    assert await llm_healthy(Http(get_resp=Resp(200)), "http://x") is True


async def test_llm_healthy_false_on_error():
    class Boom:
        async def get(self, url, timeout=None): raise RuntimeError("down")
    assert await llm_healthy(Boom(), "http://x") is False


def test_extract_stacks():
    assert extract_stacks("요약...\n기술스택: Python, Django·FastAPI") == ["Python", "Django", "FastAPI"]
    assert extract_stacks("스택 언급 없음") == []


async def test_summarize_local_calls_lmstudio():
    http = Http(post_resp=Resp(200, {"choices": [{"message": {"content": "3줄 요약"}}]}))
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], summary_backend="local"))
    out = await summarize("공고 프롬프트", s, http=http)
    assert out == "3줄 요약"
    assert http.posted["model"] == s.model
    assert http.posted["messages"][0]["content"] == SUMMARY_SYSTEM_PROMPT


async def test_summarize_claude_uses_runner():
    calls = {}
    async def fake_runner(prompt, *, on_step=None, **kw): calls["prompt"] = prompt; return "클로드 요약"
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], summary_backend="claude"))
    out = await summarize("공고 프롬프트", s, http=Http(), runner=fake_runner)
    assert out == "클로드 요약"
    assert "공고 프롬프트" in calls["prompt"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_collect_summarize.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.collect.health'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/collect/health.py
from app.collect.config import LLM_BASE_URL


async def llm_healthy(http, base_url: str = LLM_BASE_URL) -> bool:
    try:
        r = await http.get(f"{base_url}/v1/models", timeout=5)
        return r.status_code == 200
    except Exception:  # noqa: BLE001 — 어떤 실패든 down으로 간주
        return False
```

```python
# backend/app/collect/summarize.py
import re

from app.claude_client import run_claude
from app.collect.config import LLM_BASE_URL, SUMMARY_TIMEOUT

SUMMARY_SYSTEM_PROMPT = (
    "너는 채용공고를 3줄로 요약하고 핵심 자격요건을 뽑는 도우미다. "
    "답변의 맨 마지막 줄에 반드시 '기술스택: 키워드1, 키워드2' 형식으로 "
    "공고에 등장한 기술 스택을 쉼표로 구분해 나열하라."
)

_STACK_RE = re.compile(r"기술스택\s*[:：]\s*(.+)")


def extract_stacks(content: str) -> list[str]:
    m = _STACK_RE.search(content or "")
    if not m:
        return []
    return [s.strip() for s in re.split(r"[,·]", m.group(1)) if s.strip()]


async def summarize(prompt, settings, *, http, runner=run_claude, on_step=None) -> str | None:
    if settings.summary_backend == "claude":
        full = f"{SUMMARY_SYSTEM_PROMPT}\n\n{prompt}"
        text = await runner(full, timeout=SUMMARY_TIMEOUT, on_step=on_step)
        return text or None
    # local: LM Studio OpenAI 호환 chat completions
    body = {
        "model": settings.model,
        "messages": [
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3, "max_tokens": 800, "tools": [],
    }
    r = await http.post(
        f"{LLM_BASE_URL}/v1/chat/completions", json=body, timeout=SUMMARY_TIMEOUT
    )
    content = (r.json().get("choices") or [{}])[0].get("message", {}).get("content")
    return content or None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_collect_summarize.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/collect/health.py backend/app/collect/summarize.py backend/tests/test_collect_summarize.py
git commit -m "feat(collect): LLM 헬스게이트 + 요약(local|claude 스위치)"
```

---

### Task 6: 워커 (배치 점유 + 상세 + 요약 + 상태전이)

**Files:**
- Create: `backend/app/collect/detail.py`
- Create: `backend/app/collect/worker.py`
- Test: `backend/tests/test_collect_detail.py`, `backend/tests/test_worker.py`

**Interfaces:**
- Consumes: `summarize`, `extract_stacks`, `llm_healthy` (Task 5); `config.JOB_PROXY_*`, `DETAIL_TIMEOUT`; `Settings`
- Produces:
  - `detail_url(source, job_id) -> str`, `parse_detail(source, payload) -> str | None` (본문 프롬프트 텍스트; 파싱 실패 시 None) (detail.py)
  - `CLAIM_SQL: str`, `async claim_batch(conn, limit) -> list[dict]` (worker.py)
  - `async worker_tick(conn, settings, *, http, summarizer=summarize, health=llm_healthy, on_stage=None) -> dict` — `{"claimed": n, "done": d, "failed": f, "skipped_tick": bool}`

- [ ] **Step 1: Write the failing test (detail)**

```python
# backend/tests/test_collect_detail.py
from app.collect.detail import detail_url, parse_detail


def test_detail_url_by_source():
    assert detail_url("jumpit", "5") == "https://jumpit-api.saramin.co.kr/api/position/5"
    assert "wanted.co.kr/api/chaos/jobs/v4/9/details" in detail_url("wanted", "9")


def test_parse_detail_jumpit():
    payload = {"result": {"responsibility": "일", "qualifications": "요건", "preferredRequirements": "우대"}}
    text = parse_detail("jumpit", payload)
    assert "[주요업무]" in text and "일" in text and "요건" in text and "우대" in text


def test_parse_detail_wanted():
    payload = {"data": {"job": {"detail": {"main_tasks": "업무", "requirements": "자격", "preferred_points": "가점"}}}}
    text = parse_detail("wanted", payload)
    assert "업무" in text and "자격" in text and "가점" in text


def test_parse_detail_failure_returns_none():
    assert parse_detail("wanted", {"nope": 1}) is None
```

- [ ] **Step 2: Run detail test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_collect_detail.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.collect.detail'`

- [ ] **Step 3: Write detail.py**

```python
# backend/app/collect/detail.py
def detail_url(source: str, job_id: str) -> str:
    if source == "jumpit":
        return f"https://jumpit-api.saramin.co.kr/api/position/{job_id}"
    return f"https://www.wanted.co.kr/api/chaos/jobs/v4/{job_id}/details?country=kr"


def _fmt(resp: str, qual: str, pref: str) -> str:
    return f"[주요업무]\n{resp}\n\n[자격요건]\n{qual}\n\n[우대사항]\n{pref}"


def parse_detail(source: str, payload: dict) -> str | None:
    """상세 응답 → 요약 프롬프트 본문. 파싱 실패 시 None(→ fail)."""
    if (payload or {}).get("result"):
        r = payload["result"]
        return _fmt(r.get("responsibility") or "", r.get("qualifications") or "",
                    r.get("preferredRequirements") or "")
    det = (((payload or {}).get("data") or {}).get("job") or {}).get("detail")
    if det:
        return _fmt(det.get("main_tasks") or det.get("intro") or "",
                    det.get("requirements") or "", det.get("preferred_points") or "")
    return None
```

- [ ] **Step 4: Run detail test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_collect_detail.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Write the failing test (worker)**

```python
# backend/tests/test_worker.py
from app.collect.worker import worker_tick, CLAIM_SQL
from app.settings_repo import Settings, SETTINGS_DEFAULTS


class Resp:
    def __init__(self, code=200, payload=None): self.status_code = code; self._p = payload
    def json(self): return self._p


class Http:
    def __init__(self, detail_payload): self._d = detail_payload
    async def get(self, url, headers=None, timeout=None):
        return Resp(200, self._d)


class Conn:
    """claim은 1건 반환, 이후 UPDATE 캡처."""
    def __init__(self, claimed): self._claimed = claimed; self.updates = []
    async def fetch(self, sql, *args): return self._claimed
    async def execute(self, sql, *args): self.updates.append((sql, args))


def _settings(**o):
    return Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], **o))


async def test_worker_skips_when_llm_down():
    conn = Conn([])
    async def down(http, base_url=None): return False
    r = await worker_tick(conn, _settings(), http=Http({}), health=down)
    assert r["skipped_tick"] is True
    assert conn.updates == []


async def test_worker_summarizes_and_marks_done():
    claimed = [{"id": 1, "source": "jumpit", "job_id": "5", "company": "A", "title": "T", "attempts": 0}]
    conn = Conn(claimed)
    http = Http({"result": {"responsibility": "일", "qualifications": "q", "preferredRequirements": "p"}})
    async def up(http, base_url=None): return True
    async def summ(prompt, settings, *, http, on_step=None): return "요약본\n기술스택: Go"
    r = await worker_tick(conn, _settings(), http=http, summarizer=summ, health=up)
    assert r["done"] == 1 and r["failed"] == 0
    done_sql = conn.updates[-1][0]
    assert "status='done'" in done_sql


async def test_worker_retry_cap_marks_failed_on_empty():
    claimed = [{"id": 1, "source": "jumpit", "job_id": "5", "company": "A", "title": "T", "attempts": 4}]
    conn = Conn(claimed)
    http = Http({"result": {"responsibility": "일", "qualifications": "q", "preferredRequirements": "p"}})
    async def up(http, base_url=None): return True
    async def summ(prompt, settings, *, http, on_step=None): return None  # 빈 응답
    r = await worker_tick(conn, _settings(max_attempts=5), http=http, summarizer=summ, health=up)
    assert r["failed"] == 1
    assert "failed" in conn.updates[-1][0]
```

- [ ] **Step 6: Run worker test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_worker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.collect.worker'`

- [ ] **Step 7: Write worker.py**

```python
# backend/app/collect/worker.py
import logging

from app.collect.detail import detail_url, parse_detail
from app.collect.config import DETAIL_TIMEOUT, JOB_PROXY_SECRET, JOB_PROXY_URL
from app.collect.health import llm_healthy
from app.collect.summarize import extract_stacks, summarize

log = logging.getLogger("collect.worker")
_UA = {"User-Agent": "Mozilla/5.0"}

# pending을 원자적으로 점유 → 'processing' 마킹(SKIP LOCKED로 이중 처리 방지).
CLAIM_SQL = (
    "UPDATE jobs SET status='processing', updated_at=now() "
    "WHERE id IN ("
    "  SELECT id FROM jobs WHERE status='pending' "
    "  ORDER BY collected_at LIMIT $1 FOR UPDATE SKIP LOCKED"
    ") RETURNING id, source, job_id, company, title, url, attempts"
)

_DONE_SQL = (
    "UPDATE jobs SET status='done', summary=$1, "
    "tech_stacks=CASE WHEN cardinality(tech_stacks)>0 THEN tech_stacks ELSE $2::text[] END, "
    "attempts=attempts+1, updated_at=now() WHERE id=$3"
)
_RETRY_SQL = (
    "UPDATE jobs SET status=CASE WHEN attempts+1 >= $1 THEN 'failed' ELSE 'pending' END, "
    "attempts=attempts+1, updated_at=now() WHERE id=$2"
)


async def claim_batch(conn, limit: int) -> list[dict]:
    rows = await conn.fetch(CLAIM_SQL, limit)
    return [dict(r) for r in rows]


async def _fetch_detail(http, source, job_id):
    url = detail_url(source, job_id)
    if source == "wanted" and JOB_PROXY_URL:
        from urllib.parse import quote
        url = f"{JOB_PROXY_URL}/?url={quote(url, safe='')}"
        hdr = {**_UA, "X-Proxy-Secret": JOB_PROXY_SECRET}
    else:
        hdr = _UA
    r = await http.get(url, headers=hdr, timeout=DETAIL_TIMEOUT)
    return r.json()


async def worker_tick(conn, settings, *, http, summarizer=summarize,
                      health=llm_healthy, on_stage=None) -> dict:
    if not await health(http):
        return {"claimed": 0, "done": 0, "failed": 0, "skipped_tick": True}

    batch = await claim_batch(conn, settings.batch_size)
    if on_stage and batch:
        on_stage("배치 점유", f"{len(batch)}건", 0)
    done = failed = 0
    for i, job in enumerate(batch):
        title = job.get("title") or ""
        try:
            payload = await _fetch_detail(http, job["source"], job["job_id"])
            body = parse_detail(job["source"], payload)
        except Exception:  # noqa: BLE001 — 상세조회 실패
            body = None
        if body is None:
            await conn.execute(_RETRY_SQL, settings.max_attempts, job["id"])
            failed += 1
            continue
        prompt = f"제목: {title}\n회사: {job.get('company') or ''}\n\n{body}"
        if on_stage:
            on_stage("요약 중", f"{job.get('company') or ''} · {title}", f"{i+1}/{len(batch)}")
        content = await summarizer(prompt, settings, http=http)
        if content:
            await conn.execute(_DONE_SQL, content, extract_stacks(content), job["id"])
            done += 1
        else:
            await conn.execute(_RETRY_SQL, settings.max_attempts, job["id"])
            failed += 1
    return {"claimed": len(batch), "done": done, "failed": failed, "skipped_tick": False}
```

- [ ] **Step 8: Run worker test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_worker.py tests/test_collect_detail.py -v`
Expected: PASS (7 passed)

- [ ] **Step 9: Commit**

```bash
git add backend/app/collect/detail.py backend/app/collect/worker.py backend/tests/test_collect_detail.py backend/tests/test_worker.py
git commit -m "feat(collect): 워커 SKIP LOCKED 점유 + 상세파싱 + 요약 + 상태전이"
```

---

### Task 7: 수집 라우터 (수동 트리거)

**Files:**
- Create: `backend/app/routers/collect.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_collect_router.py`

**Interfaces:**
- Consumes: `collect` (Task 4), `worker_tick` (Task 6), `get_settings` (Task 1)
- Produces: `POST /api/collect/run -> 202 {scraped, inserted}`, `POST /api/collect/worker/run -> 202 {claimed, done, failed, skipped_tick}`. httpx 클라이언트는 `app.state.http`(Task 8이 lifespan에서 생성) 사용.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_collect_router.py
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from app.routers import collect as collect_router
from app.settings_repo import Settings, SETTINGS_DEFAULTS


class Conn: pass


def _app(monkeypatch, run_result, worker_result):
    app = FastAPI()
    app.state.http = object()
    app.include_router(collect_router.router)

    async def _get_conn():
        yield Conn()
    app.dependency_overrides[collect_router.get_conn] = _get_conn

    async def fake_get_settings(conn):
        return Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"]))
    monkeypatch.setattr(collect_router, "get_settings", fake_get_settings)

    async def fake_collect(conn, s, *, http, on_stage=None): return run_result
    async def fake_worker(conn, s, *, http, on_stage=None): return worker_result
    monkeypatch.setattr(collect_router, "collect", fake_collect)
    monkeypatch.setattr(collect_router, "worker_tick", fake_worker)
    return app


async def test_collect_run(monkeypatch):
    app = _app(monkeypatch, {"scraped": 3, "inserted": 3}, {})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/collect/run")
    assert r.status_code == 202 and r.json()["scraped"] == 3


async def test_worker_run(monkeypatch):
    app = _app(monkeypatch, {}, {"claimed": 2, "done": 2, "failed": 0, "skipped_tick": False})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/collect/worker/run")
    assert r.status_code == 202 and r.json()["done"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_collect_router.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.routers.collect'`

- [ ] **Step 3: Write implementation**

```python
# backend/app/routers/collect.py
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.collect.collector import collect
from app.collect.worker import worker_tick
from app.db import get_conn
from app.settings_repo import get_settings

router = APIRouter(prefix="/api/collect", tags=["collect"])


@router.post("/run", status_code=202)
async def run_collect(request: Request, conn: Any = Depends(get_conn)):
    settings = await get_settings(conn)
    return await collect(conn, settings, http=request.app.state.http)


@router.post("/worker/run", status_code=202)
async def run_worker(request: Request, conn: Any = Depends(get_conn)):
    settings = await get_settings(conn)
    return await worker_tick(conn, settings, http=request.app.state.http)
```

- [ ] **Step 4: Register the router**

In `backend/app/main.py`:
```python
from app.routers import collect as collect_router  # import 블록
```
```python
app.include_router(collect_router.router)  # include 블록
```

- [ ] **Step 5: Run tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_collect_router.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/collect.py backend/app/main.py backend/tests/test_collect_router.py
git commit -m "feat(collect): 수동 트리거 라우터 /api/collect/run, /worker/run"
```

---

### Task 8: 스케줄러 배선 (collector·worker 잡 + reschedule + http 풀)

**Files:**
- Create: `backend/app/collect_scheduler.py`
- Modify: `backend/app/main.py` (lifespan: http 클라이언트 생성, 스케줄러 start/stop, reschedule 훅, stale reset)
- Test: `backend/tests/test_collect_scheduler.py`

**Interfaces:**
- Consumes: `collect`, `worker_tick`, `get_settings`, `Settings`
- Produces:
  - `async collector_job(get_ctx)`, `async worker_job(get_ctx)` — `get_ctx()` → `(pool, http)`.
  - `start_collect_scheduler(app) -> None` (멱등), `stop_collect_scheduler(app) -> None` (멱등), `reschedule(app, settings)` — `collect_hour`/`worker_interval_min` 반영.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_collect_scheduler.py
import types
from app import collect_scheduler as cs


class FakeSched:
    def __init__(self): self.jobs = {}; self.started = False; self.shutdown_called = False
    def add_job(self, fn, trigger, id=None, **kw): self.jobs[id] = (trigger, kw)
    def reschedule_job(self, job_id, trigger=None, **kw): self.jobs[job_id] = (trigger, kw)
    def start(self): self.started = True
    def shutdown(self, wait=False): self.shutdown_called = True


def _app():
    app = types.SimpleNamespace()
    app.state = types.SimpleNamespace(db=object(), http=object(), collect_scheduler=None)
    return app


def test_start_registers_two_jobs(monkeypatch):
    monkeypatch.setattr(cs, "AsyncIOScheduler", FakeSched)
    app = _app()
    cs.start_collect_scheduler(app)
    sched = app.state.collect_scheduler
    assert set(sched.jobs) == {"collector", "worker"}
    assert sched.started is True


def test_start_is_idempotent(monkeypatch):
    monkeypatch.setattr(cs, "AsyncIOScheduler", FakeSched)
    app = _app()
    cs.start_collect_scheduler(app)
    first = app.state.collect_scheduler
    cs.start_collect_scheduler(app)
    assert app.state.collect_scheduler is first


def test_reschedule_updates_triggers(monkeypatch):
    monkeypatch.setattr(cs, "AsyncIOScheduler", FakeSched)
    app = _app()
    cs.start_collect_scheduler(app)
    from app.settings_repo import Settings, SETTINGS_DEFAULTS
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], collect_hour=6, worker_interval_min=10))
    cs.reschedule(app, s)
    sched = app.state.collect_scheduler
    assert sched.jobs["collector"][1]["hour"] == 6
    assert sched.jobs["worker"][1]["minutes"] == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_collect_scheduler.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.collect_scheduler'`

- [ ] **Step 3: Write implementation**

```python
# backend/app/collect_scheduler.py
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.collect.collector import collect
from app.collect.worker import worker_tick
from app.settings_repo import get_settings

log = logging.getLogger("collect.scheduler")


async def collector_job(get_ctx) -> None:
    pool, http = get_ctx()
    async with pool.acquire() as conn:
        settings = await get_settings(conn)
        if not settings.enabled:
            return
        await collect(conn, settings, http=http)


async def worker_job(get_ctx) -> None:
    pool, http = get_ctx()
    async with pool.acquire() as conn:
        settings = await get_settings(conn)
        if not settings.enabled:
            return
        await worker_tick(conn, settings, http=http)


def start_collect_scheduler(app) -> None:
    """멱등. collector(cron 매일 collect_hour시)·worker(interval) 잡 등록.

    잡은 항상 등록되고, 각 틱이 settings.enabled를 확인해 no-op한다(플래그 컷오버).
    초기 트리거는 DEFAULT(09시/5분) — 실제 값은 lifespan이 reschedule로 맞춘다.
    """
    if getattr(app.state, "collect_scheduler", None) is not None:
        return
    sched = AsyncIOScheduler()
    get_ctx = lambda: (app.state.db, app.state.http)  # noqa: E731
    sched.add_job(collector_job, "cron", id="collector", hour=9, minute=0, args=[get_ctx])
    sched.add_job(worker_job, "interval", id="worker", minutes=5, args=[get_ctx])
    sched.start()
    app.state.collect_scheduler = sched
    log.info("collect scheduler started")


def stop_collect_scheduler(app) -> None:
    sched = getattr(app.state, "collect_scheduler", None)
    if sched is not None:
        sched.shutdown(wait=False)
        app.state.collect_scheduler = None


def reschedule(app, settings) -> None:
    """collect_hour / worker_interval_min 변경을 즉시 반영."""
    sched = getattr(app.state, "collect_scheduler", None)
    if sched is None:
        return
    sched.reschedule_job("collector", trigger="cron", hour=settings.collect_hour, minute=0)
    sched.reschedule_job("worker", trigger="interval", minutes=settings.worker_interval_min)
```

- [ ] **Step 4: Wire into main.py lifespan**

In `backend/app/main.py`, extend `lifespan` — create a shared httpx client, start the collect scheduler, expose the reschedule hook, and reset stale `processing` rows. Add these inside the `lifespan` function, after `app.state.db = await db.connect()`:

```python
import httpx  # 파일 상단 import 블록
from app import collect_scheduler
from app.settings_repo import get_settings
```
```python
    app.state.http = httpx.AsyncClient()
    # stale recovery: 이전 프로세스가 처리 중이던 행을 pending으로 되돌림
    async with app.state.db.acquire() as conn:
        await conn.execute("UPDATE jobs SET status='pending' WHERE status='processing'")
        settings = await get_settings(conn)
    collect_scheduler.start_collect_scheduler(app)
    collect_scheduler.reschedule(app, settings)  # DB 값으로 트리거 정렬
    app.state.reschedule_pipelines = lambda s: collect_scheduler.reschedule(app, s)
```
And in the `finally:` block, before `await db.close(...)`:
```python
        collect_scheduler.stop_collect_scheduler(app)
        await app.state.http.aclose()
```

- [ ] **Step 5: Run tests (scheduler + full backend suite)**

Run: `cd backend && .venv/bin/python -m pytest tests/test_collect_scheduler.py -v && .venv/bin/python -m pytest -q`
Expected: scheduler PASS (3 passed); full suite PASS (기존 + 신규 전부 green)

- [ ] **Step 6: Commit**

```bash
git add backend/app/collect_scheduler.py backend/app/main.py backend/tests/test_collect_scheduler.py
git commit -m "feat(collect): APScheduler collector·worker 잡 + reschedule + http 풀 + stale reset"
```

---

# Phase 3 — 라이브 모니터 (백엔드)

### Task 9: Activity Registry

**Files:**
- Create: `backend/app/activity.py`
- Test: `backend/tests/test_activity.py`

**Interfaces:**
- Produces: `class Activity` — `set_stage(pipeline, stage, detail="", progress="")`, `add_research(key, stage, detail="")`, `clear(pipeline)`, `clear_research(key)`, `snapshot() -> dict`. `collector`/`worker`는 단일 슬롯, `research`는 key별 다중.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_activity.py
from app.activity import Activity


def test_set_and_snapshot():
    a = Activity()
    a.set_stage("collector", "스크레이핑", "원티드 518 1p", "0")
    snap = a.snapshot()
    assert snap["collector"]["stage"] == "스크레이핑"
    assert snap["collector"]["detail"] == "원티드 518 1p"
    assert snap["worker"] is None


def test_clear():
    a = Activity()
    a.set_stage("worker", "요약 중")
    a.clear("worker")
    assert a.snapshot()["worker"] is None


def test_research_multi_key():
    a = Activity()
    a.add_research("당근", "기업 리서치 중", "웹 검색")
    a.add_research("토스", "공고 리서치 중")
    research = a.snapshot()["research"]
    assert {r["detail_key"] for r in research} == {"당근", "토스"}
    a.clear_research("당근")
    assert [r["detail_key"] for r in a.snapshot()["research"]] == ["토스"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_activity.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.activity'`

- [ ] **Step 3: Write implementation**

```python
# backend/app/activity.py
class Activity:
    """인메모리 실행 상태. 단일 프로세스(APScheduler in-process)이므로 잠금 불필요.

    collector/worker: 단일 슬롯(dict|None). research: key→dict 다중(동시 여러 건).
    """

    def __init__(self) -> None:
        self._slots: dict[str, dict | None] = {"collector": None, "worker": None}
        self._research: dict[str, dict] = {}

    def set_stage(self, pipeline: str, stage: str, detail: str = "", progress: str = "") -> None:
        self._slots[pipeline] = {"stage": stage, "detail": detail, "progress": progress}

    def clear(self, pipeline: str) -> None:
        self._slots[pipeline] = None

    def add_research(self, key: str, stage: str, detail: str = "") -> None:
        self._research[key] = {"detail_key": key, "stage": stage, "detail": detail}

    def clear_research(self, key: str) -> None:
        self._research.pop(key, None)

    def snapshot(self) -> dict:
        return {
            "collector": self._slots["collector"],
            "worker": self._slots["worker"],
            "research": list(self._research.values()),
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_activity.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/activity.py backend/tests/test_activity.py
git commit -m "feat(monitor): 인메모리 Activity Registry"
```

---

### Task 10: claude_client 스트리밍 + on_step

**Files:**
- Modify: `backend/app/claude_client.py`
- Modify: `backend/tests/test_claude_client.py` (기존 3개 테스트를 stream-json 형식으로 갱신 + 신규)
- Test: `backend/tests/test_claude_client.py`

**Interfaces:**
- Produces: `async run_claude(prompt, *, allowed_tools="", timeout=120, claude_bin="claude", on_step=None) -> str`. 내부적으로 `--output-format stream-json --verbose`. `on_step(label: str)`을 tool_use/텍스트 이벤트마다 호출. 최종 `type:"result"`의 `result` 반환. 실패/타임아웃 시 `RuntimeError`.
- Produces: `stream_label(event: dict) -> str | None` (순수 파서, 테스트 대상).

- [ ] **Step 1: Rewrite the test file**

```python
# backend/tests/test_claude_client.py
import asyncio
import json
import pytest
from app.claude_client import run_claude, stream_label


def _lines(*events: dict) -> bytes:
    return ("\n".join(json.dumps(e) for e in events) + "\n").encode()


class FakeStream:
    def __init__(self, data: bytes): self._data = data
    def __aiter__(self): self._it = iter(self._data.splitlines(keepends=True)); return self
    async def __anext__(self):
        try: return next(self._it)
        except StopIteration: raise StopAsyncIteration


class FakeErr:
    async def read(self): return b""


class FakeProc:
    def __init__(self, out=b"", rc=0):
        self.stdout = FakeStream(out); self.returncode = rc; self.stderr = FakeErr()
    async def wait(self): return self.returncode
    def kill(self): pass


def test_stream_label_websearch():
    ev = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "WebSearch", "input": {"query": "당근 매출"}}]}}
    assert stream_label(ev) == '웹 검색: "당근 매출"'


def test_stream_label_webfetch():
    ev = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "WebFetch", "input": {"url": "https://dart.fss.or.kr/x"}}]}}
    assert stream_label(ev) == "페이지 확인: dart.fss.or.kr"


def test_stream_label_text():
    ev = {"type": "assistant", "message": {"content": [{"type": "text", "text": "분석"}]}}
    assert stream_label(ev) == "분석·작성 중"


def test_stream_label_ignores_result():
    assert stream_label({"type": "result", "result": "x"}) is None


async def test_run_claude_returns_final_result(monkeypatch):
    out = _lines(
        {"type": "system", "subtype": "init"},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "WebSearch", "input": {"query": "q"}}]}},
        {"type": "result", "subtype": "success", "result": "최종본"},
    )
    async def fake_exec(*args, **kwargs):
        assert "stream-json" in args and "--verbose" in args
        return FakeProc(out)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    steps = []
    r = await run_claude("hi", on_step=steps.append)
    assert r == "최종본"
    assert steps == ['웹 검색: "q"']


async def test_run_claude_ignores_broken_lines(monkeypatch):
    out = b'not json\n' + _lines({"type": "result", "result": "ok"})
    async def fake_exec(*a, **k): return FakeProc(out)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    assert await run_claude("hi") == "ok"


async def test_run_claude_raises_when_no_result(monkeypatch):
    async def fake_exec(*a, **k): return FakeProc(_lines({"type": "system"}), rc=1)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(RuntimeError):
        await run_claude("hi")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_claude_client.py -v`
Expected: FAIL — `ImportError: cannot import name 'stream_label'` (및 시그니처 불일치)

- [ ] **Step 3: Rewrite claude_client.py**

```python
# backend/app/claude_client.py
import asyncio
import json
from urllib.parse import urlparse


def stream_label(event: dict) -> str | None:
    """stream-json 이벤트 → 사람이 읽는 현재 단계. 해당 없으면 None."""
    if event.get("type") != "assistant":
        return None
    for block in event.get("message", {}).get("content", []):
        if block.get("type") == "tool_use":
            name = block.get("name", "")
            inp = block.get("input", {}) or {}
            if name == "WebSearch":
                return f'웹 검색: "{inp.get("query", "")}"'
            if name == "WebFetch":
                return f"페이지 확인: {urlparse(inp.get('url', '')).netloc}"
            return f"{name} 실행 중"
        if block.get("type") == "text":
            return "분석·작성 중"
    return None


async def run_claude(
    prompt: str,
    *,
    allowed_tools: str = "",
    timeout: int = 120,
    claude_bin: str = "claude",
    on_step=None,
) -> str:
    """`claude -p`를 stream-json으로 실행. 이벤트마다 on_step(label) 호출, 최종 result 반환."""
    args = [claude_bin, "-p", prompt, "--output-format", "stream-json", "--verbose"]
    if allowed_tools:
        args += ["--allowedTools", allowed_tools]

    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )

    result: str | None = None

    async def _consume():
        nonlocal result
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue  # 비JSON/잘린 라인 무시
            if event.get("type") == "result":
                result = event.get("result")
            elif on_step is not None:
                label = stream_label(event)
                if label:
                    on_step(label)

    try:
        await asyncio.wait_for(_consume(), timeout=timeout)
        await asyncio.wait_for(proc.wait(), timeout=5)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("claude timed out")

    if proc.returncode not in (0, None) and result is None:
        err = (await proc.stderr.read()).decode()[:500]
        raise RuntimeError(f"claude failed ({proc.returncode}): {err}")
    if result is None:
        raise RuntimeError("claude produced no result event")
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_claude_client.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Verify research suite still green (run_claude 소비자)**

Run: `cd backend && .venv/bin/python -m pytest tests/test_research_runner.py tests/test_research_cli.py -q`
Expected: PASS — 기존 러너는 `on_step` 없이 호출하므로 영향 없음(기본 None).

- [ ] **Step 6: Commit**

```bash
git add backend/app/claude_client.py backend/tests/test_claude_client.py
git commit -m "feat(monitor): claude_client stream-json 파싱 + on_step 서브스텝"
```

---

### Task 11: 파이프라인에 Activity 배선

**Files:**
- Modify: `backend/app/main.py` (`app.state.activity = Activity()`)
- Modify: `backend/app/collect_scheduler.py` (collector/worker에 `on_stage` 연결 + clear)
- Modify: `backend/app/research/runner.py` (research_company/research_job에 activity `on_step`/stage)
- Test: `backend/tests/test_activity_wiring.py`

**Interfaces:**
- Consumes: `Activity` (Task 9), `on_step` (Task 10), `on_stage`(collector/worker Task 4·6)
- Produces: 러너에 선택적 `activity=None` 파라미터 추가 — `research_company(db, company, url="", *, force=False, runner=run_claude, notify=push, activity=None)`, `research_job(..., activity=None)`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_activity_wiring.py
from app.activity import Activity
from app.research import runner as R


class FakeStore:
    async def get_company(self, db, c): return None
    async def mark_company_running(self, db, c): pass
    async def save_company(self, db, c, **kw): pass


async def test_research_company_publishes_stage(monkeypatch):
    act = Activity()
    seen = {}
    monkeypatch.setattr(R, "store", FakeStore())

    async def fake_runner(prompt, *, allowed_tools="", timeout=0, on_step=None):
        on_step('웹 검색: "x"')                       # claude 서브스텝 시뮬레이트
        seen["research"] = act.snapshot()["research"]  # 실행 중 스냅샷
        return '{"overview":"o","stability":"s","sources":[]}'

    async def noop(*a, **k): pass
    await R.research_company(object(), "당근", runner=fake_runner, notify=noop, activity=act)
    # 실행 중엔 stage가 게시되고, 끝나면 clear
    assert seen["research"][0]["detail_key"] == "당근"
    assert '웹 검색' in seen["research"][0]["stage"] or seen["research"][0]["detail"]
    assert act.snapshot()["research"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_activity_wiring.py -v`
Expected: FAIL — `TypeError: research_company() got an unexpected keyword argument 'activity'`

- [ ] **Step 3: Wire Activity into runner.py**

Change the `_run_and_parse` helper to forward an `on_step`, then thread `activity` through both functions. Replace `_run_and_parse` with:

```python
async def _run_and_parse(prompt, runner, on_step=None) -> dict:
    """claude 호출 → JSON 파싱. 파싱 실패 시 1회만 재시도. on_step은 서브스텝 콜백."""
    text = await runner(prompt, allowed_tools=RESEARCH_TOOLS, timeout=RESEARCH_TIMEOUT, on_step=on_step)
    try:
        return parse_research_json(text)
    except ValueError:
        retry = prompt + "\n\n[재시도] 반드시 JSON 객체 하나만 출력. 그 외 텍스트 금지."
        text = await runner(retry, allowed_tools=RESEARCH_TOOLS, timeout=RESEARCH_TIMEOUT, on_step=on_step)
        return parse_research_json(text)
```

Then add `activity=None` to `research_company` and publish/clear its stage around the existing body:

```python
async def research_company(
    db, company, url="", *, force=False, runner=run_claude, notify=push, activity=None,
) -> str:
    existing = await store.get_company(db, company)
    if existing and existing.get("status") == "done" and not force:
        return "cached"

    await store.mark_company_running(db, company)
    prompt = build_company_prompt(company, url)

    def _step(label):
        if activity is not None:
            activity.add_research(company, "기업 리서치 중", label)

    _step("")  # 시작 시 stage 게시(라벨 없이)
    try:
        parsed = await _run_and_parse(prompt, runner, on_step=_step)
    except Exception as e:  # noqa: BLE001 — 어떤 실패든 failed로 표면화
        log.warning("company research failed: %s: %s", company, e)
        await store.save_company(db, company, status="failed", model=RESEARCH_MODEL)
        await notify(f"🔴 기업 리서치 실패: {company}")
        if activity is not None:
            activity.clear_research(company)
        return "failed"

    await store.save_company(
        db, company, status="done",
        overview=parsed.get("overview"), stability=parsed.get("stability"),
        data=parsed, sources=parsed.get("sources"), model=RESEARCH_MODEL,
    )
    await notify(f"🏢 기업 리서치 완료: {company}")
    if activity is not None:
        activity.clear_research(company)
    return "done"
```

For `research_job`, apply the identical pattern: add `activity=None` to its signature; define `key = f"{source}:{job_id}"` and `def _step(label): activity and activity.add_research(key, "공고 리서치 중", label)`; call `_step("")` before the job claude call; pass `on_step=_step` into its `_run_and_parse(prompt, runner, on_step=_step)` call; pass `activity=activity` into the inner `research_company(...)` call so the company sub-phase publishes too; and call `activity.clear_research(key)` (guarded by `if activity is not None`) on both the failure return and the success return.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_activity_wiring.py tests/test_research_runner.py -v`
Expected: PASS (기존 러너 테스트 포함 green — activity 기본 None)

- [ ] **Step 5: Wire on_stage into collector/worker jobs and Activity into main**

In `backend/app/main.py` lifespan, after `app.state.http = ...`:
```python
from app.activity import Activity  # import 블록
```
```python
    app.state.activity = Activity()
```
In `backend/app/collect_scheduler.py`, update the two jobs to publish stages and clear:
```python
async def collector_job(get_ctx) -> None:
    pool, http, activity = get_ctx()
    async with pool.acquire() as conn:
        settings = await get_settings(conn)
        if not settings.enabled:
            return
        try:
            await collect(conn, settings, http=http,
                          on_stage=lambda st, d, p: activity.set_stage("collector", st, d, str(p)))
        finally:
            activity.clear("collector")


async def worker_job(get_ctx) -> None:
    pool, http, activity = get_ctx()
    async with pool.acquire() as conn:
        settings = await get_settings(conn)
        if not settings.enabled:
            return
        try:
            await worker_tick(conn, settings, http=http,
                              on_stage=lambda st, d, p: activity.set_stage("worker", st, d, str(p)))
        finally:
            activity.clear("worker")
```
And update `get_ctx` in `start_collect_scheduler` to include activity:
```python
    get_ctx = lambda: (app.state.db, app.state.http, app.state.activity)  # noqa: E731
```
Update the scheduler test's `_app()` to also set `app.state.activity = Activity()` and the FakeSched jobs assertion remains valid (job registration unchanged).

- [ ] **Step 6: Run full backend suite**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: PASS (all green)

- [ ] **Step 7: Commit**

```bash
git add backend/app/main.py backend/app/collect_scheduler.py backend/app/research/runner.py backend/tests/test_activity_wiring.py backend/tests/test_collect_scheduler.py
git commit -m "feat(monitor): collector·worker·research에 Activity 단계 게시 배선"
```

---

### Task 12: 상태 라우터 (GET /api/status)

**Files:**
- Create: `backend/app/routers/status.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_status_router.py`

**Interfaces:**
- Consumes: `app.state.activity` (Task 11), `get_settings`, `llm_healthy`
- Produces: `GET /api/status -> {activity, counts, llm_health, enabled, next_ticks}`. `counts`는 `SELECT status, count(*) FROM jobs GROUP BY status` + `job_research.status='running'` 파생.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_status_router.py
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from app.routers import status as status_router
from app.activity import Activity
from app.settings_repo import Settings, SETTINGS_DEFAULTS


class Conn:
    async def fetch(self, sql, *a):
        if "GROUP BY status" in sql:
            return [{"status": "pending", "n": 7}, {"status": "done", "n": 3}]
        return [{"n": 1}]  # research_running
    async def fetchval(self, sql, *a): return 1


def _app(activity):
    app = FastAPI()
    app.state.activity = activity
    app.state.http = object()
    app.include_router(status_router.router)

    async def _get_conn():
        yield Conn()
    app.dependency_overrides[status_router.get_conn] = _get_conn

    async def fake_get_settings(conn):
        return Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], enabled=True))
    status_router.get_settings = fake_get_settings

    async def fake_health(http, base_url=None): return True
    status_router.llm_healthy = fake_health
    return app


async def test_status_shape():
    act = Activity()
    act.set_stage("worker", "요약 중", "토스", "4/20")
    async with AsyncClient(transport=ASGITransport(app=_app(act)), base_url="http://t") as c:
        r = await c.get("/api/status")
    body = r.json()
    assert r.status_code == 200
    assert body["activity"]["worker"]["stage"] == "요약 중"
    assert body["counts"]["pending"] == 7
    assert body["llm_health"] == "ok"
    assert body["enabled"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_status_router.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.routers.status'`

- [ ] **Step 3: Write implementation**

```python
# backend/app/routers/status.py
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.collect.health import llm_healthy
from app.db import get_conn
from app.settings_repo import get_settings

router = APIRouter(prefix="/api", tags=["status"])


@router.get("/status")
async def read_status(request: Request, conn: Any = Depends(get_conn)):
    settings = await get_settings(conn)
    rows = await conn.fetch("SELECT status, count(*) AS n FROM jobs GROUP BY status")
    counts = {r["status"]: r["n"] for r in rows}
    research_running = await conn.fetchval(
        "SELECT count(*) FROM job_research WHERE status='running'"
    ) or 0
    healthy = await llm_healthy(request.app.state.http)
    return {
        "activity": request.app.state.activity.snapshot(),
        "counts": {
            "pending": counts.get("pending", 0),
            "done": counts.get("done", 0),
            "failed": counts.get("failed", 0),
            "skipped": counts.get("skipped", 0),
            "research_running": research_running,
        },
        "llm_health": "ok" if healthy else "down",
        "enabled": settings.enabled,
        "next_ticks": {"collect_hour": settings.collect_hour,
                       "worker_interval_min": settings.worker_interval_min},
    }
```

- [ ] **Step 4: Register the router**

In `backend/app/main.py`:
```python
from app.routers import status as status_router  # import 블록
```
```python
app.include_router(status_router.router)  # include 블록
```

- [ ] **Step 5: Run tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_status_router.py -v && .venv/bin/python -m pytest -q`
Expected: PASS (1 passed; full suite green)

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/status.py backend/app/main.py backend/tests/test_status_router.py
git commit -m "feat(monitor): GET /api/status 라이브 상태 라우터"
```

---

# Phase 4 — 프론트엔드

### Task 13: API 클라이언트 (settings + status)

**Files:**
- Create: `frontend/src/settingsApi.ts`
- Create: `frontend/src/statusApi.ts`
- Test: `frontend/src/settingsApi.test.ts`

**Interfaces:**
- Produces:
  - `interface Settings { keywords: string[]; allowed_wanted_categories: number[]; max_career_years: number; max_pages: number; collect_hour: number; batch_size: number; model: string; summary_backend: "local"|"claude"; max_attempts: number; worker_interval_min: number; enabled: boolean; discord_webhook_url: string; updated_at?: string }`
  - `getSettings(): Promise<Settings>`, `putSettings(s: Settings): Promise<Settings>` (422 시 `{status:422, errors}` throw)
  - `runCollect(): Promise<{scraped:number;inserted:number}>`, `runWorker(): Promise<{claimed:number;done:number;failed:number;skipped_tick:boolean}>`
  - `getStatus(): Promise<StatusResponse>` (statusApi.ts)

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/settingsApi.test.ts
import { vi, test, expect, afterEach } from "vitest";
import { getSettings, putSettings } from "./settingsApi";

afterEach(() => vi.restoreAllMocks());

test("getSettings fetches and parses", async () => {
  const body = { batch_size: 20, keywords: ["백엔드"] };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(body) }));
  const s = await getSettings();
  expect(s.batch_size).toBe(20);
});

test("putSettings throws typed error on 422", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: false, status: 422, json: () => Promise.resolve({ detail: [{ loc: ["body", "collect_hour"], msg: "bad" }] }),
  }));
  await expect(putSettings({} as never)).rejects.toMatchObject({ status: 422 });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/settingsApi.test.ts`
Expected: FAIL — cannot find module `./settingsApi`

- [ ] **Step 3: Write implementation**

```typescript
// frontend/src/settingsApi.ts
export interface Settings {
  keywords: string[];
  allowed_wanted_categories: number[];
  max_career_years: number;
  max_pages: number;
  collect_hour: number;
  batch_size: number;
  model: string;
  summary_backend: "local" | "claude";
  max_attempts: number;
  worker_interval_min: number;
  enabled: boolean;
  discord_webhook_url: string;
  updated_at?: string;
}

export async function getSettings(): Promise<Settings> {
  const r = await fetch("/api/settings");
  if (!r.ok) throw new Error("settings load failed");
  return r.json();
}

export async function putSettings(s: Settings): Promise<Settings> {
  const r = await fetch("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(s),
  });
  if (!r.ok) {
    const detail = await r.json().catch(() => ({}));
    throw { status: r.status, errors: detail.detail ?? detail };
  }
  return r.json();
}

export async function runCollect(): Promise<{ scraped: number; inserted: number }> {
  const r = await fetch("/api/collect/run", { method: "POST" });
  if (!r.ok) throw new Error("collect run failed");
  return r.json();
}

export async function runWorker(): Promise<{ claimed: number; done: number; failed: number; skipped_tick: boolean }> {
  const r = await fetch("/api/collect/worker/run", { method: "POST" });
  if (!r.ok) throw new Error("worker run failed");
  return r.json();
}
```

```typescript
// frontend/src/statusApi.ts
export interface StatusResponse {
  activity: {
    collector: { stage: string; detail: string; progress: string } | null;
    worker: { stage: string; detail: string; progress: string } | null;
    research: { detail_key: string; stage: string; detail: string }[];
  };
  counts: { pending: number; done: number; failed: number; skipped: number; research_running: number };
  llm_health: "ok" | "down";
  enabled: boolean;
  next_ticks: { collect_hour: number; worker_interval_min: number };
}

export async function getStatus(): Promise<StatusResponse> {
  const r = await fetch("/api/status");
  if (!r.ok) throw new Error("status load failed");
  return r.json();
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/settingsApi.test.ts`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/settingsApi.ts frontend/src/statusApi.ts frontend/src/settingsApi.test.ts
git commit -m "feat(frontend): settings·status API 클라이언트"
```

---

### Task 14: ChipInput + Segmented 컴포넌트

**Files:**
- Create: `frontend/src/components/ChipInput.tsx`
- Create: `frontend/src/components/Segmented.tsx`
- Test: `frontend/src/components/ChipInput.test.tsx`

**Interfaces:**
- Produces:
  - `ChipInput({ value, onChange, mode }: { value: (string|number)[]; onChange: (v: (string|number)[]) => void; mode: "text"|"number" })` — Enter로 추가(trim·중복·빈값·숫자모드 비숫자 거부), × 제거.
  - `Segmented<T>({ value, options, onChange }: { value: T; options: {label: string; value: T}[]; onChange: (v: T) => void })`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/ChipInput.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { vi, test, expect } from "vitest";
import ChipInput from "./ChipInput";

function add(input: HTMLElement, text: string) {
  fireEvent.change(input, { target: { value: text } });
  fireEvent.keyDown(input, { key: "Enter" });
}

test("adds text chip on Enter, dedupes, drops empty", () => {
  const onChange = vi.fn();
  const { rerender } = render(<ChipInput value={[]} onChange={onChange} mode="text" />);
  const input = screen.getByRole("textbox");
  add(input, "  백엔드 ");
  expect(onChange).toHaveBeenLastCalledWith(["백엔드"]);
  rerender(<ChipInput value={["백엔드"]} onChange={onChange} mode="text" />);
  add(input, "백엔드"); // 중복
  expect(onChange).toHaveBeenLastCalledWith(["백엔드"]);
});

test("number mode rejects non-numeric", () => {
  const onChange = vi.fn();
  render(<ChipInput value={[]} onChange={onChange} mode="number" />);
  const input = screen.getByRole("textbox");
  add(input, "abc");
  expect(onChange).not.toHaveBeenCalled();
  add(input, "518");
  expect(onChange).toHaveBeenLastCalledWith([518]);
});

test("removes chip on × click", () => {
  const onChange = vi.fn();
  render(<ChipInput value={["백엔드", "ML"]} onChange={onChange} mode="text" />);
  fireEvent.click(screen.getByLabelText("백엔드 제거"));
  expect(onChange).toHaveBeenLastCalledWith(["ML"]);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/ChipInput.test.tsx`
Expected: FAIL — cannot find module `./ChipInput`

- [ ] **Step 3: Write implementation**

```tsx
// frontend/src/components/ChipInput.tsx
import { useState } from "react";

type Val = string | number;

export default function ChipInput({
  value, onChange, mode,
}: { value: Val[]; onChange: (v: Val[]) => void; mode: "text" | "number" }) {
  const [draft, setDraft] = useState("");

  function commit() {
    const t = draft.trim();
    if (!t) return;
    let v: Val = t;
    if (mode === "number") {
      if (!/^\d+$/.test(t)) { setDraft(""); return; }  // 비숫자 거부
      v = Number(t);
    }
    if (!value.some((x) => x === v)) onChange([...value, v]);  // 중복 방지
    setDraft("");
  }

  return (
    <div className="chip-input">
      {value.map((v) => (
        <span key={String(v)} className="pill chip">
          {v}
          <button type="button" aria-label={`${v} 제거`} onClick={() => onChange(value.filter((x) => x !== v))}>×</button>
        </span>
      ))}
      <input
        type="text"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(); } }}
        placeholder="입력 후 Enter"
      />
    </div>
  );
}
```

```tsx
// frontend/src/components/Segmented.tsx
export default function Segmented<T extends string>({
  value, options, onChange,
}: { value: T; options: { label: string; value: T }[]; onChange: (v: T) => void }) {
  return (
    <div className="segmented" role="tablist">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="tab"
          aria-selected={value === o.value}
          className={value === o.value ? "seg active" : "seg"}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/ChipInput.test.tsx`
Expected: PASS (3 passed)

- [ ] **Step 5: Add minimal styles**

Append to `frontend/src/index.css`:
```css
.chip-input { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.chip button { margin-left: 6px; background: none; border: none; cursor: pointer; color: inherit; }
.chip-input input { flex: 1; min-width: 120px; background: transparent; border: none; outline: none; color: inherit; }
.segmented { display: inline-flex; gap: 2px; border-radius: 8px; overflow: hidden; }
.segmented .seg { padding: 6px 14px; border: none; cursor: pointer; background: var(--surface-2, #2a2a2a); color: inherit; }
.segmented .seg.active { background: var(--accent, #3b82f6); color: #fff; }
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ChipInput.tsx frontend/src/components/Segmented.tsx frontend/src/components/ChipInput.test.tsx frontend/src/index.css
git commit -m "feat(frontend): ChipInput·Segmented 재사용 컴포넌트"
```

---

### Task 15: 설정 페이지 (config + enabled + 수동 트리거)

**Files:**
- Create: `frontend/src/pages/Settings.tsx`
- Modify: `frontend/src/App.tsx` (라우트 `/settings` + 내비)
- Test: `frontend/src/pages/Settings.test.tsx`

**Interfaces:**
- Consumes: `getSettings`, `putSettings`, `runCollect`, `runWorker`, `Settings` (Task 13); `ChipInput`, `Segmented` (Task 14)

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/pages/Settings.test.tsx
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import Settings from "./Settings";
import * as api from "../settingsApi";

const seed: api.Settings = {
  keywords: ["백엔드"], allowed_wanted_categories: [518], max_career_years: 2,
  max_pages: 9999, collect_hour: 9, batch_size: 20, model: "kanana",
  summary_backend: "local", max_attempts: 5, worker_interval_min: 5,
  enabled: false, discord_webhook_url: "",
};

beforeEach(() => {
  vi.spyOn(api, "getSettings").mockResolvedValue({ ...seed });
  vi.spyOn(api, "putSettings").mockImplementation(async (s) => s);
});

test("loads settings and disables save until dirty", async () => {
  render(<Settings />);
  await waitFor(() => expect(screen.getByText("백엔드")).toBeTruthy());
  expect((screen.getByRole("button", { name: "저장" }) as HTMLButtonElement).disabled).toBe(true);
});

test("editing enables save and PUTs", async () => {
  render(<Settings />);
  await waitFor(() => expect(screen.getByText("백엔드")).toBeTruthy());
  fireEvent.change(screen.getByLabelText("배치 크기"), { target: { value: "30" } });
  const save = screen.getByRole("button", { name: "저장" }) as HTMLButtonElement;
  expect(save.disabled).toBe(false);
  fireEvent.click(save);
  await waitFor(() => expect(api.putSettings).toHaveBeenCalled());
  expect(api.putSettings.mock.calls[0][0].batch_size).toBe(30);
});

test("manual run buttons disabled while dirty", async () => {
  render(<Settings />);
  await waitFor(() => expect(screen.getByText("백엔드")).toBeTruthy());
  fireEvent.change(screen.getByLabelText("배치 크기"), { target: { value: "30" } });
  expect((screen.getByRole("button", { name: "지금 수집" }) as HTMLButtonElement).disabled).toBe(true);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/Settings.test.tsx`
Expected: FAIL — cannot find module `./Settings`

- [ ] **Step 3: Write implementation**

```tsx
// frontend/src/pages/Settings.tsx
import { useEffect, useState } from "react";
import { getSettings, putSettings, runCollect, runWorker, type Settings as S } from "../settingsApi";
import ChipInput from "../components/ChipInput";
import Segmented from "../components/Segmented";

export default function Settings() {
  const [form, setForm] = useState<S | null>(null);
  const [saved, setSaved] = useState<S | null>(null);
  const [busy, setBusy] = useState(false);
  const [runMsg, setRunMsg] = useState("");

  useEffect(() => {
    getSettings().then((s) => { setForm(s); setSaved(s); });
  }, []);

  if (!form || !saved) return <p className="caption" style={{ margin: "var(--sp-5)" }}>불러오는 중…</p>;

  const dirty = JSON.stringify(form) !== JSON.stringify(saved);
  const set = <K extends keyof S>(k: K, v: S[K]) => setForm({ ...form, [k]: v });
  const num = (k: keyof S) => (e: React.ChangeEvent<HTMLInputElement>) => set(k, Number(e.target.value) as never);

  async function save() {
    setBusy(true);
    try { const r = await putSettings(form!); setForm(r); setSaved(r); }
    finally { setBusy(false); }
  }
  async function doRun(fn: () => Promise<Record<string, number | boolean>>, label: string) {
    setBusy(true); setRunMsg("실행 중…");
    try { const r = await fn(); setRunMsg(`${label}: ${JSON.stringify(r)}`); }
    finally { setBusy(false); }
  }

  return (
    <div className="doc" style={{ maxWidth: 640 }}>
      <h1 style={{ display: "flex", justifyContent: "space-between" }}>
        설정
        <button className="btn-primary" onClick={save} disabled={!dirty || busy}>저장</button>
      </h1>

      <section>
        <h2 className="section-title">수집 제어</h2>
        <label className="field">
          <span className="flabel">수집 활성화</span>
          <input type="checkbox" checked={form.enabled} onChange={(e) => set("enabled", e.target.checked)} />
        </label>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button onClick={() => doRun(runCollect, "수집")} disabled={dirty || busy}>지금 수집</button>
          <button onClick={() => doRun(runWorker, "워커")} disabled={dirty || busy}>워커 1회</button>
          <span className="caption">{dirty ? "먼저 저장하세요" : runMsg}</span>
        </div>
      </section>

      <section>
        <h2 className="section-title">수집기</h2>
        <div className="field"><span className="flabel">키워드</span>
          <ChipInput mode="text" value={form.keywords} onChange={(v) => set("keywords", v as string[])} /></div>
        <div className="field"><span className="flabel">원티드 카테고리</span>
          <ChipInput mode="number" value={form.allowed_wanted_categories} onChange={(v) => set("allowed_wanted_categories", v as number[])} /></div>
        <label className="field"><span className="flabel">경력 상한(년)</span>
          <input aria-label="경력 상한" type="number" value={form.max_career_years} onChange={num("max_career_years")} /></label>
        <label className="field"><span className="flabel">페이지 상한</span>
          <input aria-label="페이지 상한" type="number" value={form.max_pages} onChange={num("max_pages")} /></label>
        <label className="field"><span className="flabel">수집 시각(시)</span>
          <input aria-label="수집 시각" type="number" value={form.collect_hour} onChange={num("collect_hour")} />
          <span className="caption">저장 시 즉시 재적용</span></label>
      </section>

      <section>
        <h2 className="section-title">워커</h2>
        <label className="field"><span className="flabel">배치 크기</span>
          <input aria-label="배치 크기" type="number" value={form.batch_size} onChange={num("batch_size")} /></label>
        <label className="field"><span className="flabel">재시도(회)</span>
          <input aria-label="재시도" type="number" value={form.max_attempts} onChange={num("max_attempts")} /></label>
        <label className="field"><span className="flabel">워커 주기(분)</span>
          <input aria-label="워커 주기" type="number" value={form.worker_interval_min} onChange={num("worker_interval_min")} />
          <span className="caption">저장 시 즉시 재적용</span></label>
        <div className="field"><span className="flabel">요약 백엔드</span>
          <Segmented value={form.summary_backend}
            options={[{ label: "로컬 LLM", value: "local" }, { label: "claude", value: "claude" }]}
            onChange={(v) => set("summary_backend", v)} /></div>
        <label className="field"><span className="flabel">모델</span>
          <input aria-label="모델" type="text" value={form.model} onChange={(e) => set("model", e.target.value)} /></label>
      </section>

      <section>
        <h2 className="section-title">알림</h2>
        <label className="field"><span className="flabel">Discord 웹훅</span>
          <input aria-label="Discord 웹훅" type="text" value={form.discord_webhook_url}
            onChange={(e) => set("discord_webhook_url", e.target.value)} /></label>
      </section>
    </div>
  );
}
```

- [ ] **Step 4: Add route and nav in App.tsx**

In `frontend/src/App.tsx`, import and add the route + nav link:
```tsx
import Settings from "./pages/Settings";
```
```tsx
<NavLink to="/settings" title="설정" className={active}>⚙</NavLink>
```
(inside `<nav className="rail">`, before the `<span style={{ flex: 1 }} />`)
```tsx
<Route path="/settings" element={<Settings />} />
```
(inside `<Routes>`)

- [ ] **Step 5: Run tests**

Run: `cd frontend && npx vitest run src/pages/Settings.test.tsx src/App.test.tsx`
Expected: PASS (Settings 3 passed; App still green)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Settings.tsx frontend/src/App.tsx frontend/src/pages/Settings.test.tsx
git commit -m "feat(frontend): 설정 페이지(config+enabled+수동트리거) + /settings 라우트"
```

---

### Task 16: 상태 모니터 페이지 (폴링)

**Files:**
- Create: `frontend/src/pages/Status.tsx`
- Modify: `frontend/src/App.tsx` (라우트 `/status` + 내비)
- Test: `frontend/src/pages/Status.test.tsx`

**Interfaces:**
- Consumes: `getStatus`, `StatusResponse` (Task 13)

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/pages/Status.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach, afterEach } from "vitest";
import Status from "./Status";
import * as api from "../statusApi";

const base: api.StatusResponse = {
  activity: { collector: null, worker: { stage: "요약 중", detail: "토스 · 백엔드", progress: "4/20" }, research: [] },
  counts: { pending: 7, done: 3, failed: 0, skipped: 0, research_running: 1 },
  llm_health: "ok", enabled: true, next_ticks: { collect_hour: 9, worker_interval_min: 5 },
};

beforeEach(() => vi.spyOn(api, "getStatus").mockResolvedValue(base));
afterEach(() => vi.restoreAllMocks());

test("renders running worker card and backlog", async () => {
  render(<Status />);
  await waitFor(() => expect(screen.getByText("요약 중")).toBeTruthy());
  expect(screen.getByText(/토스 · 백엔드/)).toBeTruthy();
  expect(screen.getByText(/4\/20/)).toBeTruthy();
  expect(screen.getByText(/7/)).toBeTruthy(); // pending 백로그
});

test("shows idle for empty pipeline", async () => {
  render(<Status />);
  await waitFor(() => expect(screen.getAllByText(/idle/i).length).toBeGreaterThan(0));
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/Status.test.tsx`
Expected: FAIL — cannot find module `./Status`

- [ ] **Step 3: Write implementation**

```tsx
// frontend/src/pages/Status.tsx
import { useEffect, useState } from "react";
import { getStatus, type StatusResponse } from "../statusApi";

const POLL_MS = 3000;

function Slot({ name, act }: { name: string; act: { stage: string; detail: string; progress: string } | null }) {
  return (
    <div className="status-row">
      <span className="flabel">{name}</span>
      {act ? (
        <span>{act.stage} {act.progress && `· ${act.progress}`} <span className="caption">{act.detail}</span></span>
      ) : (
        <span className="caption">idle</span>
      )}
    </div>
  );
}

export default function Status() {
  const [s, setS] = useState<StatusResponse | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => { try { const r = await getStatus(); if (alive) setS(r); } catch { /* keep last */ } };
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => { alive = false; clearInterval(id); };
  }, []);

  if (!s) return <p className="caption" style={{ margin: "var(--sp-5)" }}>불러오는 중…</p>;

  return (
    <div className="doc" style={{ maxWidth: 640 }}>
      <h1>상태</h1>
      <div style={{ display: "flex", gap: 8, marginBottom: "var(--sp-4)" }}>
        <span className="pill">백로그 {s.counts.pending}</span>
        <span className={s.llm_health === "ok" ? "pill" : "pill pill-bad"}>LLM {s.llm_health}</span>
        <span className="pill">{s.enabled ? "수집 ON" : "수집 OFF"}</span>
      </div>
      <section>
        <Slot name="수집기" act={s.activity.collector} />
        <Slot name="워커" act={s.activity.worker} />
        {s.activity.research.length === 0 ? (
          <div className="status-row"><span className="flabel">리서치</span><span className="caption">idle</span></div>
        ) : (
          s.activity.research.map((r) => (
            <div className="status-row" key={r.detail_key}>
              <span className="flabel">리서치</span>
              <span>{r.stage} <span className="caption">{r.detail || r.detail_key}</span></span>
            </div>
          ))
        )}
      </section>
    </div>
  );
}
```

- [ ] **Step 4: Add route and nav + styles**

In `frontend/src/App.tsx`:
```tsx
import Status from "./pages/Status";
```
```tsx
<NavLink to="/status" title="상태" className={active}>◉</NavLink>
```
```tsx
<Route path="/status" element={<Status />} />
```
Append to `frontend/src/index.css`:
```css
.status-row { display: flex; gap: 12px; align-items: baseline; padding: 8px 0; border-bottom: 1px solid var(--border, #333); }
.status-row .flabel { min-width: 72px; }
```

- [ ] **Step 5: Run tests + full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: PASS (Status 2 passed; 전체 스위트 green)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Status.tsx frontend/src/App.tsx frontend/src/pages/Status.test.tsx frontend/src/index.css
git commit -m "feat(frontend): 라이브 상태 모니터 페이지 + /status 라우트(폴링)"
```

---

# 컷오버 런북 (배포 후 수동 실행 — 코드 태스크 아님)

> 모든 태스크 머지 + `alembic upgrade head`(0003 적용, enabled=false 시드) 후 실행.

```
1. [배포]   전체 배포. enabled=false라 스케줄러 잡은 매 틱 no-op. n8n 무중단.
2. [검증-설정]  agent.chs135.com/settings 열어 시드값이 n8n과 일치하는지 대조. 값 하나 바꿔 저장→반영 확인.
3. [검증-수집]  POST /api/collect/run (또는 "지금 수집" 버튼) → dedup으로 n8n 켜져 있어도 안전.
              /status에서 스크레이핑 단계 관찰. jobs pending 신규 스팟체크. 재실행 시 신규 0.
4. [n8n 워커 OFF]  n8n UI에서 02-worker 비활성화.
5. [검증-워커]  POST /api/collect/worker/run (또는 "워커 1회") → pending→done, 요약 채워짐,
              LLM 내리고 재시도 시 skipped_tick=true(억울한 fail 없음).
6. [n8n 수집기 OFF]  n8n UI에서 01-collector 비활성화.
7. [전환]   /settings에서 수집 활성화 체크 → 저장. Python 스케줄러 인수.
8. [모니터]  /status로 다음 워커 틱 + 다음날 09시 collector 관찰.

롤백: /settings에서 enabled 해제 저장(Python 즉시 no-op) + n8n 01·02 재활성화.
```

**환경변수 준비(배포 전):** A1 컨테이너 env에 `LLM_BASE_URL`(리서치가 쓰는 lm.chs135.com 경유값), `JOB_PROXY_URL`, `JOB_PROXY_SECRET`, `SEARCH_KEYWORDS`, `DISCORD_WEBHOOK_URL` 존재 확인(마이그레이션 시드가 SEARCH_KEYWORDS·DISCORD_WEBHOOK_URL을 읽음).
