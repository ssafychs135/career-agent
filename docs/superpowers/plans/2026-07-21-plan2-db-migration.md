# career-agent Plan ② — DB 소유권 이전 (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 n8n Postgres(`jobs` DB, pgvector)를 **career-agent 소유 Postgres로 이전**하고 n8n을 재연결해 **단일 소스**를 만든다. career-agent compose에 pgvector Postgres 서비스를 추가하고, 스키마 소유권을 **Alembic 마이그레이션**(기존 `jobs`·`applications` 스키마 베이스라인 흡수 + `company_research`·`job_research` 신규 + `jobs_ro` 읽기전용 롤)으로 이관한다. 백엔드는 이 DB에 **런타임 asyncpg 풀**(SQLAlchemy는 마이그레이션 전용 의존)로 접근하고, `GET /api/db/health`로 접속을 증명한다. 데이터 이전(pg_dump/restore)·n8n 재연결·검증·롤백은 라이브 태스크로 명시한다.

**Architecture:** career-agent compose가 `pgvector/pgvector:pg16` Postgres를 **소유**한다. 스키마는 career-agent가 소유(Alembic). `migrate` 원샷 서비스가 `alembic upgrade head`로 스키마를 세우고, `backend`가 그 위에서 async로 읽고, 리서치 테이블에 쓴다. n8n은 **공유 external 도커 네트워크**에서 career-agent Postgres를 별칭 `postgres`로 만나 **기존 Postgres 자격증명 변경 없이** 재연결된다. n8n **자체 상태는 SQLite(존치)** — 이전 대상은 도메인 데이터(Postgres)뿐.

> **스펙 정합 주석(중요):** 설계 스펙은 "n8n `DB_POSTGRESDB_HOST` 재연결"이라 적었으나, 실제 n8n(`n8n-pjt`)은 자기 상태를 **SQLite**(`./data/n8n`)에 두고 `jobs` Postgres에는 **워크플로우의 Postgres 자격증명(Host: `postgres`, port 5432)**으로 접속한다(`DB_POSTGRESDB_*`는 미사용). 따라서 재연결의 실제 지점은 그 **자격증명이 가리키는 `postgres` 호스트의 해석 대상**이다. 이 플랜은 career-agent Postgres를 공유 네트워크에서 별칭 `postgres`로 노출해 **자격증명을 손대지 않고** 재연결한다(가장 결합이 적고 가역적). host:5432 방식은 폴백으로 문서화.

**Tech Stack:** Python 3.12 · FastAPI · asyncpg(런타임 풀) · Alembic + SQLAlchemy(마이그레이션 전용) · pytest / PostgreSQL 16 + pgvector(HNSW) · Docker Compose / (기존) Jenkins · cloudflared

## Global Constraints

- 레포 루트: `/Users/sunny/career-agent` (원격 `ssafychs135/career-agent`). n8n 레포: `/Users/sunny/n8n-pjt`(원격 별도) — 라이브 재연결 태스크에서만 편집.
- **선행:** Walking Skeleton 플랜(`2026-07-21-walking-skeleton.md`) 완료 — backend 컨테이너·nginx·docker-compose·Jenkins 배포 체인이 이미 있음. 이 플랜은 그 위에 Postgres·마이그레이션·DB 라우터를 얹는다.
- 배포 대상: A1 서버(ssh alias `a1`), career-agent 경로 `/home/ubuntu/career-agent`, n8n 경로 `/home/ubuntu/n8n-pjt`(기존). Docker/Jenkins 기존 스택 재사용.
- **결합 최소화:** 백엔드 신규 엔드포인트는 **별도 라우터 파일**(`app/routers/db.py`). `main.py`에는 `include_router` **한 줄만** 추가(다른 플랜과 병렬 구현 시 충돌 최소화).
- **PG 메이저 버전 고정 = 16**(기존 `pgvector/pgvector:pg16`와 일치). 벡터 컬럼 `vector(1024)`·HNSW(`vector_cosine_ops`)·`jobs_ro` 롤·`Asia/Seoul` 타임존을 **반드시 재현**.
- 시크릿(POSTGRES_PASSWORD·JOBS_RO_PASSWORD·DISCORD_WEBHOOK_URL)은 `.env`로만 주입, 화면 출력·커밋 금지(`.gitignore`).
- **라이브 인프라 변경(데이터 이전·n8n 재연결·구 DB 은퇴)** 태스크는 제목에 **[LIVE — controller 확인 필요]** 표기. 실행 전 컨트롤러 승인. 컷오버 전 **pg_dump 백업 필수**, 원본 무손상 유지(즉시 롤백 가능).
- 커밋 메시지 말미:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

## File Structure

```
career-agent/
├─ backend/
│  ├─ app/
│  │  ├─ db.py                    # ← asyncpg 풀(connect/close/get_conn) (신규)
│  │  ├─ routers/__init__.py      # ← (신규)
│  │  ├─ routers/db.py            # ← GET /api/db/health (신규, 별도 라우터)
│  │  ├─ main.py                  # ← include_router 한 줄 추가 (기존)
│  │  └─ claude_client.py         # (기존, 불변)
│  ├─ alembic.ini                 # ← (신규)
│  ├─ migrations/
│  │  ├─ env.py                   # ← async Alembic env (신규)
│  │  ├─ script.py.mako           # ← (신규, alembic 표준)
│  │  └─ versions/
│  │     ├─ 0001_baseline_jobs.py     # ← 기존 jobs·applications 스키마 흡수 (신규)
│  │     └─ 0002_research_tables.py   # ← company_research·job_research + jobs_ro grant (신규)
│  ├─ tests/
│  │  ├─ test_db.py               # ← (신규)
│  │  └─ test_db_router.py        # ← (신규)
│  ├─ pyproject.toml              # ← asyncpg(런타임)·alembic·sqlalchemy(마이그레이션)·httpx·apscheduler (기존)
│  └─ Dockerfile                  # ← alembic 파일 COPY + 런타임 deps 추가 (기존)
├─ db/
│  └─ 01-roles.sh                 # ← career-agent Postgres initdb: jobs_ro 롤 (신규)
├─ docker-compose.yml             # ← postgres·migrate 서비스 + 공유 네트워크 (기존)
├─ .env.example                   # ← DB 변수 문서화 (신규)
└─ deploy/
   └─ db-migration-runbook.md     # ← 라이브 컷오버 절차·롤백 기록 (신규)
```

각 파일 1책임: `db.py`=asyncpg 풀(connect/close/get_conn)만, `routers/db.py`=DB 헬스 라우팅만, `migrations/versions/*`=스키마 DDL만, `db/01-roles.sh`=롤 부트스트랩만.

---

## Task 1: 백엔드 asyncpg DB 레이어 (`app/db.py`) + 의존성

> **정본 계약 1번:** 런타임 DB 접근은 **asyncpg**(SQLAlchemy 아님). `db.py`는 `connect`/`close`/`get_conn`만 제공하고, `main.py`가 lifespan에서 `app.state.db` 풀을 채운다. 라우터/러너는 `from app.db import get_conn`(FastAPI Depends)로 conn을 받는다. SQLAlchemy는 **마이그레이션 전용 의존**(Task 2 Alembic env)일 뿐 런타임 앱은 asyncpg만 쓴다.

**Files:**
- Edit: `backend/pyproject.toml`
- Create: `backend/app/db.py`, `backend/tests/test_db.py`

**Interfaces:**
- Produces: `async def connect() -> asyncpg.Pool` (`DATABASE_URL` DSN으로 풀 생성), `async def close(pool: asyncpg.Pool) -> None`, `async def get_conn(request: Request)` (FastAPI Depends용 — `request.app.state.db`에서 conn acquire 후 yield). 위치 파라미터 `$1,$2`, `conn.fetch/fetchrow/fetchval/execute` 사용.

- [ ] **Step 1: `pyproject.toml`에 의존성 추가 (정본 계약 2번 전량)**

`backend/pyproject.toml` — `dependencies`와 `dev`를 아래로 교체(계약 2번 그대로):
```toml
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "asyncpg>=0.30",
  "alembic>=1.13",
  "sqlalchemy>=2.0",
  "httpx>=0.27",
  "apscheduler>=3.10",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.24", "httpx>=0.27"]
```
(나머지 `[project]`·`[tool.pytest.ini_options]` 섹션은 그대로 둔다. `sqlalchemy`는 Alembic 마이그레이션 전용, `httpx`·`apscheduler`는 플랜 ④가 소비 — 계약상 deps는 Plan ②가 소유하고 ③④는 손대지 않는다.)

- [ ] **Step 2: 실패하는 테스트 작성**

`backend/tests/test_db.py` (asyncpg 인터페이스 — 실 DB 없이 풀·의존성 배선만 단위 검증):
```python
from types import SimpleNamespace

import app.db as db


async def test_connect_uses_database_url(monkeypatch):
    seen = {}

    async def fake_create_pool(dsn, **kw):
        seen["dsn"] = dsn
        seen["kw"] = kw
        return "POOL"

    monkeypatch.setattr(db.asyncpg, "create_pool", fake_create_pool)
    monkeypatch.setenv("DATABASE_URL", "postgresql://n8n:pw@postgres:5432/jobs")
    pool = await db.connect()
    assert pool == "POOL"
    assert seen["dsn"] == "postgresql://n8n:pw@postgres:5432/jobs"
    assert seen["kw"]["min_size"] == 1 and seen["kw"]["max_size"] == 10


async def test_get_conn_yields_from_app_state():
    conn_obj = object()

    class FakeAcquire:
        async def __aenter__(self):
            return conn_obj

        async def __aexit__(self, *a):
            return False

    class FakePool:
        def acquire(self):
            return FakeAcquire()

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=FakePool())))
    gen = db.get_conn(request)
    got = await gen.__anext__()
    assert got is conn_obj
    await gen.aclose()
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `cd backend && pip install -e ".[dev]" && python -m pytest tests/test_db.py -q`
Expected: FAIL — `ModuleNotFoundError: app.db`.

- [ ] **Step 4: 구현 (정본 계약 1번 그대로)**

`backend/app/db.py`:
```python
import os

import asyncpg
from fastapi import Request


async def connect() -> asyncpg.Pool:
    """DATABASE_URL(asyncpg DSN)로 커넥션 풀 생성. main.py lifespan이 호출."""
    return await asyncpg.create_pool(
        dsn=os.environ["DATABASE_URL"], min_size=1, max_size=10
    )


async def close(pool: asyncpg.Pool) -> None:
    await pool.close()


async def get_conn(request: Request):
    """FastAPI Depends용 — 앱 풀(app.state.db)에서 conn을 빌려 yield."""
    async with request.app.state.db.acquire() as conn:
        yield conn
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_db.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: 커밋**

```bash
cd /Users/sunny/career-agent
git add backend/pyproject.toml backend/app/db.py backend/tests/test_db.py
git commit -m "feat(backend): asyncpg DB 레이어(connect·close·get_conn)·정본 deps"
```

---

## Task 2: Alembic 초기화 + 베이스라인 마이그레이션 (기존 jobs 스키마 흡수)

기존 `db/init.sql`(n8n-pjt)의 스키마를 **그대로** career-agent 마이그레이션이 소유하도록 흡수한다. 컬럼·인덱스·제약·pgvector·HNSW·타임존을 1:1 재현한다(n8n 워크플로우가 계속 의존).

**Files:**
- Create: `backend/alembic.ini`, `backend/migrations/env.py`, `backend/migrations/script.py.mako`, `backend/migrations/versions/0001_baseline_jobs.py`

**Interfaces:**
- Consumes: `DATABASE_URL`(런타임 asyncpg DSN) 또는 `ALEMBIC_URL`(마이그레이션 전용 override). env.py가 자체적으로 SQLAlchemy URL을 조립한다 — **런타임 `app.db`(asyncpg)에는 의존하지 않는다**(계약 1번: SQLAlchemy는 마이그레이션 전용).
- Produces: `alembic upgrade head` 시 `jobs`·`applications` 테이블 + `vector` 확장 + 인덱스(HNSW 포함)를 생성.

- [ ] **Step 1: alembic 설정 파일 작성**

`backend/alembic.ini`:
```ini
[alembic]
script_location = migrations
prepend_sys_path = .

[loggers]
keys = root,sqlalchemy,alembic
[handlers]
keys = console
[formatters]
keys = generic
[logger_root]
level = WARN
handlers = console
qualname =
[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine
[logger_alembic]
level = INFO
handlers =
qualname = alembic
[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic
[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

`backend/migrations/script.py.mako`:
```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

`backend/migrations/env.py` (마이그레이션 전용 — 런타임 asyncpg `app.db`에 의존 안 함):
```python
import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None  # DDL은 raw SQL(op.execute)로 소유 — autogenerate 미사용


def _alembic_url() -> str:
    """마이그레이션용 SQLAlchemy URL. ALEMBIC_URL이 있으면 우선(예: 동기 psycopg),
    없으면 런타임 DATABASE_URL(asyncpg DSN)을 SQLAlchemy async 드라이버 URL로 변환."""
    explicit = os.environ.get("ALEMBIC_URL")
    if explicit:
        return explicit
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_alembic_url().replace("+asyncpg", ""),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_alembic_url())
    async with engine.connect() as conn:
        await conn.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```
(런타임 앱 DSN은 `postgresql://`(asyncpg 풀이 직접 사용) → env.py가 SQLAlchemy async 드라이버용 `postgresql+asyncpg://`로 변환. 동기 psycopg를 쓰고 싶으면 `ALEMBIC_URL=postgresql+psycopg://...`를 별도 주입하면 이 함수가 그대로 사용한다.)

- [ ] **Step 2: 베이스라인 마이그레이션 작성 (init.sql 1:1 흡수)**

`backend/migrations/versions/0001_baseline_jobs.py`:
```python
"""baseline: 기존 n8n jobs·applications 스키마 흡수 (init.sql 1:1)

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-21
"""
from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN EXECUTE format("
        "'ALTER DATABASE %I SET timezone TO ''Asia/Seoul''', current_database()); END $$;"
    )
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
          id            BIGSERIAL PRIMARY KEY,
          source        TEXT        NOT NULL,
          job_id        TEXT        NOT NULL,
          company       TEXT,
          title         TEXT,
          url           TEXT,
          min_career    INT,
          max_career    INT,
          tech_stacks   TEXT[],
          locations     TEXT,
          summary       TEXT,
          status        TEXT        NOT NULL DEFAULT 'pending',
          attempts      INT         NOT NULL DEFAULT 0,
          notified_at   TIMESTAMPTZ,
          closed_at     TIMESTAMPTZ,
          collected_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
          embedding     vector(1024),
          UNIQUE (source, job_id)
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status       ON jobs (status);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_jobs_collected_at ON jobs (collected_at);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_jobs_source       ON jobs (source);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_jobs_notify       ON jobs (status, notified_at);")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_embedding "
        "ON jobs USING hnsw (embedding vector_cosine_ops);"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS applications (
          id            BIGSERIAL PRIMARY KEY,
          message_id    TEXT UNIQUE,
          company       TEXT,
          status        TEXT,
          email_subject TEXT,
          email_from    TEXT,
          summary       TEXT,
          received_at   TIMESTAMPTZ,
          notified_at   TIMESTAMPTZ,
          created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);")
    # jobs_ro 롤은 initdb(db/01-roles.sh)가 먼저 생성 → 존재할 때만 grant(로컬 단독 테스트 안전).
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='jobs_ro') THEN "
        "GRANT SELECT ON jobs TO jobs_ro; GRANT SELECT ON applications TO jobs_ro; END IF; END $$;"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS applications;")
    op.execute("DROP TABLE IF EXISTS jobs;")
```

- [ ] **Step 3: 실패 확인 — 실 pgvector 컨테이너 대상 upgrade (아직 최종 검증 전, 스크립트 인식만)**

Run: `cd backend && python -m alembic history`
Expected: `0001_baseline` 이 head로 표시(스크립트 로딩 성공). 아직 DB 적용 전이므로 이 단계는 "구성 유효" 확인용.

- [ ] **Step 4: 일회용 pgvector 컨테이너로 upgrade 통합 검증**

Run:
```bash
cd /Users/sunny/career-agent/backend
docker run -d --name ca-pg-test -e POSTGRES_PASSWORD=test -e POSTGRES_USER=n8n -e POSTGRES_DB=jobs -p 55432:5432 pgvector/pgvector:pg16
sleep 6
DATABASE_URL="postgresql://n8n:test@localhost:55432/jobs" python -m alembic upgrade head
docker exec ca-pg-test psql -U n8n -d jobs -c "\d jobs" -c "\di idx_jobs_embedding" -c "SELECT extname FROM pg_extension WHERE extname='vector';"
```
Expected: `jobs`·`applications` 존재, `idx_jobs_embedding`가 hnsw, `vector` 확장 존재. 정리: `docker rm -f ca-pg-test`.

- [ ] **Step 5: 커밋**

```bash
cd /Users/sunny/career-agent
git add backend/alembic.ini backend/migrations/env.py backend/migrations/script.py.mako backend/migrations/versions/0001_baseline_jobs.py
git commit -m "feat(db): Alembic + 베이스라인(기존 jobs·applications·pgvector·HNSW 흡수)"
```

---

## Task 3: 리서치 테이블 마이그레이션 (`company_research`·`job_research`)

스펙 "데이터 모델"의 두 리서치 테이블을 신규 마이그레이션으로 추가하고 `jobs_ro`에 SELECT 부여. `job_research`는 `jobs(source, job_id)` UNIQUE를 FK로 참조.

**Files:**
- Create: `backend/migrations/versions/0002_research_tables.py`

**Interfaces:**
- Consumes: `0001_baseline`(jobs 테이블·UNIQUE 제약).
- Produces: `alembic upgrade head` 시 `company_research`·`job_research` 생성 + FK + `jobs_ro` SELECT.

- [ ] **Step 1: 마이그레이션 작성**

`backend/migrations/versions/0002_research_tables.py`:
```python
"""research: company_research·job_research + jobs_ro SELECT

Revision ID: 0002_research
Revises: 0001_baseline
Create Date: 2026-07-21
"""
from alembic import op

revision = "0002_research"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS company_research (
          company        text PRIMARY KEY,
          overview       text,
          stability      text,
          data           jsonb,
          sources        jsonb,
          model          text,
          status         text DEFAULT 'done',
          researched_at  timestamptz DEFAULT now()
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS job_research (
          source         text,
          job_id         text,
          company        text,
          tech_detail    text,
          role_detail    text,
          data           jsonb,
          sources        jsonb,
          model          text,
          status         text DEFAULT 'done',
          researched_at  timestamptz DEFAULT now(),
          PRIMARY KEY (source, job_id),
          FOREIGN KEY (source, job_id) REFERENCES jobs(source, job_id) ON DELETE CASCADE
        );
        """
    )
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='jobs_ro') THEN "
        "GRANT SELECT ON company_research TO jobs_ro; "
        "GRANT SELECT ON job_research TO jobs_ro; END IF; END $$;"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS job_research;")
    op.execute("DROP TABLE IF EXISTS company_research;")
```

- [ ] **Step 2: 일회용 컨테이너로 upgrade 검증 (FK·grant 확인)**

Run:
```bash
cd /Users/sunny/career-agent/backend
docker run -d --name ca-pg-test2 -e POSTGRES_PASSWORD=test -e POSTGRES_USER=n8n -e POSTGRES_DB=jobs -p 55433:5432 pgvector/pgvector:pg16
sleep 6
docker exec ca-pg-test2 psql -U n8n -d jobs -c "CREATE ROLE jobs_ro LOGIN;"   # initdb 롤 대역(테스트용)
DATABASE_URL="postgresql://n8n:test@localhost:55433/jobs" python -m alembic upgrade head
docker exec ca-pg-test2 psql -U n8n -d jobs -c "\d job_research" \
  -c "SELECT has_table_privilege('jobs_ro','job_research','SELECT');"
```
Expected: `job_research`에 `FOREIGN KEY (source, job_id) REFERENCES jobs(source, job_id)`, `has_table_privilege` = `t`. 정리: `docker rm -f ca-pg-test2`.

- [ ] **Step 3: 커밋**

```bash
cd /Users/sunny/career-agent
git add backend/migrations/versions/0002_research_tables.py
git commit -m "feat(db): company_research·job_research 테이블 + jobs_ro SELECT"
```

---

## Task 4: `jobs_ro` 롤 부트스트랩 (career-agent Postgres initdb)

career-agent가 소유하는 fresh Postgres 볼륨의 **최초 기동 시** `jobs_ro` 로그인 롤을 생성한다(기존 n8n `db/roles.sh` 재현, 비밀번호는 `JOBS_RO_PASSWORD` env). 이후 Alembic 마이그레이션이 이 롤에 SELECT를 부여한다. 테이블 생성은 하지 않는다(스키마는 Alembic이 소유).

**Files:**
- Create: `career-agent/db/01-roles.sh`

- [ ] **Step 1: 롤 부트스트랩 스크립트 작성**

`db/01-roles.sh`:
```bash
#!/bin/bash
# career-agent Postgres 최초 기동 시 읽기전용 롤 생성(스키마는 Alembic이 소유).
# n8n-pjt/db/roles.sh 재현. 비밀번호는 env(JOBS_RO_PASSWORD), 하드코딩 금지.
set -e
psql -v ON_ERROR_STOP=1 -v ro_pw="${JOBS_RO_PASSWORD}" \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-'EOSQL'
  DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='jobs_ro') THEN
      CREATE ROLE jobs_ro LOGIN;
    END IF;
  END $$;
  ALTER ROLE jobs_ro WITH PASSWORD :'ro_pw';
EOSQL
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -c "GRANT CONNECT ON DATABASE \"$POSTGRES_DB\" TO jobs_ro;" \
  -c "GRANT USAGE ON SCHEMA public TO jobs_ro;"
```
(테이블 SELECT grant는 Alembic 0001/0002가 담당 — 롤이 먼저 존재하므로 순서 안전. init 스크립트는 initdb 단계에서 실행되고, `migrate` 서비스는 그 이후 접속한다.)

- [ ] **Step 2: 실행권한 + initdb 순서 검증**

Run:
```bash
cd /Users/sunny/career-agent && chmod +x db/01-roles.sh
docker run -d --name ca-pg-role -e POSTGRES_PASSWORD=test -e POSTGRES_USER=n8n -e POSTGRES_DB=jobs \
  -e JOBS_RO_PASSWORD=ro_test -v "$PWD/db":/docker-entrypoint-initdb.d:ro pgvector/pgvector:pg16
sleep 6
docker exec ca-pg-role psql -U n8n -d jobs -c "SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname='jobs_ro';"
```
Expected: `jobs_ro | t`. 정리: `docker rm -f ca-pg-role`.

- [ ] **Step 3: 커밋**

```bash
cd /Users/sunny/career-agent
git add db/01-roles.sh
git commit -m "feat(db): jobs_ro 읽기전용 롤 initdb 부트스트랩(roles.sh 재현)"
```

---

## Task 5: compose에 pgvector Postgres + migrate 원샷 + 백엔드 배선 + 공유 네트워크

career-agent compose가 Postgres를 소유하게 한다. `migrate`(원샷, backend 이미지로 `alembic upgrade head`) → `backend`(async 접근) 순서를 헬스체크로 강제. n8n이 붙을 **공유 external 네트워크**에 Postgres를 별칭 `postgres`로 노출.

**Files:**
- Edit: `career-agent/docker-compose.yml`, `career-agent/backend/Dockerfile`
- Create: `career-agent/.env.example`

**Interfaces:**
- Consumes: `db/01-roles.sh`(initdb), Alembic(migrate 서비스), `app.db`(backend).
- Produces: `postgres`·`migrate`·`backend`·`nginx` 서비스, external 네트워크 `jobs_shared`.

- [ ] **Step 1: Dockerfile deps 명시 설치 + alembic 파일 COPY (정본 계약 3번)**

`backend/Dockerfile`의 기존 pip 라인
```dockerfile
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn[standard]>=0.32"
```
을 **정본 계약 3번의 deps 명시 설치**로 교체하고, 그 뒤 `COPY app ./app` 아래에 alembic 파일 COPY를 가산:
```dockerfile
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn[standard]>=0.32" \
    "asyncpg>=0.30" "alembic>=1.13" "sqlalchemy>=2.0" "httpx>=0.27" "apscheduler>=3.10"
COPY app ./app
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations
```
(계약 3번: `pip install .`(editable/비editable) **금지** — 빌드단계 패키지탐색 위험. deps는 위처럼 **명시 설치**. `migrate` 원샷 서비스가 같은 이미지로 `alembic upgrade head`를 돌리므로 `alembic.ini`·`migrations`를 COPY. pytest는 CI(Jenkins) 에이전트가 `pip install -e ".[dev]"`로 실행하므로 이미지엔 dev extras 불필요.)

- [ ] **Step 2: `.env.example` 작성 (DB 변수 문서화)**

`.env.example`:
```
# career-agent 배포용 .env (실제 .env는 커밋 금지 — .gitignore)
HOST_UID=1001

# career-agent 소유 Postgres (기존 n8n jobs DB에서 이전)
POSTGRES_USER=n8n
POSTGRES_PASSWORD=change_me_please
POSTGRES_DB=jobs
JOBS_RO_PASSWORD=change_me_readonly_pw

# backend asyncpg 풀이 직접 쓰는 DSN (plain postgresql://, compose 서비스명 postgres)
# Alembic은 이 DSN을 env.py가 postgresql+asyncpg://로 변환해 마이그레이션에 사용.
DATABASE_URL=postgresql://n8n:change_me_please@postgres:5432/jobs

# 리서치 실패 알림 등(플랜 ③에서 사용). 값은 실제 .env에.
DISCORD_WEBHOOK_URL=
```

- [ ] **Step 3: `docker-compose.yml` 편집 (정본 계약 8번 — 가산, 전체 교체 금지)**

**전체 교체 금지.** 기존 walking-skeleton compose의 `backend`(claude `~/.claude` rw 마운트·user·expose)·`nginx`를 **보존**하고, 아래를 **가산**한다: (a) `postgres`(pgvector)·`migrate` 서비스 신규, (b) 공유 external 네트워크 `jobs_shared`(별칭 `postgres`), (c) 기존 `backend`에 `environment: DATABASE_URL`·`depends_on(postgres healthy, migrate completed)` 추가. 병합 결과는 아래와 같다(기존 backend claude 마운트·nginx 그대로 유지 확인):
```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      - POSTGRES_USER=${POSTGRES_USER}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DB=${POSTGRES_DB}
      - JOBS_RO_PASSWORD=${JOBS_RO_PASSWORD}
      - TZ=Asia/Seoul
      - PGTZ=Asia/Seoul
    volumes:
      - ./data/postgres:/var/lib/postgresql/data
      - ./db:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 5s
      timeout: 3s
      retries: 10
    networks:
      default:
      jobs_shared:
        aliases:
          - postgres          # n8n이 기존 자격증명(host=postgres) 그대로 여기 접속
    restart: unless-stopped

  migrate:
    build: ./backend
    command: ["python", "-m", "alembic", "upgrade", "head"]
    working_dir: /app
    environment:
      - DATABASE_URL=${DATABASE_URL}
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - default
    restart: "no"

  backend:
    build: ./backend
    user: "${HOST_UID:-1001}:${HOST_UID:-1001}"
    environment:
      - DATABASE_URL=${DATABASE_URL}
    volumes:
      - /home/ubuntu/.claude:/home/appuser/.claude:rw
      - /home/ubuntu/.claude.json:/home/appuser/.claude.json:rw
    expose:
      - "8000"
    depends_on:
      postgres:
        condition: service_healthy
      migrate:
        condition: service_completed_successfully
    networks:
      - default
    restart: unless-stopped

  nginx:
    build:
      context: .
      dockerfile: nginx/Dockerfile
    ports:
      - "127.0.0.1:80:80"
    depends_on:
      - backend
    networks:
      - default
    restart: unless-stopped

networks:
  default:
  jobs_shared:
    external: true          # n8n 재연결용 공유 네트워크(Task 8에서 생성)
```
(주의: 기존 compose는 `data/postgres` 볼륨이 없었다. 여기서 **career-agent 소유**로 새로 잡는다. 데이터 실적재는 Task 7. `jobs_shared`는 external이라 미리 만들어야 `config`/`up`이 통과 — Step 4 참고.)

- [ ] **Step 4: 로컬 검증 (config + postgres/migrate만 기동)**

Run:
```bash
cd /Users/sunny/career-agent
cp -n .env.example .env    # 로컬 검증용(시크릿 임시값). 커밋 금지.
docker network create jobs_shared 2>/dev/null || true
docker compose --env-file .env config -q && echo CONFIG_OK
docker compose --env-file .env up -d --build postgres
docker compose --env-file .env run --rm migrate
docker compose --env-file .env exec postgres psql -U n8n -d jobs \
  -c "\dt" -c "SELECT has_table_privilege('jobs_ro','job_research','SELECT');"
```
Expected: `CONFIG_OK`; `\dt`에 `jobs`·`applications`·`company_research`·`job_research`; grant `t`. 정리: `docker compose --env-file .env down` (볼륨 `data/postgres`는 로컬 테스트분 — `rm -rf data/postgres`로 정리 가능).

- [ ] **Step 5: 커밋**

```bash
cd /Users/sunny/career-agent
git add docker-compose.yml backend/Dockerfile .env.example
git commit -m "feat(compose): pgvector postgres·migrate 원샷·공유 네트워크·backend DB 배선"
```

---

## Task 6: 백엔드 DB 헬스 라우터 (별도 파일) + `main.py` 한 줄 mount

DB 접속을 증명하는 최소 엔드포인트. **별도 라우터 파일**로 두고 `main.py`엔 `include_router` 한 줄만 추가(병렬 플랜 충돌 최소화).

**Files:**
- Create: `backend/app/routers/__init__.py`, `backend/app/routers/db.py`, `backend/tests/test_db_router.py`
- Edit: `backend/app/main.py` (한 줄)

**Interfaces:**
- Consumes: `app.db.get_conn`(asyncpg conn, FastAPI Depends), `app.db.connect`/`close`(main.py lifespan).
- Produces: `GET /api/db/health` → `{"ok": true, "jobs_count": <int>, "pgvector": true}` (asyncpg `conn.fetchval`). 실패 시 503.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_db_router.py` (asyncpg conn을 `dependency_overrides[get_conn]`로 대체, finally에서 clear — 계약 1번: 전역 오염 금지):
```python
from fastapi.testclient import TestClient
from app import main
from app.db import get_conn


class FakeConn:
    async def fetchval(self, sql, *a):
        if "count" in sql.lower():
            return 42
        return 1  # pgvector 존재 여부 쿼리(SELECT 1 ...)


def test_db_health_ok():
    async def fake_conn():
        yield FakeConn()

    main.app.dependency_overrides[get_conn] = fake_conn
    try:
        r = TestClient(main.app).get("/api/db/health")
        assert r.status_code == 200
        assert r.json() == {"ok": True, "jobs_count": 42, "pgvector": True}
    finally:
        main.app.dependency_overrides.clear()


def test_db_health_failure():
    class BoomConn:
        async def fetchval(self, sql, *a):
            raise RuntimeError("db down")

    async def boom_conn():
        yield BoomConn()

    main.app.dependency_overrides[get_conn] = boom_conn
    try:
        r = TestClient(main.app).get("/api/db/health")
        assert r.status_code == 503
    finally:
        main.app.dependency_overrides.clear()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && python -m pytest tests/test_db_router.py -q`
Expected: FAIL — `404`(라우트 없음) / `ModuleNotFoundError: app.routers.db`.

- [ ] **Step 3: 구현**

`backend/app/routers/__init__.py`: (빈 파일)

`backend/app/routers/db.py` (asyncpg `conn.fetchval` — 계약 1번):
```python
from fastapi import APIRouter, Depends, HTTPException

from app.db import get_conn

router = APIRouter(prefix="/api/db", tags=["db"])


@router.get("/health")
async def db_health(conn=Depends(get_conn)):
    try:
        jobs_count = await conn.fetchval("SELECT count(*) FROM jobs")
        pgvector = await conn.fetchval(
            "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
        )
    except Exception as e:  # noqa: BLE001 — 접속·쿼리 실패를 503으로 표면화
        raise HTTPException(status_code=503, detail=str(e))
    return {"ok": True, "jobs_count": int(jobs_count or 0), "pgvector": pgvector == 1}
```

`backend/app/main.py` — **가산 편집(전체 파일 교체 금지, 계약 6·6a번)**: 기존 `/api/health`·`/api/claude-check` 핸들러는 그대로 두고, **단일 lifespan**(app.state.db 풀 connect/close **+ 스케줄러 start/stop 소유**)과 `include_router(db_router.router)`만 추가한다. **계약 6a**: `main.py`엔 lifespan **하나만** 둔다 — Starlette는 커스텀 lifespan이 있으면 `add_event_handler("startup"/"shutdown")`를 **무시**하므로, 플랜 ④ 스케줄러는 반드시 이 lifespan이 호출해야 한다(그래서 ④는 `add_event_handler`가 아니라 `start_scheduler(app)`/`stop_scheduler(app)`를 제공):
```python
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from app import db
from app.claude_client import run_claude
from app.routers import db as db_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = await db.connect()      # asyncpg 풀(계약 1번)
    # 계약 6a: 스케줄러 훅을 이 단일 lifespan이 소유. ④ 미머지 시점엔 import 실패 → no-op.
    try:
        from app.research.scheduler import start_scheduler, stop_scheduler
    except ImportError:  # 플랜 ④ 미머지 — 스케줄러 없음
        def start_scheduler(app):  # noqa: ARG001
            return None

        def stop_scheduler(app):  # noqa: ARG001
            return None
    try:
        start_scheduler(app)               # ④ 제공, 멱등·RESEARCH_AUTO_ENABLED false면 no-op
        yield
    finally:
        stop_scheduler(app)                # ④ 제공, 멱등·스케줄러 없으면 no-op
        await db.close(app.state.db)


app = FastAPI(title="career-agent", lifespan=lifespan)
app.include_router(db_router.router)


# --- 이하 기존 핸들러 그대로 유지 ---
@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/claude-check")
async def claude_check():
    try:
        text = await run_claude("Reply with exactly: OK")
    except Exception as e:  # noqa: BLE001 — 어떤 실패든 503로 표면화
        raise HTTPException(status_code=503, detail=str(e))
    return {"ok": True, "reply": text.strip()}
```
(플랜 ③은 여기에 `include_router(jobs_router)` 한 줄, 플랜 ④는 `include_router(research_router)`+`init_research(app)`를 각자 가산 — lifespan의 `app.state.db` 풀과 스케줄러를 공유한다. **④는 `add_event_handler`를 쓰지 않는다**: 커스텀 lifespan이 무시하므로 자동모드가 조용히 안 뜨는 버그가 난다.)

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && python -m pytest -q`
Expected: PASS (기존 + `test_db.py` 3 + `test_db_router.py` 2 모두 통과).

- [ ] **Step 5: 커밋**

```bash
cd /Users/sunny/career-agent
git add backend/app/routers backend/app/main.py backend/tests/test_db_router.py
git commit -m "feat(backend): GET /api/db/health(별도 라우터) + main.py mount 한 줄"
```

---

## Task 7: [LIVE — controller 확인 필요] A1 데이터 이전 (백업 → 쓰기정지 → 스키마 → 데이터 복원 → 검증)

기존 n8n Postgres의 `jobs`·`applications` 데이터를 career-agent 소유 Postgres로 옮긴다. **방식 = pg_dump 논리 복원**(원본 무손상, 즉시 롤백 가능, 스키마는 Alembic이 소유). 볼륨 이관(대안)은 런북에 폴백으로 기록.

> ⚠️ **컨트롤러 승인 필수.** 짧은 컷오버 창. 실행 전 **백업(pg_dump) 확보**. 원본 n8n Postgres·볼륨은 이 태스크에서 **읽기만**(무손상).

**Files:**
- Create: `career-agent/deploy/db-migration-runbook.md` (수행 절차·행수·롤백 기록)

- [ ] **Step 1: career-agent 레포 최신화 + `.env` 준비 (A1)**

```bash
ssh a1 'cd /home/ubuntu/career-agent && git fetch -q origin main && git reset --hard origin/main'
```
**.env는 no-op `cp` 금지(계약 8번).** walking-skeleton이 이미 A1 `.env`(HOST_UID만)를 생성했으므로 `test -f .env || cp` 는 무의미하다. 대신 **기존 .env에 DB 변수를 append**(이미 있으면 건너뜀). 값은 controller가 n8n `.env`에서 주입(화면 노출 금지):
```bash
ssh a1 'grep -q "^DATABASE_URL=" /home/ubuntu/career-agent/.env || cat >> /home/ubuntu/career-agent/.env <<EOF
POSTGRES_USER=n8n
POSTGRES_PASSWORD=<controller 주입: n8n .env의 POSTGRES_PASSWORD>
POSTGRES_DB=jobs
DATABASE_URL=postgresql://n8n:<pw>@postgres:5432/jobs
JOBS_RO_PASSWORD=<controller 주입: n8n .env의 JOBS_RO_PASSWORD>
EOF'
```
Expected: 기존 `HOST_UID` + append된 DB 변수가 한 `.env`에 공존. **POSTGRES_USER/PASSWORD/DB/JOBS_RO_PASSWORD는 n8n `.env`와 동일 값**(자격증명 연속성 → n8n 자격증명 무변경). 값은 controller가 주입, 화면 출력·커밋 금지.

- [ ] **Step 2: 백업 (컷오버 전 필수)**

```bash
ssh a1 'cd /home/ubuntu/n8n-pjt && sudo docker compose exec -T postgres \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > /home/ubuntu/jobs-backup-$(date +%F).dump'
ssh a1 'ls -la /home/ubuntu/jobs-backup-*.dump'
```
Expected: 백업 파일 생성(크기 > 0). **이 파일이 롤백 안전망.**

- [ ] **Step 3: n8n 쓰기 워크플로우 비활성화 (정합성)**

수집·요약·임베딩(01·02·05)을 잠시 비활성화(active=false)해 이전 중 신규 쓰기를 멈춘다. n8n UI(SSH 포워드) 또는 CLI:
```bash
ssh a1 'cd /home/ubuntu/n8n-pjt && sudo docker compose exec -T n8n \
  n8n update:workflow --all=false --active=false' 2>/dev/null || echo "UI에서 01/02/05 토글"
```
Expected: 01·02·05 inactive. (조회·알림 등 읽기 WF는 유지 가능.) **컨트롤러 확인.**

- [ ] **Step 4: career-agent Postgres 기동 + 스키마 마이그레이션**

```bash
ssh a1 'cd /home/ubuntu/career-agent && docker network create jobs_shared 2>/dev/null || true'
ssh a1 'cd /home/ubuntu/career-agent && sudo docker compose --env-file .env up -d --build postgres'
ssh a1 'cd /home/ubuntu/career-agent && sudo docker compose --env-file .env run --rm migrate'
ssh a1 'cd /home/ubuntu/career-agent && sudo docker compose --env-file .env exec postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dt"'
```
Expected: `jobs`·`applications`·`company_research`·`job_research` 생성(빈 상태), `jobs_ro` 롤 존재.

- [ ] **Step 5: 데이터 복원 (data-only) — 기존 → career-agent**

스키마는 이미 Alembic이 만들었으므로 **데이터만** 옮긴다. 두 컨테이너를 파이프로 직결:
```bash
ssh a1 'set -o pipefail; \
  cd /home/ubuntu/n8n-pjt && sudo docker compose exec -T postgres \
    pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --data-only --no-owner \
      --table=jobs --table=applications \
  | (cd /home/ubuntu/career-agent && sudo docker compose --env-file .env exec -T postgres \
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1)'
```
Expected: COPY/INSERT 성공, 에러 없음. (data-only 덤프는 시퀀스 `setval`도 포함 → id 연속성 유지. HNSW 인덱스는 적재 중 자동 갱신.)

- [ ] **Step 6: 검증 (행수·벡터쿼리 일치)**

```bash
# 원본 카운트
ssh a1 'cd /home/ubuntu/n8n-pjt && sudo docker compose exec -T postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT count(*) FROM jobs; SELECT count(*) FROM applications;"'
# 이전본 카운트 + 임베딩 존재 + 벡터쿼리 동작
ssh a1 'cd /home/ubuntu/career-agent && sudo docker compose --env-file .env exec -T postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc \
  "SELECT count(*) FROM jobs; SELECT count(*) FROM applications; \
   SELECT count(*) FROM jobs WHERE embedding IS NOT NULL; \
   SELECT id FROM jobs WHERE embedding IS NOT NULL ORDER BY embedding <=> (SELECT embedding FROM jobs WHERE embedding IS NOT NULL LIMIT 1) LIMIT 1;"'
```
Expected: `jobs`·`applications` 카운트가 원본과 **정확히 일치**, embedding 보존, HNSW 코사인 쿼리(`<=>`)가 결과 반환(벡터 인덱스 정상). **불일치 시 롤백(Step 8)로.**

- [ ] **Step 7: backend가 새 DB를 읽는지 확인**

```bash
ssh a1 'cd /home/ubuntu/career-agent && sudo docker compose --env-file .env up -d --build backend nginx'
ssh a1 'curl -s http://localhost:80/api/db/health'
```
Expected: `{"ok":true,"jobs_count":<원본과 동일>,"pgvector":true}`.

- [ ] **Step 8: 런북 기록 + 커밋 (롤백 절차 포함)**

`deploy/db-migration-runbook.md`에 실제 행수(원본/이전본), 사용 방식(pg_dump data-only), 백업 파일명, **롤백 절차**를 기록:
- 롤백: (Task 8 미실행 상태면) career-agent Postgres만 내리고 n8n은 원본 그대로 → 01/02/05 재활성화하면 원상복귀. 데이터 유실 없음(원본 무손상).
- 볼륨 이관 폴백(대안): career-agent postgres를 내리고 `data/postgres` 볼륨을 기존 n8n `data/postgres` 사본으로 교체 후 `migrate`만 실행(스키마 delta 추가). PG16 동일 버전이라 호환.
```bash
ssh a1 'cd /home/ubuntu/career-agent && git add deploy/db-migration-runbook.md && git commit -m "docs(deploy): DB 이전 런북(행수·백업·롤백)"'
```

---

## Task 8: [LIVE — controller 확인 필요] n8n 재연결 + 검증 + 재개 + 롤백

n8n을 공유 네트워크에서 career-agent Postgres(별칭 `postgres`)에 붙인다. n8n **자격증명은 이미 host=`postgres`** 이므로 네트워크만 바꾸면 재연결된다. 구 Postgres는 정지(삭제 아님, 가역).

> ⚠️ **컨트롤러 승인 필수.** n8n 레포(`/home/ubuntu/n8n-pjt`) override 편집 + 재시작. 실패 시 즉시 롤백.

**Files:**
- Edit (n8n 레포): `n8n-pjt/deploy/a1/docker-compose.override.yml` (n8n을 `jobs_shared`에 연결, 로컬 `postgres` 정지)

- [ ] **Step 1: n8n override 편집 — 공유 네트워크 연결**

`n8n-pjt/deploy/a1/docker-compose.override.yml`의 `services.n8n`에 external 네트워크를 추가하고, 로컬 `postgres` 서비스는 컷오버 후 정지(별칭 충돌 방지). override에 추가:
```yaml
services:
  n8n:
    networks:
      default:
      jobs_shared: {}     # career-agent Postgres(별칭 postgres)에 도달
  # 구 postgres는 컷오버 후 정지(아래 Step 3에서 stop). 정의 자체는 롤백 위해 보존.

networks:
  jobs_shared:
    external: true
```
(n8n의 Postgres 자격증명 host=`postgres`는 그대로. 구 로컬 `postgres`가 살아 있으면 default 네트워크에서 먼저 해석되므로, Step 3에서 반드시 stop 해야 `jobs_shared`의 별칭이 유효.)

- [ ] **Step 2: career-agent Postgres가 공유 네트워크에 있는지 확인**

```bash
ssh a1 'sudo docker network inspect jobs_shared --format "{{range .Containers}}{{.Name}} {{end}}"'
```
Expected: career-agent `postgres` 컨테이너가 목록에 있음(Task 7 Step 4에서 이미 연결). 없으면 `docker compose ... up -d postgres` 재실행.

- [ ] **Step 3: 구 postgres 정지 + n8n 재기동**

```bash
ssh a1 'cd /home/ubuntu/n8n-pjt && sudo docker compose stop postgres'            # 구 DB 정지(삭제 아님)
ssh a1 'cd /home/ubuntu/n8n-pjt && sudo docker compose up -d --no-deps n8n'       # override 반영 재기동
ssh a1 'sudo docker network inspect jobs_shared --format "{{range .Containers}}{{.Name}} {{end}}"'
```
Expected: n8n 컨테이너가 `jobs_shared`에 연결, 구 postgres Stopped. **`--no-deps` 필수(계약 8번):** plain `up -d n8n`은 `depends_on`으로 방금 정지한 구 postgres를 재기동해 `postgres` 별칭이 이중 해석되고 데이터가 갈라진다.

- [ ] **Step 4: n8n → career-agent Postgres 접속 검증**

n8n에서 `postgres` 호스트가 career-agent DB로 해석되는지 확인:
```bash
ssh a1 'cd /home/ubuntu/n8n-pjt && sudo docker compose exec -T n8n \
  sh -lc "getent hosts postgres"'
# 실쓰기 검증: 조회 WF(09 대체 전) 또는 임시로 pending 1건 처리해 career-agent DB에 반영되는지
ssh a1 'cd /home/ubuntu/career-agent && sudo docker compose --env-file .env exec -T postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT count(*) FROM jobs;"'
```
Expected: `getent`가 career-agent postgres 컨테이너 IP를 반환. **컨트롤러와 함께** n8n UI에서 대표 WF(예: 04 검색 또는 03 알림) 수동 실행 → 정상. 벡터검색(06) 결과 정상.

- [ ] **Step 5: 쓰기 워크플로우 재개 + 신규 유입 확인**

```bash
# Task 7 Step 3에서 끈 01/02/05 재활성화(UI 또는 CLI)
ssh a1 'cd /home/ubuntu/career-agent && sudo docker compose --env-file .env exec -T postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT max(collected_at) FROM jobs;"'
```
Expected: 재활성화 후 다음 수집 주기에 `max(collected_at)`가 갱신(신규 공고가 career-agent DB로 유입). **단일 소스 확정.**

- [ ] **Step 6: 롤백 절차 (실패 시)**

컷오버 실패 시:
```bash
# n8n을 구 DB로 원복
ssh a1 'cd /home/ubuntu/n8n-pjt && sudo docker compose up -d postgres'   # 구 DB 재기동
# override의 jobs_shared 연결 제거 후 n8n 재기동 → default 네트워크의 구 postgres로 복귀
ssh a1 'cd /home/ubuntu/n8n-pjt && git checkout deploy/a1/docker-compose.override.yml && sudo docker compose up -d n8n'
```
구 DB는 이전 동안 무손상이라 즉시 복귀. 런북에 결과 반영.

- [ ] **Step 7: n8n override 커밋 (n8n 레포)**

```bash
ssh a1 'cd /home/ubuntu/n8n-pjt && git add deploy/a1/docker-compose.override.yml && git commit -m "chore(a1): n8n을 career-agent 소유 Postgres(jobs_shared)로 재연결"'
```
(로컬 맥에도 동일 편집 반영하려면 `/Users/sunny/n8n-pjt`에서 커밋/푸시. **컨트롤러 확인.**)

---

## Task 9: [LIVE] 구 Postgres 은퇴 + Jenkins 스모크에 DB 헬스 추가

컷오버가 안정화되면 구 Postgres 정의를 은퇴(정지 유지 또는 제거)하고, career-agent Jenkins 스모크에 `/api/db/health`를 추가해 배포 회귀를 잡는다.

**Files:**
- Edit: `career-agent/Jenkinsfile` (smoke 단계에 DB 헬스 1줄)

- [ ] **Step 1: Jenkinsfile smoke에 DB 헬스 가산 (계약 8번 — 되돌림 금지)**

⚠️ **현재 smoke는 walking-skeleton의 `curl localhost`에서 이미 진화했다:** `docker compose exec -T nginx wget -qO- http://127.0.0.1/...` + 재시도 루프(IPv6·부팅레이스 fix). **이 형태를 `curl`로 되돌리지 말 것.** 기존 앱 헬스·SPA 재시도 루프는 그대로 두고, **같은 nginx-exec wget 형태로 DB 헬스 한 블록만 가산**한다. `stage('smoke')`의 `sh` 블록 안, 기존 재시도 루프 뒤에 추가:
```groovy
          # (가산) DB 헬스 — 기존 nginx-exec wget + 재시도 형태를 그대로 사용(curl 금지)
          for i in $(seq 1 10); do
            docker compose exec -T nginx wget -qO- http://127.0.0.1/api/db/health | grep -q '"ok":true' && break
            sleep 3
          done
          docker compose exec -T nginx wget -qO- http://127.0.0.1/api/db/health | grep -q '"ok":true'
```
(기존 `/api/health`·SPA(`<title>career-agent</title>`) 검증 루프는 **보존**. CD 배포 시 compose가 `postgres`·`migrate`를 함께 올리도록 `docker compose --env-file .env up -d --build`가 전 서비스를 대상하는지 확인 — Task 5 compose는 기본 전 서비스 up이므로 DB 헬스가 통과 가능.)

- [ ] **Step 2: 구 Postgres 은퇴 판단 (controller 확인)**

안정 확인(수 일 신규 유입 정상) 후:
```bash
# 정지 유지가 기본(가역). 완전 제거를 원하면 n8n compose에서 postgres 서비스 정의 삭제 + data/postgres 백업 보관.
ssh a1 'cd /home/ubuntu/n8n-pjt && sudo docker compose ps postgres'
```
Expected: 구 postgres가 Stopped/Removed. **볼륨(`n8n-pjt/data/postgres`)은 백업 삼아 일정 기간 보존**(즉시 삭제 금지).

- [ ] **Step 3: 커밋 + 파이프라인 E2E**

```bash
cd /Users/sunny/career-agent
git add Jenkinsfile
git commit -m "ci: 스모크에 /api/db/health 추가(DB 소유권 이전 회귀 방지)"
git push origin main
```
그 후 Jenkins 폴링(≤3분) → 빌드 → 배포 → 스모크 통과 확인:
```bash
ssh a1 'curl -sf http://localhost:80/api/db/health'   # {"ok":true,"jobs_count":N,"pgvector":true}
```
Expected: Jenkins SUCCESS, `/api/db/health` 정상.

---

## 완료 기준 (Plan ② Done)

- career-agent compose가 **pgvector Postgres를 소유**하고, 스키마(`jobs`·`applications`·`company_research`·`job_research`·`jobs_ro`)를 **Alembic이 소유**한다.
- 기존 `jobs` 데이터가 **행수·임베딩·HNSW 벡터쿼리까지 무손실**로 이전됨(원본 무손상).
- n8n이 **자격증명 변경 없이**(공유 네트워크 별칭 `postgres`) career-agent Postgres에 재연결되어 **단일 소스** 확정, 신규 수집이 새 DB로 유입.
- 백엔드가 **런타임 asyncpg 풀**(SQLAlchemy는 마이그레이션 전용)로 접속하고 `GET /api/db/health`(conn.fetchval)가 이를 증명, Jenkins 스모크가 nginx-exec wget으로 회귀 감시.
- 라이브 컷오버는 **백업 + 즉시 롤백** 절차가 런북에 기록됨. 리서치 러너·API·프론트는 이 플랜 밖(플랜 ③④).
