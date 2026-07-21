# career-agent 플랜 ②③④ 정본 계약 (Reconciliation Contract)

병렬 작성된 3개 플랜의 인터페이스 충돌을 없애기 위한 **단일 정본**. 각 플랜은 이 계약에 맞춰 수정한다. 충돌 시 이 문서가 우선한다.

## 1. DB 접근 계층 = asyncpg (SQLAlchemy 아님, 런타임)

`backend/app/db.py`가 제공하는 정본 인터페이스:
```python
import asyncpg
from fastapi import Request

async def connect() -> asyncpg.Pool:
    import os
    return await asyncpg.create_pool(dsn=os.environ["DATABASE_URL"], min_size=1, max_size=10)

async def close(pool: asyncpg.Pool) -> None:
    await pool.close()

async def get_conn(request: Request):
    async with request.app.state.db.acquire() as conn:
        yield conn
```
- `main.py`는 lifespan(또는 startup/shutdown)에서 `app.state.db = await connect()` / `await close(app.state.db)`.
- 모든 런타임 SQL은 **asyncpg**: `conn.fetch(...)`, `conn.fetchrow(...)`, `conn.fetchval(...)`, `conn.execute(...)`, 위치 파라미터 `$1,$2`.
- `DATABASE_URL` = `postgresql://n8n:<pw>@postgres:5432/jobs` (컨테이너 네트워크; A1에선 공유 네트워크의 postgres).
- **마이그레이션만 Alembic**(SQLAlchemy는 마이그레이션 전용 의존). 런타임 앱은 asyncpg만 사용. Alembic 동기 URL은 `postgresql+psycopg://...`를 별도(예: `ALEMBIC_URL`)로.

라우터/러너는 `from app.db import get_conn`(FastAPI Depends)로 conn을 받는다. 테스트는 `app.dependency_overrides[get_conn]`를 쓰고 **finally에서 clear**한다(전역 오염 금지).

## 2. pyproject 의존성 (정본 — Plan ②가 소유, ③④는 손대지 않음)

```toml
dependencies = [
  "fastapi>=0.115", "uvicorn[standard]>=0.32",
  "asyncpg>=0.30", "alembic>=1.13", "sqlalchemy>=2.0",
  "httpx>=0.27", "apscheduler>=3.10",
]
[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.24", "httpx>=0.27"]
```
- Plan ③: pyproject/Dockerfile **손대지 않음**.
- Plan ④: pyproject **손대지 않음**(httpx·apscheduler 이미 포함됨).

## 3. Dockerfile (Plan ②) — deps 명시 설치 후 COPY app

```dockerfile
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn[standard]>=0.32" \
    "asyncpg>=0.30" "alembic>=1.13" "sqlalchemy>=2.0" "httpx>=0.27" "apscheduler>=3.10"
COPY app ./app
```
`pip install .`(editable/비editable) 방식 금지(빌드단계 패키지탐색 위험). deps 명시 설치.

## 4. jobs 스키마 컬럼 (정본 — n8n init.sql 기준)

`jobs`: `source, job_id, company, title, url, min_career, max_career, tech_stacks (text[]), locations (**TEXT 스칼라**), summary, status, attempts, collected_at, updated_at, closed_at, embedding vector(1024)`.
- 컬럼명 **`locations`, `collected_at`** 사용(`location`/`created_at` 금지).
- **[정정] `locations`는 배열이 아니라 `TEXT` 스칼라**(실제 n8n init.sql이 `locations TEXT`, 수집기가 스칼라 문자열 저장). `tech_stacks`만 `text[]`.
  - 백엔드: asyncpg가 str 반환. 필터는 `locations ILIKE $1`(CAST 불필요).
  - 프론트: 타입 `locations: string`(또는 null). **`.join` 금지** — 그대로 문자열 렌더.
- `UNIQUE(source, job_id)`.

## 5. API 응답 형태 (정본)

`GET /api/jobs` (필터 status·source·location·tech·keyword, limit/offset):
```json
{ "items": [ { "source","job_id","company","title","url","locations","min_career","max_career","status","collected_at",
               "has_company_research": true, "has_job_research": false } ],
  "total": 123, "limit": 50, "offset": 0 }
```
→ 리스트 아이템마다 **리서치 존재 플래그 포함**(스펙 요구).

`GET /api/jobs/{source}/{job_id}` (상세 — **리서치 본문 합본**, LEFT JOIN):
```json
{ "job": { ...전체 job 컬럼... },
  "companyResearch": { "overview","stability","sources","status","researched_at" } | null,
  "jobResearch": { "tech_detail","role_detail","sources","status","researched_at" } | null }
```
- **Plan ③가 이 상세 엔드포인트를 생산**(company_research·job_research LEFT JOIN). Plan ④는 이 형태를 **소비**만.
- 404: 공고 없으면.

프론트 API 클라이언트: **`frontend/src/api.ts`**(신규 jobsApi.ts 금지 — 기존 api.ts 확장). 시그니처:
```ts
export async function getJobs(f: JobsFilters): Promise<JobsPage>
export async function getJob(source: string, jobId: string): Promise<{ job: Job; companyResearch: CompanyResearch|null; jobResearch: JobResearch|null }>
```
Plan ④는 `import { getJob } from "./api"`로 소비.

## 6. main.py (가산 편집 — 전체 파일 교체 금지)

각 플랜은 **자기 줄만 추가**(edit):
- Plan ②: lifespan 추가(app.state.db 풀 connect/close) + `app.include_router(db_router)`.
- Plan ③: `app.include_router(jobs_router)`.
- Plan ④: `app.include_router(research_router)` + `init_research(app)`.
`routers/__init__.py`(빈 파일)는 누가 만들어도 동일 → 무해.

### 6a. 단일 lifespan이 스케줄러도 소유 (add_event_handler 금지)

`main.py`에 **lifespan 하나만** 둔다(Plan ②가 작성). Starlette는 커스텀 lifespan이 있으면 `add_event_handler("startup"/"shutdown")`를 **무시**하므로, Plan ④ 스케줄러는 반드시 lifespan이 호출해야 한다.
- Plan ④는 `start_scheduler(app)` / `stop_scheduler(app)` 함수를 제공(멱등, `RESEARCH_AUTO_ENABLED` false면 no-op). **`add_event_handler` 금지.**
- Plan ②의 lifespan:
  ```python
  @asynccontextmanager
  async def lifespan(app):
      app.state.db = await db.connect()
      try:
          from app.research.scheduler import start_scheduler, stop_scheduler
          start_scheduler(app)          # ④ 제공, 기본 no-op
          yield
      finally:
          stop_scheduler(app)
          await db.close(app.state.db)
  ```
  (④ 미구현 시점엔 import를 try/except로 감싸도 됨. ④ 머지 후 활성.)
- ④ 테스트도 lifespan 컨텍스트(`TestClient(app) as client`)에서 스케줄러 훅을 검증(bare FastAPI() 금지).

## 7. 리서치 트리거 (Plan ④) — 202 전 running upsert

`POST /api/research/{company,job}`: 리서치행을 `status='running'`으로 **먼저 upsert**한 뒤 BackgroundTask 등록, 즉시 202. (스펙 "running 즉시 표기" 준수 — 폴링이 즉시 running을 봄.)
scheduler의 `app.state.db`는 Plan ②의 lifespan 풀에서 온다(정본 lifespan이 채움).
`run_claude` 시그니처(정본, walking-skeleton Task1): `async def run_claude(prompt, *, allowed_tools="", timeout=120, claude_bin="claude") -> str` — result 텍스트 반환. 그대로 사용.

## 8. Plan ② 라이브 태스크 버그 수정

- **.env**: walking-skeleton이 이미 A1에 `.env`(HOST_UID만) 생성함. `test -f .env || cp` 금지(no-op). 대신 **기존 .env에 DB 변수 append**:
  ```bash
  grep -q '^DATABASE_URL=' /home/ubuntu/career-agent/.env || cat >> /home/ubuntu/career-agent/.env <<EOF
  POSTGRES_USER=n8n
  POSTGRES_PASSWORD=<n8n DB 비번, controller가 n8n .env에서 주입>
  POSTGRES_DB=jobs
  DATABASE_URL=postgresql://n8n:<pw>@postgres:5432/jobs
  JOBS_RO_PASSWORD=<controller 주입>
  EOF
  ```
  값은 화면 노출 금지, controller가 n8n .env에서 주입.
- **n8n 재연결**: `docker compose up -d --no-deps n8n` (plain `up -d n8n` 금지 — depends_on으로 구 postgres 재기동 → `postgres` 별칭 이중해석·데이터 갈라짐).
- **Jenkinsfile smoke**: 현재 smoke는 `docker compose exec -T nginx wget -qO- http://127.0.0.1/...` + 재시도 루프로 진화함(IPv6·부팅레이스 fix). **되돌리지 말 것**. DB 헬스체크는 같은 nginx-exec wget 형태로 **가산**.
- **compose**: 전체 교체 금지 — Postgres 서비스·공유 네트워크를 **가산**(기존 backend claude 마운트·nginx 보존).

## 9. 슬라이스 경계 (스펙 대비 의도적 연기)

- "리서치 완료만" 토글은 Plan ④.
- 리스트 레벨 리서치 플래그는 Plan ③(위 5번에 포함 — 조용히 빼지 말 것).
