# career-agent Plan ④ 리서치 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 2단 리서치(①기업 개요·안정성 = 회사당 1회, ②공고+기업 기술·직무 = 공고당 1회)를 `claude -p` 웹검색 서브프로세스로 실행하고, `company_research`·`job_research` 테이블에 캐싱(running/done/failed, force 재리서치)하며, 트리거는 비동기 BackgroundTask로 202 즉시 응답 + 완료 시 Discord 푸시, 프론트는 폴링으로 열람/트리거한다. 백엔드 신규 표면은 **별도 라우터 파일 + `app/research/` 러너 패키지**로 격리하고 `main.py`에는 **mount 한 줄**만 추가한다. APScheduler 자동모드는 구현하되 **플래그로 비활성**.

**Architecture:** Walking Skeleton(FastAPI 컨테이너 + `run_claude` 래퍼 + nginx + docker compose + Jenkins)와 Plan ②(career-agent 소유 Postgres·`jobs`/`company_research`/`job_research` 테이블·`app/db.py` 풀)·Plan ③(`GET /api/jobs`·`GET /api/jobs/{source}/{job_id}` 뷰어 API + 프론트 리스트/상세) 위에 얹는다. 리서치 러너는 Plan ①의 `run_claude(prompt, allowed_tools="WebSearch,WebFetch")`를 재사용해 JSON을 받아 파싱·저장하고, 라우터는 `BackgroundTasks`로 러너를 비동기 기동한다.

**Tech Stack:** Python 3.12 · FastAPI · asyncpg(Plan ② 제공) · httpx · APScheduler · pytest / React 18 · Vite · TypeScript · vitest / nginx · Docker Compose · Jenkins

## Global Constraints

- 레포 루트: `/Users/sunny/career-agent`. 원격: `ssafychs135/career-agent`. 배포 대상: A1(ssh alias `a1`), 경로 `/home/ubuntu/career-agent`.
- claude 인증 = **구독**(과금 0). 리서치 호출은 `run_claude(prompt, allowed_tools="WebSearch,WebFetch", timeout=…)` — 웹툴만 허용(파일·bash 불허, A1 안전). 프롬프트는 **"오직 JSON 객체 하나만 출력"** 지시. 파싱 실패 시 1회 재시도 후 `failed`.
- 구독 레이트리밋 보호: 캐싱(회사/공고당 1회)이 1차 방어. 자동/배치는 `--limit`·동시성 상한. 자동모드는 기본 **꺼짐**(`RESEARCH_AUTO_ENABLED=false`).
- **결합 최소화:** 신규 백엔드 표면은 `app/routers/research.py`(APIRouter) + `app/research/` 패키지에만 둔다. `app/main.py` 편집은 **`from app.routers import research` + `research.init_research(app)` 두 줄**로 한정(다른 플랜과 병렬 시 충돌 최소화). DB 스키마·`app/db.py`·`GET /api/jobs*`·프론트 상세 뷰는 **수정하지 않고 소비**한다.
- 커밋 메시지 말미: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- 공개 리포에 개인 취업 결과(회사명·합불) 노출 금지. `.env`·시크릿 커밋 금지.

### 선행 플랜이 제공한다고 가정하는 인터페이스 (구현 전 확인 · 어긋나면 해당 파일만 조정)

- **Plan ② (테이블):**
  - `company_research`·`job_research` 테이블(설계 스펙 데이터 모델 그대로; `status` = running/done/failed, `data`/`sources` = jsonb).
  - `jobs` 테이블에 조회용 컬럼 `company, title, tech_stacks, summary, url, status`(실제 컬럼명은 기존 n8n `jobs` 스키마 확정본을 따르며, 어긋나면 `store.py`의 `get_job_meta` SELECT만 조정 — **Task 2에서 실제 컬럼 확인**).
  - `app/db.py`가 asyncpg 풀을 소유하고 **정본 계약 1번**의 인터페이스를 노출:
    - FastAPI 의존성 `async def get_conn(request: Request)` — `request.app.state.db.acquire()`로 asyncpg **Connection**(메서드 `fetchrow/fetch/fetchval/execute`, 위치 파라미터 `$1` 보유)을 `yield`.
    - lifespan에서 `app.state.db = await connect()` / `await close(app.state.db)`로 풀 open/close.
    - CLI·백그라운드용 `async def connect() -> asyncpg.Pool` / `async def close(pool) -> None`(DATABASE_URL로 풀 생성·정리). Pool도 `fetchrow/fetch/execute`를 지원하므로 store는 conn/pool 어느 쪽이든 동작.
  - **주의:** 런타임은 asyncpg만 사용(계약 1번). 이름·시그니처가 어긋나면 `store.py`·`get_conn` import·`__main__.py`의 `connect/close`만 어댑트(격리됨).
- **Plan ③ (뷰어 — 상세 본문 생산자):**
  - `GET /api/jobs/{source}/{job_id}` → `{ job, companyResearch, jobResearch }`(company_research·job_research LEFT JOIN; 각 research는 없으면 null, 있으면 `status`·`researched_at` 포함)는 **Plan ③가 생산**한다. 프론트 `src/api.ts`에 `getJob(source, jobId)` 존재. **Plan ④는 이 엔드포인트/`getJob`을 소비만**(상세 본문 공급 태스크를 ④에 만들지 않음 — 계약 2·5번).
  - 공고 상세 뷰 컴포넌트가 존재하며, 그 안에 Plan ④의 `<ResearchPanel/>`를 **import 한 줄**로 얹고 `refetch={() => getJob(source, jobId)}`를 주입한다.

### 구현 순서 메모(테스트 독립성)

- Task 1~4·7·8은 **순수/주입식**이라 Plan ②·③ 코드 없이 단독 테스트 가능(DB·claude·fetch를 fake로 주입).
- Task 5(라우터)·6(스케줄러)·9(라이브)는 `app.db`(Plan ② 소유 `get_conn`/`connect`/`close`)와 런타임 deps(`apscheduler`·`httpx` — 계약 2번에서 Plan ② pyproject가 소유)에 의존 → **Plan ② 머지 후** 실행.

---

## File Structure

```
career-agent/
├─ backend/
│  ├─ app/
│  │  ├─ main.py                     # (편집) research.init_research(app) 두 줄만 추가
│  │  ├─ claude_client.py            # (기존, 그대로 재사용) run_claude
│  │  ├─ db.py                       # (Plan ② 소유, 소비만)
│  │  ├─ routers/
│  │  │  ├─ __init__.py
│  │  │  └─ research.py              # APIRouter: POST /api/research/company·/job + init_research(app)
│  │  └─ research/
│  │     ├─ __init__.py
│  │     ├─ config.py                # 환경설정(모델·타임아웃·자동모드 플래그)
│  │     ├─ prompts.py               # build_company_prompt / build_job_prompt / RESEARCH_TOOLS
│  │     ├─ parse.py                 # parse_research_json (펜스/서두 관용)
│  │     ├─ store.py                 # DB read/write (research 2테이블 + jobs 메타 조회)
│  │     ├─ discord.py               # push(content) — 완료/실패 알림
│  │     ├─ runner.py                # research_company / research_job 오케스트레이션
│  │     ├─ scheduler.py             # APScheduler 자동모드(플래그 꺼짐)
│  │     └─ __main__.py              # 관리용 CLI (python -m app.research)
│  ├─ tests/
│  │  ├─ test_research_prompts.py
│  │  ├─ test_research_parse.py
│  │  ├─ test_research_store.py
│  │  ├─ test_research_runner.py
│  │  ├─ test_research_discord.py
│  │  ├─ test_research_router.py
│  │  ├─ test_research_scheduler.py
│  │  └─ test_research_cli.py
│  ├─ pyproject.toml                 # (계약 2번: Plan ②가 소유 — 손대지 않음)
│  └─ Dockerfile                     # (계약 3번: Plan ②가 소유 — 손대지 않음)
└─ frontend/
   └─ src/
      ├─ researchApi.ts              # postCompanyResearch / postJobResearch
      ├─ ResearchPanel.tsx           # 리서치 열람 + 트리거 버튼 + 폴링
      └─ ResearchPanel.test.tsx
```

각 파일 1책임: `prompts`=문자열만, `parse`=파싱만, `store`=SQL만, `runner`=오케스트레이션만, `discord`=HTTP 알림만, `research.py`=라우팅만, `ResearchPanel`=표시·폴링만.

---

## Task 1: 리서치 프롬프트 + JSON 파서 (`prompts.py`, `parse.py`)

**Files:**
- Create: `backend/app/research/__init__.py`, `backend/app/research/prompts.py`, `backend/app/research/parse.py`, `backend/tests/test_research_prompts.py`, `backend/tests/test_research_parse.py`

**Interfaces:**
- Produces: `RESEARCH_TOOLS = "WebSearch,WebFetch"`; `build_company_prompt(company, url="") -> str`; `build_job_prompt(company_overview, title, tech_stacks, summary, url) -> str`; `parse_research_json(text) -> dict`(첫 `{`~마지막 `}` 추출 후 `json.loads`, 실패 시 `ValueError`).

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/app/research/__init__.py`: (빈 파일)

`backend/tests/test_research_prompts.py`:
```python
from app.research.prompts import (
    RESEARCH_TOOLS,
    build_company_prompt,
    build_job_prompt,
)


def test_tools_are_web_only():
    assert RESEARCH_TOOLS == "WebSearch,WebFetch"


def test_company_prompt_contains_name_and_json_directive():
    p = build_company_prompt("토스", "https://x/y")
    assert "토스" in p
    assert "https://x/y" in p
    assert '"overview"' in p and '"stability"' in p and '"sources"' in p
    assert "JSON 객체 하나만" in p  # 단일 JSON 강제 지시


def test_job_prompt_injects_company_overview():
    p = build_job_prompt("핀테크 스타트업", "백엔드", "Java,Spring", "요약", "https://z")
    assert "핀테크 스타트업" in p
    assert '"tech_detail"' in p and '"role_detail"' in p
    assert "백엔드" in p and "Java,Spring" in p
```

`backend/tests/test_research_parse.py`:
```python
import pytest
from app.research.parse import parse_research_json


def test_parses_plain_json():
    assert parse_research_json('{"a": 1}') == {"a": 1}


def test_parses_fenced_json():
    text = '```json\n{"overview": "x", "sources": ["u"]}\n```'
    assert parse_research_json(text) == {"overview": "x", "sources": ["u"]}


def test_parses_json_with_prose_prefix():
    text = '아래는 결과입니다:\n{"role_detail": "y"}\n감사합니다'
    assert parse_research_json(text) == {"role_detail": "y"}


def test_raises_when_no_object():
    with pytest.raises(ValueError):
        parse_research_json("no json here")
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && python -m pytest tests/test_research_prompts.py tests/test_research_parse.py -q`
Expected: FAIL — `ModuleNotFoundError: app.research.prompts` / `app.research.parse`

- [ ] **Step 3: 구현**

`backend/app/research/prompts.py`:
```python
RESEARCH_TOOLS = "WebSearch,WebFetch"


def build_company_prompt(company: str, url: str = "") -> str:
    return f"""너는 취업 리서처다. 아래 회사를 웹검색으로 조사해 JSON만 출력하라.
회사명: {company}   (참고 공고 URL: {url})
{{
  "overview":  "사업·주력제품·규모 4~6문장",
  "stability": "설립연도·투자단계/누적투자·매출/흑자여부·최근 동향 등 재무·안정성 근거 4~6문장. 불확실하면 '확인 안 됨' 명시",
  "sources":   ["실제 참고한 URL"]
}}
근거 없는 추측 금지. 한국 스타트업은 정보가 적을 수 있으니 모르면 모른다고 하라.
오직 위 JSON 객체 하나만 출력하라. 설명·머리말·코드펜스 금지."""


def build_job_prompt(
    company_overview: str,
    title: str,
    tech_stacks: str,
    summary: str,
    url: str,
) -> str:
    return f"""회사 개요(기존 리서치): {company_overview}
공고: {title} / 기술스택(수집): {tech_stacks} / 요약: {summary} / URL: {url}
위 공고를 웹검색으로 조사해 JSON만 출력하라.
{{
  "tech_detail": "실제 사용 기술스택·아키텍처·개발문화 근거와 함께 4~6문장",
  "role_detail": "담당 업무·기대 경력/역량·성장경로 4~6문장",
  "sources": ["실제 참고한 URL"]
}}
근거 없는 추측 금지. 오직 위 JSON 객체 하나만 출력하라. 설명·머리말·코드펜스 금지."""
```

`backend/app/research/parse.py`:
```python
import json


def parse_research_json(text: str) -> dict:
    """claude result 텍스트에서 JSON 객체를 파싱.

    코드펜스(```json)·서두 설명·후미 텍스트에 관용적: 첫 '{'~마지막 '}' 구간만 취해
    json.loads 한다. 객체가 없거나 파싱 불가면 ValueError.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object in claude output")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON: {e}") from e
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_research_prompts.py tests/test_research_parse.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: 커밋**

```bash
cd /Users/sunny/career-agent
git add backend/app/research/__init__.py backend/app/research/prompts.py backend/app/research/parse.py backend/tests/test_research_prompts.py backend/tests/test_research_parse.py
git commit -m "feat(research): 리서치 프롬프트 빌더 + JSON 파서"
```

---

## Task 2: 리서치 스토어 (DB read/write) (`store.py`)

**Files:**
- Create: `backend/app/research/store.py`, `backend/tests/test_research_store.py`

**Interfaces:**
- Consumes: asyncpg Pool(`fetchrow/fetch/execute`, `$1` 파라미터) — 러너·라우터가 주입.
- Produces:
  - `get_company(db, company) -> dict|None`, `get_job(db, source, job_id) -> dict|None`, `get_job_meta(db, source, job_id) -> dict|None`(jobs 조회).
  - `mark_company_running(db, company)`, `mark_job_running(db, source, job_id, company)`.
  - `save_company(db, company, *, status, overview=None, stability=None, data=None, sources=None, model=None)`; `save_job(db, source, job_id, company, *, status, tech_detail=None, role_detail=None, data=None, sources=None, model=None)`.
  - `pending_companies(db, limit=10) -> list[str]`, `pending_jobs(db, limit=10) -> list[tuple[str,str]]`.

> **선행 확인:** 구현 전 A1 DB에서 `jobs` 실제 컬럼을 확인하고 `get_job_meta`의 SELECT를 맞춘다: `ssh a1 'sudo docker exec <pg> psql -U <user> -d jobs -c "\d jobs"'` → **controller 확인 필요**(DB 접근·컨테이너명). 컬럼명이 다르면 이 파일의 SELECT만 조정.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_research_store.py`:
```python
import json
from app.research import store


class FakeDB:
    """asyncpg Pool 흉내: fetchrow/fetch/execute 호출·인자 기록."""

    def __init__(self, fetchrow=None, fetch=None):
        self._fetchrow = fetchrow
        self._fetch = fetch or []
        self.calls = []

    async def fetchrow(self, q, *a):
        self.calls.append(("fetchrow", q, a))
        return self._fetchrow

    async def fetch(self, q, *a):
        self.calls.append(("fetch", q, a))
        return self._fetch

    async def execute(self, q, *a):
        self.calls.append(("execute", q, a))
        return "OK"


async def test_get_company_returns_dict():
    db = FakeDB(fetchrow={"company": "토스", "status": "done"})
    assert await store.get_company(db, "토스") == {"company": "토스", "status": "done"}


async def test_get_company_none_when_missing():
    assert await store.get_company(FakeDB(fetchrow=None), "x") is None


async def test_mark_company_running_upserts_running():
    db = FakeDB()
    await store.mark_company_running(db, "토스")
    q, a = db.calls[0][1], db.calls[0][2]
    assert "company_research" in q and "running" in q
    assert a == ("토스",)


async def test_save_company_serializes_jsonb():
    db = FakeDB()
    await store.save_company(
        db, "토스", status="done", overview="o", stability="s",
        data={"k": "v"}, sources=["u1"], model="m",
    )
    args = db.calls[0][2]
    # data·sources는 json.dumps 된 문자열로 전달
    assert json.loads(args[3]) == {"k": "v"}
    assert json.loads(args[4]) == ["u1"]
    assert "done" in db.calls[0][1] or "done" in args


async def test_save_job_upsert_and_null_json():
    db = FakeDB()
    await store.save_job(db, "wanted", "42", "토스", status="failed")
    q, a = db.calls[0][1], db.calls[0][2]
    assert "job_research" in q
    assert a[0] == "wanted" and a[1] == "42" and a[2] == "토스"


async def test_pending_companies_maps_rows():
    db = FakeDB(fetch=[{"company": "A"}, {"company": "B"}])
    assert await store.pending_companies(db, 5) == ["A", "B"]


async def test_pending_jobs_maps_tuples():
    db = FakeDB(fetch=[{"source": "s", "job_id": "1"}])
    assert await store.pending_jobs(db, 5) == [("s", "1")]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && python -m pytest tests/test_research_store.py -q`
Expected: FAIL — `ModuleNotFoundError: app.research.store`

- [ ] **Step 3: 구현**

`backend/app/research/store.py`:
```python
import json


def _jsonb(value):
    return json.dumps(value, ensure_ascii=False) if value is not None else None


async def get_company(db, company):
    row = await db.fetchrow(
        "SELECT * FROM company_research WHERE company = $1", company
    )
    return dict(row) if row else None


async def get_job(db, source, job_id):
    row = await db.fetchrow(
        "SELECT * FROM job_research WHERE source = $1 AND job_id = $2",
        source,
        job_id,
    )
    return dict(row) if row else None


async def get_job_meta(db, source, job_id):
    """jobs 테이블에서 리서치 컨텍스트를 조회. 컬럼명은 실제 jobs 스키마에 맞춤."""
    row = await db.fetchrow(
        "SELECT source, job_id, company, title, tech_stacks, summary, url "
        "FROM jobs WHERE source = $1 AND job_id = $2",
        source,
        job_id,
    )
    return dict(row) if row else None


async def mark_company_running(db, company):
    await db.execute(
        """INSERT INTO company_research (company, status, researched_at)
           VALUES ($1, 'running', now())
           ON CONFLICT (company)
           DO UPDATE SET status = 'running', researched_at = now()""",
        company,
    )


async def mark_job_running(db, source, job_id, company):
    await db.execute(
        """INSERT INTO job_research (source, job_id, company, status, researched_at)
           VALUES ($1, $2, $3, 'running', now())
           ON CONFLICT (source, job_id)
           DO UPDATE SET status = 'running', company = EXCLUDED.company,
                         researched_at = now()""",
        source,
        job_id,
        company,
    )


async def save_company(
    db, company, *, status, overview=None, stability=None,
    data=None, sources=None, model=None,
):
    await db.execute(
        """INSERT INTO company_research
             (company, overview, stability, data, sources, model, status, researched_at)
           VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7, now())
           ON CONFLICT (company) DO UPDATE SET
             overview = EXCLUDED.overview, stability = EXCLUDED.stability,
             data = EXCLUDED.data, sources = EXCLUDED.sources,
             model = EXCLUDED.model, status = EXCLUDED.status,
             researched_at = now()""",
        company, overview, stability, _jsonb(data), _jsonb(sources), model, status,
    )


async def save_job(
    db, source, job_id, company, *, status, tech_detail=None,
    role_detail=None, data=None, sources=None, model=None,
):
    await db.execute(
        """INSERT INTO job_research
             (source, job_id, company, tech_detail, role_detail,
              data, sources, model, status, researched_at)
           VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9, now())
           ON CONFLICT (source, job_id) DO UPDATE SET
             company = EXCLUDED.company, tech_detail = EXCLUDED.tech_detail,
             role_detail = EXCLUDED.role_detail, data = EXCLUDED.data,
             sources = EXCLUDED.sources, model = EXCLUDED.model,
             status = EXCLUDED.status, researched_at = now()""",
        source, job_id, company, tech_detail, role_detail,
        _jsonb(data), _jsonb(sources), model, status,
    )


async def pending_companies(db, limit=10):
    rows = await db.fetch(
        """SELECT DISTINCT j.company
           FROM jobs j
           LEFT JOIN company_research c ON c.company = j.company
           WHERE j.company IS NOT NULL AND j.company <> ''
             AND (c.company IS NULL OR c.status = 'failed')
           LIMIT $1""",
        limit,
    )
    return [r["company"] for r in rows]


async def pending_jobs(db, limit=10):
    rows = await db.fetch(
        """SELECT j.source, j.job_id
           FROM jobs j
           LEFT JOIN job_research r ON r.source = j.source AND r.job_id = j.job_id
           WHERE (r.source IS NULL OR r.status = 'failed')
           LIMIT $1""",
        limit,
    )
    return [(r["source"], r["job_id"]) for r in rows]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_research_store.py -q`
Expected: PASS (8 passed)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/research/store.py backend/tests/test_research_store.py
git commit -m "feat(research): research/jobs DB 스토어(캐시·pending 조회)"
```

---

## Task 3: 리서치 러너 (오케스트레이션) (`runner.py`, `config.py`)

**Files:**
- Create: `backend/app/research/config.py`, `backend/app/research/runner.py`, `backend/tests/test_research_runner.py`

**Interfaces:**
- Consumes: `store`, `prompts`, `parse`, `run_claude`(claude_client), `discord.push`.
- Produces:
  - `async def research_company(db, company, url="", *, force=False, runner=run_claude, notify=push) -> str` — 반환 `"cached"|"done"|"failed"`.
  - `async def research_job(db, source, job_id, *, force=False, runner=run_claude, notify=push) -> str` — 기업 리서치 선행 후 실행. 공고 없으면 `LookupError`.
  - 상태 전이: 캐시 done + not force → skip; 아니면 `running` upsert → claude → 파싱(실패 1회 재시도) → `done`/`failed` 저장 → Discord 푸시.

- [ ] **Step 1: config 작성**

`backend/app/research/config.py`:
```python
import os

RESEARCH_MODEL = os.environ.get("RESEARCH_MODEL", "")
RESEARCH_TIMEOUT = int(os.environ.get("RESEARCH_TIMEOUT", "180"))

# 자동모드(APScheduler) — 기본 꺼짐
RESEARCH_AUTO_ENABLED = os.environ.get("RESEARCH_AUTO_ENABLED", "false").lower() == "true"
RESEARCH_AUTO_INTERVAL_MIN = int(os.environ.get("RESEARCH_AUTO_INTERVAL_MIN", "30"))
RESEARCH_AUTO_LIMIT = int(os.environ.get("RESEARCH_AUTO_LIMIT", "5"))
```

- [ ] **Step 2: 실패하는 테스트 작성**

`backend/tests/test_research_runner.py`:
```python
import pytest
from app.research import runner


class Recorder:
    def __init__(self):
        self.saved = []
        self.notified = []
        self.running = []


@pytest.fixture
def wired(monkeypatch):
    """store를 인메모리로, notify를 기록기로 교체."""
    rec = Recorder()
    state = {"company": {}, "job": {}, "job_meta": {}}

    async def get_company(db, company):
        return state["company"].get(company)

    async def get_job(db, source, job_id):
        return state["job"].get((source, job_id))

    async def get_job_meta(db, source, job_id):
        return state["job_meta"].get((source, job_id))

    async def mark_company_running(db, company):
        rec.running.append(("company", company))
        state["company"][company] = {"status": "running"}

    async def mark_job_running(db, source, job_id, company):
        rec.running.append(("job", source, job_id))
        state["job"][(source, job_id)] = {"status": "running"}

    async def save_company(db, company, **kw):
        rec.saved.append(("company", company, kw))
        state["company"][company] = {"status": kw["status"], **kw}

    async def save_job(db, source, job_id, company, **kw):
        rec.saved.append(("job", source, job_id, kw))
        state["job"][(source, job_id)] = {"status": kw["status"], **kw}

    for name, fn in dict(
        get_company=get_company, get_job=get_job, get_job_meta=get_job_meta,
        mark_company_running=mark_company_running, mark_job_running=mark_job_running,
        save_company=save_company, save_job=save_job,
    ).items():
        monkeypatch.setattr(runner.store, name, fn)

    async def notify(msg):
        rec.notified.append(msg)

    rec.state = notify_state = state
    rec.notify = notify
    return rec


def make_runner(*replies):
    replies = list(replies)

    async def fake(prompt, **kw):
        return replies.pop(0)

    return fake


async def test_company_cache_skip(wired):
    wired.state["company"]["토스"] = {"status": "done"}
    out = await runner.research_company(
        None, "토스", runner=make_runner('{"overview":"x"}'), notify=wired.notify,
    )
    assert out == "cached"
    assert wired.saved == []  # 재저장 없음


async def test_company_force_reresearches(wired):
    wired.state["company"]["토스"] = {"status": "done"}
    out = await runner.research_company(
        None, "토스", force=True,
        runner=make_runner('{"overview":"o","stability":"s","sources":["u"]}'),
        notify=wired.notify,
    )
    assert out == "done"
    kind, company, kw = wired.saved[0]
    assert kw["status"] == "done" and kw["overview"] == "o"
    assert wired.notified  # 완료 알림


async def test_company_parse_retry_then_success(wired):
    out = await runner.research_company(
        None, "토스",
        runner=make_runner("헛소리", '{"overview":"o"}'),  # 1차 실패 → 2차 성공
        notify=wired.notify,
    )
    assert out == "done"


async def test_company_failed_after_retry(wired):
    out = await runner.research_company(
        None, "토스",
        runner=make_runner("bad", "still bad"),
        notify=wired.notify,
    )
    assert out == "failed"
    assert wired.saved[-1][2]["status"] == "failed"


async def test_job_precedes_company_then_researches(wired):
    wired.state["job_meta"][("wanted", "42")] = {
        "company": "토스", "title": "백엔드", "tech_stacks": "Java",
        "summary": "s", "url": "https://x",
    }
    out = await runner.research_job(
        None, "wanted", "42",
        runner=make_runner(
            '{"overview":"o"}',                    # 기업 리서치
            '{"tech_detail":"t","role_detail":"r"}',  # 공고 리서치
        ),
        notify=wired.notify,
    )
    assert out == "done"
    kinds = [s[0] for s in wired.saved]
    assert kinds == ["company", "job"]  # 기업 먼저 저장


async def test_job_missing_raises(wired):
    with pytest.raises(LookupError):
        await runner.research_job(
            None, "wanted", "999",
            runner=make_runner('{"x":1}'), notify=wired.notify,
        )
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `cd backend && python -m pytest tests/test_research_runner.py -q`
Expected: FAIL — `ModuleNotFoundError: app.research.runner`

- [ ] **Step 4: 구현**

`backend/app/research/runner.py`:
```python
import logging

from app.claude_client import run_claude
from app.research import store
from app.research.config import RESEARCH_MODEL, RESEARCH_TIMEOUT
from app.research.discord import push
from app.research.parse import parse_research_json
from app.research.prompts import (
    RESEARCH_TOOLS,
    build_company_prompt,
    build_job_prompt,
)

log = logging.getLogger("research")


async def _run_and_parse(prompt, runner) -> dict:
    """claude 호출 → JSON 파싱. 파싱 실패 시 1회만 재시도."""
    text = await runner(prompt, allowed_tools=RESEARCH_TOOLS, timeout=RESEARCH_TIMEOUT)
    try:
        return parse_research_json(text)
    except ValueError:
        retry = prompt + "\n\n[재시도] 반드시 JSON 객체 하나만 출력. 그 외 텍스트 금지."
        text = await runner(retry, allowed_tools=RESEARCH_TOOLS, timeout=RESEARCH_TIMEOUT)
        return parse_research_json(text)


async def research_company(
    db, company, url="", *, force=False, runner=run_claude, notify=push,
) -> str:
    existing = await store.get_company(db, company)
    if existing and existing.get("status") == "done" and not force:
        return "cached"

    await store.mark_company_running(db, company)
    prompt = build_company_prompt(company, url)
    try:
        parsed = await _run_and_parse(prompt, runner)
    except Exception as e:  # noqa: BLE001 — 어떤 실패든 failed로 표면화
        log.warning("company research failed: %s: %s", company, e)
        await store.save_company(db, company, status="failed", model=RESEARCH_MODEL)
        await notify(f"🔴 기업 리서치 실패: {company}")
        return "failed"

    await store.save_company(
        db, company, status="done",
        overview=parsed.get("overview"), stability=parsed.get("stability"),
        data=parsed, sources=parsed.get("sources"), model=RESEARCH_MODEL,
    )
    await notify(f"🏢 기업 리서치 완료: {company}")
    return "done"


async def research_job(
    db, source, job_id, *, force=False, runner=run_claude, notify=push,
) -> str:
    existing = await store.get_job(db, source, job_id)
    if existing and existing.get("status") == "done" and not force:
        return "cached"

    meta = await store.get_job_meta(db, source, job_id)
    if meta is None:
        raise LookupError(f"job not found: {source}:{job_id}")

    # ① 기업 리서치 선행(캐시되면 내부에서 skip)
    await research_company(
        db, meta["company"], meta.get("url", "") or "", runner=runner, notify=notify,
    )
    company_row = await store.get_company(db, meta["company"])
    overview = (company_row or {}).get("overview", "") or ""

    await store.mark_job_running(db, source, job_id, meta["company"])
    prompt = build_job_prompt(
        overview, meta.get("title", ""), meta.get("tech_stacks", ""),
        meta.get("summary", ""), meta.get("url", ""),
    )
    try:
        parsed = await _run_and_parse(prompt, runner)
    except Exception as e:  # noqa: BLE001
        log.warning("job research failed: %s:%s: %s", source, job_id, e)
        await store.save_job(
            db, source, job_id, meta["company"], status="failed", model=RESEARCH_MODEL,
        )
        await notify(f"🔴 공고 리서치 실패: {meta['company']} {source}:{job_id}")
        return "failed"

    await store.save_job(
        db, source, job_id, meta["company"], status="done",
        tech_detail=parsed.get("tech_detail"), role_detail=parsed.get("role_detail"),
        data=parsed, sources=parsed.get("sources"), model=RESEARCH_MODEL,
    )
    await notify(f"📋 공고 리서치 완료: {meta['company']} {source}:{job_id}")
    return "done"
```

> `runner.py`는 `app.research.discord`를 import하므로 Task 4를 먼저(또는 병행) 만든다. 테스트는 `notify`를 주입하므로 discord의 실제 동작에 의존하지 않는다.

- [ ] **Step 5: 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_research_runner.py -q`
Expected: PASS (6 passed)

- [ ] **Step 6: 커밋**

```bash
git add backend/app/research/config.py backend/app/research/runner.py backend/tests/test_research_runner.py
git commit -m "feat(research): 2단 리서치 러너(캐시·force·재시도·기업 선행)"
```

---

## Task 4: Discord 푸시 (`discord.py`)

**Files:**
- Create: `backend/app/research/discord.py`, `backend/tests/test_research_discord.py`

> **의존성(계약 2번):** `httpx`는 **Plan ②가 pyproject 런타임 deps에 이미 포함**(계약 2번)하므로 Plan ④는 `pyproject.toml`을 **손대지 않는다**. dev deps에도 `httpx`가 있어 단위 테스트는 그대로 동작한다.

**Interfaces:**
- Produces: `async def push(content: str) -> None` — `DISCORD_WEBHOOK_URL` 있으면 비동기 POST, 없거나 실패해도 조용히 무시(알림이 리서치를 막지 않음).

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_research_discord.py`:
```python
import httpx
from app.research import discord


class FakeClient:
    posted = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        FakeClient.posted.append((url, kw))
        return None


async def test_push_posts_when_webhook_set(monkeypatch):
    FakeClient.posted = []
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord/hook")
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    await discord.push("hi")
    assert FakeClient.posted[0][0] == "https://discord/hook"
    assert FakeClient.posted[0][1]["json"] == {"content": "hi"}


async def test_push_noop_without_webhook(monkeypatch):
    FakeClient.posted = []
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    await discord.push("hi")
    assert FakeClient.posted == []


async def test_push_swallows_errors(monkeypatch):
    class Boom(FakeClient):
        async def post(self, url, **kw):
            raise httpx.ConnectError("down")

    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord/hook")
    monkeypatch.setattr(httpx, "AsyncClient", Boom)
    await discord.push("hi")  # 예외 전파 없이 반환
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && python -m pytest tests/test_research_discord.py -q`
Expected: FAIL — `ModuleNotFoundError: app.research.discord`

- [ ] **Step 3: 구현**

`backend/app/research/discord.py`:
```python
import logging
import os

import httpx

log = logging.getLogger("research.discord")


async def push(content: str) -> None:
    """Discord 웹훅으로 알림. 웹훅 미설정/실패는 조용히 무시(리서치 흐름 비차단)."""
    url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(
                url,
                json={"content": content},
                headers={"User-Agent": "career-agent"},
            )
    except Exception as e:  # noqa: BLE001 — 알림 실패는 무시
        log.warning("discord push failed: %s", e)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && pip install -e ".[dev]" && python -m pytest tests/test_research_discord.py -q`
Expected: PASS (3 passed) — `httpx`는 dev deps(및 Plan ② 런타임 deps)로 제공됨.

- [ ] **Step 5: 커밋**

```bash
git add backend/app/research/discord.py backend/tests/test_research_discord.py
git commit -m "feat(research): Discord 완료/실패 푸시(비차단)"
```

---

## Task 5: 리서치 라우터 + main.py 마운트 (`routers/research.py`)

이 태스크부터 `app.db`(Plan ②)에 의존한다. **Plan ② 머지 후** 진행.

**Files:**
- Create: `backend/app/routers/__init__.py`, `backend/app/routers/research.py`, `backend/tests/test_research_router.py`
- Edit: `backend/app/main.py`(**가산 2줄만** — import + `init_research(app)`)

> **의존성(계약 2·3번):** `httpx`·`apscheduler`는 **Plan ②가 pyproject 런타임 deps + Dockerfile pip 라인에 이미 포함**(계약 2·3번)한다. Plan ④는 `pyproject.toml`·`Dockerfile`을 **손대지 않는다**. 로컬 테스트는 Plan ② 머지 후 `pip install -e ".[dev]"`로 apscheduler가 설치된 상태에서 돈다.

**Interfaces:**
- Consumes: `get_conn`(app.db — 계약 1번, `request.app.state.db.acquire()`로 Connection yield), `app.state.db`(Plan ② lifespan 풀), `runner`, `store`.
- Produces:
  - `POST /api/research/company` body `{company, force?}` → **202 전 `store.mark_company_running` upsert**(계약 7번: 폴링이 즉시 running을 봄) 후 BackgroundTask로 `research_company`, 즉시 202 `{"status":"running","company":…}`.
  - `POST /api/research/job` body `{source, job_id, force?}` → 공고 존재 확인(없으면 404), **202 전 `store.mark_job_running` upsert** 후 BackgroundTask로 `research_job`, 202 `{"status":"running","source":…,"job_id":…}`.
  - BackgroundTask에는 요청 스코프 `conn`(응답 후 풀에 반납됨)이 아니라 **`request.app.state.db`(풀)** 를 넘겨 러너가 자체 acquire하도록 한다(연결 수명 버그 회피).
  - `init_research(app)`: **라우터 include만**. 자동모드 스케줄러 start/stop은 **Plan ②의 단일 lifespan**이 소유(계약 6a) — `init_research`는 `add_event_handler`를 쓰지 않는다.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_research_router.py`:
```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.db  # Plan ② 제공 (계약 1번: get_conn/connect/close)
from app.routers import research


def make_app(monkeypatch):
    """research 라우터가 붙고 get_conn·app.state.db가 갖춰진 테스트 앱."""
    app = FastAPI()
    app.state.db = object()  # BackgroundTask로 넘길 풀 자리(러너는 fake라 실사용 안 함)
    research.init_research(app)
    # 계약 1번 정본 의존성 이름 = get_conn. request 스코프 conn 오버라이드.
    app.dependency_overrides[research.get_conn] = lambda: object()
    return app


def test_company_trigger_marks_running_then_202(monkeypatch):
    ran = []
    app = make_app(monkeypatch)

    async def fake_company(db, company, url="", *, force=False):
        ran.append(("company", company, force))

    async def fake_mark(conn, company):
        ran.append(("mark", company))

    monkeypatch.setattr(research.runner, "research_company", fake_company)
    monkeypatch.setattr(research.store, "mark_company_running", fake_mark)

    r = TestClient(app).post("/api/research/company", json={"company": "토스"})
    assert r.status_code == 202
    assert r.json()["status"] == "running"
    assert ("mark", "토스") in ran               # 202 전 running upsert(계약 7번)
    assert ("company", "토스", False) in ran      # BackgroundTask 실행됨


def test_job_trigger_404_when_missing(monkeypatch):
    app = make_app(monkeypatch)

    async def missing(conn, source, job_id):
        return None

    monkeypatch.setattr(research.store, "get_job_meta", missing)
    r = TestClient(app).post(
        "/api/research/job", json={"source": "wanted", "job_id": "999"}
    )
    assert r.status_code == 404


def test_job_trigger_marks_running_then_202(monkeypatch):
    ran = []
    app = make_app(monkeypatch)

    async def found(conn, source, job_id):
        return {"company": "토스"}

    async def fake_mark(conn, source, job_id, company):
        ran.append(("mark", source, job_id, company))

    async def fake_job(db, source, job_id, *, force=False):
        ran.append((source, job_id, force))

    monkeypatch.setattr(research.store, "get_job_meta", found)
    monkeypatch.setattr(research.store, "mark_job_running", fake_mark)
    monkeypatch.setattr(research.runner, "research_job", fake_job)
    r = TestClient(app).post(
        "/api/research/job", json={"source": "wanted", "job_id": "42", "force": True}
    )
    assert r.status_code == 202
    assert ("mark", "wanted", "42", "토스") in ran  # 202 전 running upsert(계약 7번)
    assert ("wanted", "42", True) in ran
```

> 라우터는 `from app.db import get_conn`(계약 1번 정본 이름)를 재노출(`research.get_conn`)해 테스트에서 `dependency_overrides[research.get_conn]`로 잡는다. 오버라이드는 **finally에서 clear**가 원칙이나(계약 1번), 테스트마다 `FastAPI()`를 새로 만들므로 전역 오염은 없다.

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && python -m pytest tests/test_research_router.py -q`
Expected: FAIL — `ModuleNotFoundError: app.routers.research`(또는 `app.db` 미존재면 Plan ② 선행 필요)

- [ ] **Step 3: 구현**

`backend/app/routers/__init__.py`: (빈 파일)

`backend/app/routers/research.py`:
```python
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel

from app.db import get_conn  # Plan ② 제공 (계약 1번; 테스트 dependency_overrides 대상)
from app.research import runner, store

router = APIRouter(prefix="/api/research", tags=["research"])


class CompanyReq(BaseModel):
    company: str
    force: bool = False


class JobReq(BaseModel):
    source: str
    job_id: str
    force: bool = False


@router.post("/company", status_code=202)
async def trigger_company(
    req: CompanyReq, bg: BackgroundTasks, request: Request, conn=Depends(get_conn)
):
    # 계약 7번: 202 전 running upsert → 폴링이 즉시 running을 봄.
    await store.mark_company_running(conn, req.company)
    # BackgroundTask에는 요청 스코프 conn(응답 후 반납됨) 대신 풀을 넘겨 러너가 자체 acquire.
    bg.add_task(
        runner.research_company, request.app.state.db, req.company, "", force=req.force
    )
    return {"status": "running", "company": req.company}


@router.post("/job", status_code=202)
async def trigger_job(
    req: JobReq, bg: BackgroundTasks, request: Request, conn=Depends(get_conn)
):
    meta = await store.get_job_meta(conn, req.source, req.job_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="job not found")
    # 계약 7번: 202 전 running upsert.
    await store.mark_job_running(conn, req.source, req.job_id, meta["company"])
    bg.add_task(
        runner.research_job, request.app.state.db, req.source, req.job_id, force=req.force
    )
    return {"status": "running", "source": req.source, "job_id": req.job_id}


def init_research(app) -> None:
    """main.py에서 한 번 호출: 라우터 include만.

    계약 6a: 스케줄러 start/stop은 **Plan ②의 단일 lifespan**이 `start_scheduler(app)`/
    `stop_scheduler(app)`로 소유한다. 여기서 `add_event_handler`로 등록하면 커스텀 lifespan에
    무시되어 자동모드가 조용히 안 뜬다 → 등록하지 않는다.
    """
    app.include_router(router)
```

`backend/app/main.py` 편집 — **가산 2줄만**(계약 6번: 전체 파일 교체 금지). Plan ②가 같은 파일에 lifespan(풀 open/close)을 가산하므로 아래 두 줄만 추가한다:

1. import 블록에 한 줄 추가:
```python
from app.routers import research  # ← 추가
```
2. 파일 말미에 한 줄 추가:
```python
research.init_research(app)  # ← 추가 (라우터 include + 자동모드 훅; 계약 6번)
```

> 기존 `main.py`(health·claude_check)와 Plan ②의 lifespan 가산은 그대로 두고 위 두 줄만 얹는다. `init_research(app)`는 라우터 include만 하는 파일 말미의 독립 호출이라 lifespan 가산과 충돌하지 않는다. **스케줄러 start/stop은 Plan ②의 단일 lifespan이 `start_scheduler(app)`/`stop_scheduler(app)`로 호출**(계약 6a)하며, 그 스케줄러가 참조하는 `app.state.db`도 같은 lifespan이 채운다(계약 7번). `add_event_handler`는 커스텀 lifespan에 무시되므로 ④는 쓰지 않는다.

> `pyproject.toml`·`Dockerfile`은 **손대지 않는다** — `apscheduler`·`httpx`는 계약 2·3번에서 Plan ②가 소유·설치한다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && pip install -e ".[dev]" && python -m pytest -q`
Expected: PASS(전체 그린 — 기존 walking-skeleton 테스트 + research 테스트). *`app.db`가 아직 없으면 이 태스크는 Plan ② 머지 후 재실행.*

- [ ] **Step 5: 커밋**

```bash
git add backend/app/routers backend/app/main.py backend/tests/test_research_router.py
git commit -m "feat(research): 비동기 트리거 라우터(202 전 running upsert) + main.py mount"
```

---

## Task 6: 자동모드 스케줄러 (APScheduler, 비활성) (`scheduler.py`)

**Files:**
- Create: `backend/app/research/scheduler.py`, `backend/tests/test_research_scheduler.py`

> **계약 6a(중요):** 스케줄러는 **`add_event_handler`로 등록하지 않는다**. `main.py`엔 Plan ②의 **단일 lifespan**만 있고, Starlette는 커스텀 lifespan이 있으면 `add_event_handler("startup"/"shutdown")`를 **무시**하므로 자동모드가 조용히 안 뜬다. 대신 lifespan이 직접 호출할 **`start_scheduler(app)`/`stop_scheduler(app)`** 함수(멱등, `RESEARCH_AUTO_ENABLED=false`면 no-op)를 제공한다.

**Interfaces:**
- Produces:
  - `start_scheduler(app) -> None` — 계약 6a: Plan ②의 lifespan이 startup에서 호출. **멱등**(이미 시작됐으면 재시작 안 함), `RESEARCH_AUTO_ENABLED=false`면 **no-op**. true면 interval 잡 1개로 `AsyncIOScheduler`를 시작하고 `app.state.research_scheduler`에 보관.
  - `stop_scheduler(app) -> None` — 계약 6a: lifespan의 finally에서 호출. **멱등**(스케줄러 없으면 no-op), 있으면 `shutdown(wait=False)` 후 `app.state.research_scheduler=None`.
  - `async def tick(get_pool)` — pending 회사/공고를 limit만큼 리서치(자동모드 잡 본체).

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_research_scheduler.py` (계약 6a: **lifespan 컨텍스트**(`with TestClient(app)`)에서 start/stop 훅을 검증. **bare `FastAPI()`로 startup을 흉내내지 않는다** — Plan ②의 단일 lifespan이 `start_scheduler`/`stop_scheduler`를 호출하는 경로를 그대로 재현):
```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.research import scheduler


def _app_with_scheduler_lifespan():
    """Plan ②의 단일 lifespan을 재현: startup→start_scheduler, shutdown→stop_scheduler."""

    @asynccontextmanager
    async def lifespan(app):
        app.state.db = object()          # tick이 참조(테스트에선 30분 잡 미발화)
        scheduler.start_scheduler(app)
        try:
            yield
        finally:
            scheduler.stop_scheduler(app)

    return FastAPI(lifespan=lifespan)


def test_disabled_by_default_is_noop(monkeypatch):
    monkeypatch.setattr(scheduler, "RESEARCH_AUTO_ENABLED", False)
    app = _app_with_scheduler_lifespan()
    with TestClient(app):                # lifespan startup/shutdown 실행
        assert app.state.research_scheduler is None   # no-op


def test_enabled_starts_and_stops_in_lifespan(monkeypatch):
    monkeypatch.setattr(scheduler, "RESEARCH_AUTO_ENABLED", True)
    monkeypatch.setattr(scheduler, "RESEARCH_AUTO_INTERVAL_MIN", 30)
    app = _app_with_scheduler_lifespan()
    with TestClient(app):
        sched = app.state.research_scheduler
        assert sched is not None
        assert sched.running
        assert len(sched.get_jobs()) == 1
    assert app.state.research_scheduler is None        # 컨텍스트 종료 시 stop


def test_start_scheduler_is_idempotent(monkeypatch):
    monkeypatch.setattr(scheduler, "RESEARCH_AUTO_ENABLED", True)
    monkeypatch.setattr(scheduler, "RESEARCH_AUTO_INTERVAL_MIN", 30)
    app = _app_with_scheduler_lifespan()
    with TestClient(app):
        first = app.state.research_scheduler
        scheduler.start_scheduler(app)   # 두 번째 호출 — 멱등(같은 스케줄러 유지, 잡 중복 없음)
        assert app.state.research_scheduler is first
        assert len(first.get_jobs()) == 1


async def test_tick_processes_pending(monkeypatch):
    calls = []

    async def pending_companies(db, limit):
        return ["토스"]

    async def pending_jobs(db, limit):
        return [("wanted", "42")]

    async def research_company(db, company, **kw):
        calls.append(("company", company))

    async def research_job(db, source, job_id, **kw):
        calls.append(("job", source, job_id))

    monkeypatch.setattr(scheduler.store, "pending_companies", pending_companies)
    monkeypatch.setattr(scheduler.store, "pending_jobs", pending_jobs)
    monkeypatch.setattr(scheduler.runner, "research_company", research_company)
    monkeypatch.setattr(scheduler.runner, "research_job", research_job)

    await scheduler.tick(lambda: object())
    assert calls == [("company", "토스"), ("job", "wanted", "42")]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && python -m pytest tests/test_research_scheduler.py -q`
Expected: FAIL — `ModuleNotFoundError: app.research.scheduler`

- [ ] **Step 3: 구현**

`backend/app/research/scheduler.py`:
```python
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.research import runner, store
from app.research.config import (
    RESEARCH_AUTO_ENABLED,
    RESEARCH_AUTO_INTERVAL_MIN,
    RESEARCH_AUTO_LIMIT,
)

log = logging.getLogger("research.scheduler")


async def tick(get_pool) -> None:
    """미리서치 대상 회사/공고를 limit만큼 처리(자동모드 잡 본체)."""
    db = get_pool()
    for company in await store.pending_companies(db, RESEARCH_AUTO_LIMIT):
        await runner.research_company(db, company)
    for source, job_id in await store.pending_jobs(db, RESEARCH_AUTO_LIMIT):
        await runner.research_job(db, source, job_id)


def start_scheduler(app) -> None:
    """계약 6a: Plan ②의 단일 lifespan이 startup에서 호출.

    **멱등**(이미 시작됐으면 그대로 반환) · `RESEARCH_AUTO_ENABLED=false`면 **no-op**.
    `add_event_handler`를 쓰지 않는다 — 커스텀 lifespan이 있으면 Starlette가 무시하므로.
    자동모드가 켜져 있으면 interval 잡 1개로 스케줄러를 시작해 `app.state`에 보관한다.
    """
    if getattr(app.state, "research_scheduler", None) is not None:
        return  # 멱등: 이미 시작됨
    if not RESEARCH_AUTO_ENABLED:
        app.state.research_scheduler = None
        log.info("research auto-mode disabled (RESEARCH_AUTO_ENABLED=false)")
        return
    sched = AsyncIOScheduler()
    # tick은 get_pool()로 풀을 얻는다 → app.state.db(Plan ② lifespan이 채움)를 지연 참조.
    sched.add_job(
        tick, "interval", minutes=RESEARCH_AUTO_INTERVAL_MIN,
        args=[lambda: app.state.db],
    )
    sched.start()
    app.state.research_scheduler = sched
    log.info("research auto-mode enabled: every %d min", RESEARCH_AUTO_INTERVAL_MIN)


def stop_scheduler(app) -> None:
    """계약 6a: lifespan의 finally에서 호출. **멱등** — 스케줄러 없으면 no-op."""
    sched = getattr(app.state, "research_scheduler", None)
    if sched is not None:
        sched.shutdown(wait=False)
        app.state.research_scheduler = None
```

> `app.state.db`는 Plan ②의 lifespan이 채운다. 자동모드가 꺼져 있으면 `start_scheduler`는 잡을 걸지 않아 `app.state.db`를 참조하지 않는다(no-op) → Plan ② 유무와 무관하게 안전. `start_scheduler`/`stop_scheduler`는 **Plan ②의 단일 lifespan이 직접 호출**하므로 `add_event_handler`가 필요 없다(계약 6a).

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_research_scheduler.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/research/scheduler.py backend/tests/test_research_scheduler.py
git commit -m "feat(research): APScheduler 자동모드(기본 비활성)"
```

---

## Task 7: 관리용 CLI (`__main__.py`)

**Files:**
- Create: `backend/app/research/__main__.py`, `backend/tests/test_research_cli.py`

**Interfaces:**
- Produces: `python -m app.research (--company X | --job source:id | --pending-companies | --pending-jobs) [--limit N] [--force]`. 동일 러너 재사용, 자동모드 없이 수동만. DB 풀은 `app.db.connect()/close()`(Plan ②).

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_research_cli.py`:
```python
from app.research.__main__ import build_parser, dispatch


def test_parser_job_splits_source_id():
    args = build_parser().parse_args(["--job", "wanted:42", "--force"])
    assert args.job == "wanted:42" and args.force is True


def test_parser_pending_with_limit():
    args = build_parser().parse_args(["--pending-companies", "--limit", "3"])
    assert args.pending_companies is True and args.limit == 3


async def test_dispatch_company(monkeypatch):
    calls = []

    async def rc(db, company, url="", *, force=False):
        calls.append(("company", company, force))
        return "done"

    monkeypatch.setattr("app.research.__main__.runner.research_company", rc)
    args = build_parser().parse_args(["--company", "토스", "--force"])
    await dispatch(object(), args)
    assert calls == [("company", "토스", True)]


async def test_dispatch_job_splits(monkeypatch):
    calls = []

    async def rj(db, source, job_id, *, force=False):
        calls.append((source, job_id, force))
        return "done"

    monkeypatch.setattr("app.research.__main__.runner.research_job", rj)
    args = build_parser().parse_args(["--job", "wanted:42"])
    await dispatch(object(), args)
    assert calls == [("wanted", "42", False)]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && python -m pytest tests/test_research_cli.py -q`
Expected: FAIL — `ModuleNotFoundError: app.research.__main__`

- [ ] **Step 3: 구현**

`backend/app/research/__main__.py`:
```python
import argparse
import asyncio

from app.research import runner, store


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.research")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--company", help="기업 리서치할 회사명")
    g.add_argument("--job", help="공고 리서치. 형식 source:job_id")
    g.add_argument("--pending-companies", action="store_true", help="미리서치 회사 일괄")
    g.add_argument("--pending-jobs", action="store_true", help="미리서치 공고 일괄")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--force", action="store_true")
    return p


async def dispatch(db, args) -> None:
    if args.company:
        print(await runner.research_company(db, args.company, force=args.force))
    elif args.job:
        source, job_id = args.job.split(":", 1)
        print(await runner.research_job(db, source, job_id, force=args.force))
    elif args.pending_companies:
        for company in await store.pending_companies(db, args.limit):
            print(company, await runner.research_company(db, company, force=args.force))
    elif args.pending_jobs:
        for source, job_id in await store.pending_jobs(db, args.limit):
            print(source, job_id, await runner.research_job(db, source, job_id, force=args.force))


async def _amain(args) -> None:
    from app.db import connect, close  # Plan ② 제공

    pool = await connect()
    try:
        await dispatch(pool, args)
    finally:
        await close(pool)


def main() -> None:
    asyncio.run(_amain(build_parser().parse_args()))


if __name__ == "__main__":
    main()
```

> `connect/close` import는 `_amain` 안에 둬서 파서/`dispatch` 단위테스트가 `app.db`(Plan ②) 없이도 돈다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_research_cli.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/research/__main__.py backend/tests/test_research_cli.py
git commit -m "feat(research): 관리용 CLI(python -m app.research)"
```

---

## Task 8: 프론트 리서치 패널 + 트리거 API (`researchApi.ts`, `ResearchPanel.tsx`)

**Files:**
- Create: `frontend/src/researchApi.ts`, `frontend/src/ResearchPanel.tsx`, `frontend/src/ResearchPanel.test.tsx`

**Interfaces:**
- Produces: `postCompanyResearch(company, force?)`, `postJobResearch(source, jobId, force?)`; `<ResearchPanel source jobId companyResearch jobResearch refetch trigger? pollMs? />`.
- Consumes(Plan ③): 상세 뷰가 `refetch = () => getJob(source, jobId)`(반환 `{companyResearch, jobResearch}`)와 초기 research를 props로 주입. 상세 뷰에는 **`<ResearchPanel/>` import 한 줄**만 얹는다.

- [ ] **Step 1: 실패하는 테스트 작성**

`frontend/src/ResearchPanel.test.tsx`:
```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, test, expect } from "vitest";
import { ResearchPanel } from "./ResearchPanel";

test("shows existing research", () => {
  render(
    <ResearchPanel
      source="wanted"
      jobId="42"
      companyResearch={{ status: "done", overview: "핀테크" }}
      jobResearch={{ status: "done", tech_detail: "Spring 기반" }}
      refetch={vi.fn()}
    />,
  );
  expect(screen.getByText(/핀테크/)).toBeTruthy();
  expect(screen.getByText(/Spring 기반/)).toBeTruthy();
});

test("triggers research and polls until done", async () => {
  const trigger = vi.fn().mockResolvedValue({ status: "running" });
  const refetch = vi
    .fn()
    .mockResolvedValueOnce({
      companyResearch: { status: "running" },
      jobResearch: { status: "running" },
    })
    .mockResolvedValueOnce({
      companyResearch: { status: "done", overview: "핀테크" },
      jobResearch: { status: "done", tech_detail: "Spring 기반" },
    });

  render(
    <ResearchPanel
      source="wanted"
      jobId="42"
      companyResearch={null}
      jobResearch={null}
      refetch={refetch}
      trigger={trigger}
      pollMs={0}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: /리서치/ }));
  expect(trigger).toHaveBeenCalledWith("wanted", "42");
  await waitFor(() => expect(screen.getByText(/Spring 기반/)).toBeTruthy());
});
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd frontend && npm test -- ResearchPanel`
Expected: FAIL — `Cannot find module './ResearchPanel'`

- [ ] **Step 3: 구현**

`frontend/src/researchApi.ts`:
```ts
export async function postCompanyResearch(company: string, force = false) {
  const r = await fetch("/api/research/company", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ company, force }),
  });
  if (!r.ok) throw new Error("company research trigger failed");
  return r.json();
}

export async function postJobResearch(source: string, jobId: string, force = false) {
  const r = await fetch("/api/research/job", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source, job_id: jobId, force }),
  });
  if (!r.ok) throw new Error("job research trigger failed");
  return r.json();
}
```

`frontend/src/ResearchPanel.tsx`:
```tsx
import { useState } from "react";
import { postJobResearch } from "./researchApi";

type Research = {
  status?: string;
  overview?: string;
  stability?: string;
  tech_detail?: string;
  role_detail?: string;
  sources?: string[];
} | null;

type RefetchResult = { companyResearch: Research; jobResearch: Research };

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function ResearchPanel({
  source,
  jobId,
  companyResearch,
  jobResearch,
  refetch,
  trigger = postJobResearch,
  pollMs = 2000,
}: {
  source: string;
  jobId: string;
  companyResearch: Research;
  jobResearch: Research;
  refetch: () => Promise<RefetchResult>;
  trigger?: (source: string, jobId: string) => Promise<unknown>;
  pollMs?: number;
}) {
  const [cr, setCr] = useState<Research>(companyResearch);
  const [jr, setJr] = useState<Research>(jobResearch);
  const [busy, setBusy] = useState(false);

  const done = (r: Research) => r?.status === "done" || r?.status === "failed";

  async function onResearch() {
    setBusy(true);
    try {
      await trigger(source, jobId);
      for (let i = 0; i < 60; i++) {
        await sleep(pollMs);
        const fresh = await refetch();
        setCr(fresh.companyResearch);
        setJr(fresh.jobResearch);
        if (done(fresh.jobResearch)) break;
      }
    } finally {
      setBusy(false);
    }
  }

  const hasResearch = jr && jr.status !== "running";

  return (
    <section>
      <h2>🔍 리서치</h2>
      {cr?.overview && (
        <p>
          <strong>기업 개요:</strong> {cr.overview}
        </p>
      )}
      {cr?.stability && (
        <p>
          <strong>안정성:</strong> {cr.stability}
        </p>
      )}
      {jr?.tech_detail && (
        <p>
          <strong>기술·문화:</strong> {jr.tech_detail}
        </p>
      )}
      {jr?.role_detail && (
        <p>
          <strong>직무:</strong> {jr.role_detail}
        </p>
      )}
      {jr?.sources && jr.sources.length > 0 && (
        <ul>
          {jr.sources.map((u) => (
            <li key={u}>
              <a href={u}>{u}</a>
            </li>
          ))}
        </ul>
      )}
      {!hasResearch && (
        <button onClick={onResearch} disabled={busy}>
          {busy ? "리서치 중…" : "리서치 실행"}
        </button>
      )}
    </section>
  );
}
```

> Plan ③ 상세 뷰에는 다음 한 줄만 추가:
> ```tsx
> <ResearchPanel source={source} jobId={jobId} companyResearch={data.companyResearch}
>   jobResearch={data.jobResearch} refetch={() => getJob(source, jobId)} />
> ```

- [ ] **Step 4: 테스트·빌드 통과 확인**

Run: `cd frontend && npm test && npm run build`
Expected: 테스트 PASS + `dist/` 생성

- [ ] **Step 5: 커밋**

```bash
git add frontend/src/researchApi.ts frontend/src/ResearchPanel.tsx frontend/src/ResearchPanel.test.tsx
git commit -m "feat(frontend): 리서치 열람/트리거 패널(폴링)"
```

---

## Task 9: A1 라이브 배포 + 실제 리서치 E2E (★게이트 · controller 확인 필요)

코드 변경 없음(검증·배포). 라이브 인프라를 건드리는 단계는 **controller 확인 필요**로 표시한다.

**전제(Plan ② 소유, controller 확인 필요):**
- career-agent Postgres(pgvector)가 A1에 떠 있고 `company_research`·`job_research` 테이블·`jobs` 데이터가 존재.
- **데이터 이전(기존 n8n Postgres → career-agent Postgres)·n8n 재연결(`DB_POSTGRESDB_HOST` 변경)** 은 Plan ②의 DB 마이그레이션 태스크가 수행. Plan ④는 그 결과 위에서 검증만 한다. **이 두 라이브 변경은 controller 확인 필요.**

- [ ] **Step 1: `.env`에 리서치 설정 추가 (A1, controller 확인 필요)**

A1 `/home/ubuntu/career-agent/.env`에 아래 추가(값·웹훅은 controller가 제공/확인):
```
DISCORD_WEBHOOK_URL=<기존 n8n과 동일 웹훅 재사용>
RESEARCH_MODEL=
RESEARCH_AUTO_ENABLED=false
```
Expected: `.env`에 반영(커밋 금지 — `.gitignore`).

- [ ] **Step 2: push → Jenkins 배포 (기존 CI/CD 체인)**

```bash
cd /Users/sunny/career-agent && git push origin main
```
Jenkins가 폴링(≤3분)해 빌드→`docker compose up -d --build`→smoke. 완료 후:
```bash
ssh a1 'cd /home/ubuntu/career-agent && git rev-parse --short HEAD'   # push 커밋과 일치
ssh a1 'sudo docker compose ps'                                       # backend·nginx Up
```
Expected: Jenkins SUCCESS, A1 HEAD 일치, 컨테이너 Up. **배포는 라이브 변경 — controller 확인 필요.**

- [ ] **Step 3: 실제 기업 리서치 1건 E2E (구독 인증 웹검색)**

기존 `jobs`에서 실제 회사 하나로 트리거(호스트명·값은 controller 확인):
```bash
ssh a1 'curl -s -X POST http://localhost:80/api/research/company \
  -H "Content-Type: application/json" -d "{\"company\":\"<실제회사>\"}"'
```
Expected: `202 {"status":"running","company":"<실제회사>"}`. 10~60초 후 DB 확인:
```bash
ssh a1 'sudo docker exec <pg컨테이너> psql -U <user> -d jobs -t -c \
  "SELECT status, left(overview,40) FROM company_research WHERE company='"'"'<실제회사>'"'"';"'
```
Expected: `status=done` + overview 채워짐 + Discord에 "🏢 기업 리서치 완료" 도착. **DB·컨테이너 접근 — controller 확인 필요.**

- [ ] **Step 4: 실제 공고 리서치 1건 E2E (기업 선행 확인)**

```bash
ssh a1 'curl -s -X POST http://localhost:80/api/research/job \
  -H "Content-Type: application/json" -d "{\"source\":\"<src>\",\"job_id\":\"<id>\"}"'
```
Expected: `202`. 완료 후 `job_research`에 `status=done` + `tech_detail`/`role_detail` 채워짐, Discord 푸시. (없는 공고면 404 확인.)

- [ ] **Step 5: 프론트 열람/트리거 E2E (Access 뒤)**

브라우저 `https://agent.chs135.com` → Google 로그인 → 공고 상세에서 리서치 표시 확인, 미리서치 공고는 "리서치 실행" 버튼 → "리서치 중…" → 폴링 완료 후 개요·기술·직무·근거 링크 표시.
Expected: 트리거→폴링→표시 흐름 정상.

- [ ] **Step 6: n8n 09 DB 뷰어 비활성화 (controller 확인 필요)**

이 프론트가 09 뷰어를 대체하므로 n8n 09 워크플로우를 `active=false`로만 전환(삭제 금지, 가역). **라이브 n8n 변경 — controller 확인 필요.**

- [ ] **Step 7: 자동모드는 비활성 유지(문서화)**

`RESEARCH_AUTO_ENABLED=false` 확인. 활성화 시점·주기는 이후 결정(설계 스펙 "자동모드 활성화 시점" 미해결 항목). 지금은 프론트 버튼·CLI 수동만.

---

## 완료 기준 (Plan ④ Done)

- `company_research`·`job_research` 캐싱이 running→done/failed로 동작하고 **force 재리서치**가 된다.
- 트리거는 **202 즉시 응답 + BackgroundTask**로 비동기 실행되고, 완료 시 **Discord 푸시**가 온다.
- 공고 리서치가 **기업 리서치를 자동 선행**(캐시되면 skip)하고 개요를 컨텍스트로 재사용한다.
- 프론트에서 리서치 **열람·트리거·폴링**이 되고, `main.py`는 **두 줄 추가**로 격리됐다.
- APScheduler 자동모드는 **구현됐지만 꺼져 있다**.
- 라이브(데이터 이전·n8n 재연결·배포·n8n 09 비활성화)는 **controller 확인 필요**로 표시·수행됐다.
