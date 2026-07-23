# 실행 로그(run_log) 작업 이력 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 수집기·워커·리서치 실행이 끝난 뒤에도 결과(성공/실패·건수·소요시간)를 대시보드에서 볼 수 있게 하고, 무인 스케줄 실행 실패는 디스코드로 알린다.

**Architecture:** 세 파이프라인의 완료된 실행을 Postgres `run_log`에 영속화한다. 공통 `logged_run` 래퍼가 실행을 감싸 시작/끝을 재고, 원본 반환은 JSONB로 보존하며 상태만 `ok/failed/skipped`로 정규화한다. 조회는 `GET /api/runs`, 표시는 Ops 대시보드 풋터 카드. 갱신은 폴링이 아니라 "마운트/수동실행후/라이브 모니터 active→idle 전환" 시 재조회.

**Tech Stack:** FastAPI + asyncpg + Alembic(백엔드), React 18 + Vite + TypeScript + vitest(프론트), APScheduler(인프로세스 스케줄러), Discord 웹훅(`app.research.discord.push`).

## Global Constraints

- 저장은 Postgres `run_log` 테이블(Alembic 마이그레이션 `0004_run_log`, down_revision=`0003_app_settings`). 인메모리 금지(재배포 시 소실).
- **완료된 실행만** 기록한다. 진행 중 상태는 기존 `Activity` 라이브 모니터가 담당 — 부분/`running` 행을 만들지 않는다.
- 상태 정규화: collector → `ok`(예외만 `failed`); worker → `skipped_tick` True면 `skipped`, 아니면 `ok`; research → `"done"→ok` / `"cached"→skipped` / `"failed"→failed`.
- 디스코드 알림은 **`trigger=='scheduled'` 이고 예외로 실패했을 때만**. 수동 실행·성공·워커 정상 틱은 무음. research는 `trigger='manual'`이며 러너가 자체 알림하므로 run_log 경로에서 추가 알림하지 않는다.
- 리서치 러너(`research_company`/`research_job`)는 **순수하게 유지** — 반환/알림/clear 로직을 바꾸지 않는다. 로깅은 bg 태스크를 감싸는 얇은 래퍼에서만.
- SSE 미도입. 실시간은 3초 폴링 유지 + 이벤트 기반 재조회.
- 원본 반환값(dict/str)은 `result` JSONB에 그대로 저장. 30일 초과 행은 insert 시 정리.
- 파이프라인 식별자는 정확히 `'collector' | 'worker' | 'research'`. 트리거는 `'manual' | 'scheduled'`.
- 기존 테스트 스타일 준수: 실 DB 대신 fake conn/pool. 순수 쿼리 빌더(`build_*_query`)는 단위 테스트, 실행 경로는 fake conn으로 검증.
- 마이그레이션 실행: `cd backend && python -m alembic upgrade head` (compose의 migrate 원샷과 동일).

---

### Task 1: 마이그레이션 0004 — `run_log` 테이블

**Files:**
- Create: `backend/migrations/versions/0004_run_log.py`

**Interfaces:**
- Produces: `run_log` 테이블 (컬럼: `id bigserial PK, pipeline text, ref text, label text, trigger text, status text, result jsonb, error text, started_at timestamptz, finished_at timestamptz, duration_ms int`), 인덱스 `run_log_finished_idx (finished_at DESC)`.

- [ ] **Step 1: 마이그레이션 파일 작성**

`backend/migrations/versions/0004_run_log.py`:

```python
"""run_log 실행 이력

Revision ID: 0004_run_log
Revises: 0003_app_settings
Create Date: 2026-07-23
"""
from alembic import op

revision = "0004_run_log"
down_revision = "0003_app_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS run_log (
          id          bigserial   PRIMARY KEY,
          pipeline    text        NOT NULL,
          ref         text        NOT NULL DEFAULT '',
          label       text        NOT NULL DEFAULT '',
          trigger     text        NOT NULL,
          status      text        NOT NULL,
          result      jsonb       NOT NULL DEFAULT '{}'::jsonb,
          error       text        NOT NULL DEFAULT '',
          started_at  timestamptz NOT NULL,
          finished_at timestamptz NOT NULL DEFAULT now(),
          duration_ms int         NOT NULL DEFAULT 0
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS run_log_finished_idx ON run_log (finished_at DESC);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS run_log;")
```

- [ ] **Step 2: 리비전 체인 검증**

Run: `cd backend && python -m alembic history | head -5`
Expected: 출력에 `0003_app_settings -> 0004_run_log (head)` 형태로 0004가 head로 표시됨.

- [ ] **Step 3: 모듈 임포트 검증(문법)**

Run: `cd backend && python -c "import importlib.util, glob; p=glob.glob('migrations/versions/0004_run_log.py')[0]; spec=importlib.util.spec_from_file_location('m', p); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print(m.revision, m.down_revision)"`
Expected: `0004_run_log 0003_app_settings`

- [ ] **Step 4: 커밋**

```bash
git add backend/migrations/versions/0004_run_log.py
git commit -m "feat(run_log): 실행 이력 테이블 마이그레이션 0004"
```

---

### Task 2: `run_log.py` 기록 엔진 — classify · record · logged_run

**Files:**
- Create: `backend/app/run_log.py`
- Test: `backend/tests/test_run_log.py`

**Interfaces:**
- Consumes: `app.research.discord.push(content: str)` (async, 웹훅 미설정/실패 무시).
- Produces:
  - `classify(pipeline: str, result) -> str` — `'ok'|'failed'|'skipped'`.
  - `async record(conn, *, pipeline, ref, label, trigger, status, result, error, started) -> None` — run_log 1행 insert + 30일 초과 정리.
  - `async logged_run(conn, *, pipeline, trigger, ref='', label='', clear=<callable>, run=<async callable>) -> Any` — `run()`을 감싸 결과 기록 후 원본 반환값을 그대로 반환; 예외 시 failed 기록 후 재-raise; `finally`에서 `clear()` 호출; `trigger=='scheduled'` 예외 시 디스코드 push.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_run_log.py`:

```python
import json

import pytest

from app.run_log import classify, logged_run


class FakeConn:
    def __init__(self):
        self.executed = []  # (sql, args)

    async def execute(self, sql, *args):
        self.executed.append((sql, args))


def _run(value):
    async def _r():
        return value
    return _r


def test_classify_collector_and_worker():
    assert classify("collector", {"scraped": 1, "inserted": 1}) == "ok"
    assert classify("worker", {"skipped_tick": True}) == "skipped"
    assert classify("worker", {"skipped_tick": False, "done": 2, "failed": 0}) == "ok"


def test_classify_research_strings():
    assert classify("research", "done") == "ok"
    assert classify("research", "cached") == "skipped"
    assert classify("research", "failed") == "failed"


async def test_logged_run_records_ok_and_returns_result():
    conn = FakeConn()
    cleared = []
    result = await logged_run(
        conn, pipeline="collector", trigger="manual",
        clear=lambda: cleared.append(True),
        run=_run({"scraped": 3, "inserted": 3}),
    )
    assert result == {"scraped": 3, "inserted": 3}
    assert cleared == [True]
    sql, args = conn.executed[0]
    assert "INSERT INTO run_log" in sql
    assert args[0] == "collector"          # pipeline
    assert args[3] == "manual"             # trigger
    assert args[4] == "ok"                 # status
    assert json.loads(args[5]) == {"scraped": 3, "inserted": 3}  # result jsonb


async def test_logged_run_records_failed_and_reraises():
    conn = FakeConn()
    async def boom():
        raise RuntimeError("scrape down")
    with pytest.raises(RuntimeError):
        await logged_run(conn, pipeline="collector", trigger="manual", run=boom)
    sql, args = conn.executed[0]
    assert args[4] == "failed"
    assert "scrape down" in args[6]        # error column


async def test_scheduled_failure_pushes_discord(monkeypatch):
    pushed = []
    async def fake_push(msg):
        pushed.append(msg)
    monkeypatch.setattr("app.run_log.push", fake_push)
    conn = FakeConn()
    async def boom():
        raise RuntimeError("down")
    with pytest.raises(RuntimeError):
        await logged_run(conn, pipeline="collector", trigger="scheduled", run=boom)
    assert pushed and "실패" in pushed[0]


async def test_manual_failure_does_not_push(monkeypatch):
    pushed = []
    async def fake_push(msg):
        pushed.append(msg)
    monkeypatch.setattr("app.run_log.push", fake_push)
    conn = FakeConn()
    async def boom():
        raise RuntimeError("down")
    with pytest.raises(RuntimeError):
        await logged_run(conn, pipeline="collector", trigger="manual", run=boom)
    assert pushed == []
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && python -m pytest tests/test_run_log.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.run_log'`

- [ ] **Step 3: `run_log.py` 최소 구현**

`backend/app/run_log.py`:

```python
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from app.research.discord import push

log = logging.getLogger("run_log")

_KO = {"collector": "수집", "worker": "요약 처리", "research": "리서치"}

_INSERT = (
    "INSERT INTO run_log "
    "(pipeline, ref, label, trigger, status, result, error, started_at, finished_at, duration_ms) "
    "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, $10)"
)
_PRUNE = "DELETE FROM run_log WHERE finished_at < now() - interval '30 days'"


def classify(pipeline: str, result: Any) -> str:
    if pipeline == "research":
        return {"done": "ok", "cached": "skipped", "failed": "failed"}.get(result, "ok")
    if pipeline == "worker" and isinstance(result, dict) and result.get("skipped_tick"):
        return "skipped"
    return "ok"


async def record(conn, *, pipeline: str, ref: str, label: str, trigger: str,
                 status: str, result: Any, error: str, started: datetime) -> None:
    finished = datetime.now(timezone.utc)
    duration_ms = int((finished - started).total_seconds() * 1000)
    payload = result if isinstance(result, dict) else {"result": result}
    await conn.execute(_INSERT, pipeline, ref, label, trigger, status,
                       json.dumps(payload), error, started, finished, duration_ms)
    await conn.execute(_PRUNE)


async def logged_run(conn, *, pipeline: str, trigger: str, ref: str = "", label: str = "",
                     clear: Callable[[], None] = lambda: None,
                     run: Callable[[], Any]) -> Any:
    started = datetime.now(timezone.utc)
    try:
        result = await run()
        await record(conn, pipeline=pipeline, ref=ref, label=label, trigger=trigger,
                     status=classify(pipeline, result), result=result, error="", started=started)
        return result
    except Exception as e:  # noqa: BLE001 — 실패도 기록 후 재-raise
        await record(conn, pipeline=pipeline, ref=ref, label=label, trigger=trigger,
                     status="failed", result={}, error=str(e), started=started)
        if trigger == "scheduled":
            first = str(e).splitlines()[0][:200] if str(e) else ""
            await push(f"⚠️ 스케줄 {_KO.get(pipeline, pipeline)} 실패 · {first}")
        raise
    finally:
        clear()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_run_log.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/run_log.py backend/tests/test_run_log.py
git commit -m "feat(run_log): logged_run 기록 엔진 + 상태 정규화 + 스케줄 실패 알림"
```

---

### Task 3: 조회 — build_runs_query · list_runs · `GET /api/runs`

**Files:**
- Modify: `backend/app/run_log.py` (조회 함수 추가)
- Create: `backend/app/routers/runs.py`
- Modify: `backend/app/main.py:54` (라우터 include 추가)
- Test: `backend/tests/test_run_log_query.py`, `backend/tests/test_runs_router.py`

**Interfaces:**
- Consumes: `app.db.get_conn` (FastAPI dependency), `logged_run`/`record`가 쓴 `run_log` 스키마.
- Produces:
  - `build_runs_query(*, pipeline=None, status=None, limit=30) -> tuple[str, list]` — 순수 쿼리 빌더.
  - `async list_runs(conn, *, pipeline=None, status=None, limit=30) -> dict` — `{"items": [ {id, pipeline, ref, label, trigger, status, result(dict), error, started_at(iso), finished_at(iso), duration_ms} ] }`.
  - `GET /api/runs?limit=&pipeline=&status=` → `list_runs` 결과.

- [ ] **Step 1: 쿼리 빌더/조회 테스트 작성**

`backend/tests/test_run_log_query.py`:

```python
from app.run_log import build_runs_query, list_runs


def test_build_runs_query_no_filters():
    sql, params = build_runs_query()
    assert "FROM run_log" in sql
    assert "ORDER BY finished_at DESC" in sql
    assert "WHERE" not in sql
    assert "LIMIT $1" in sql
    assert params == [30]


def test_build_runs_query_pipeline_and_status():
    sql, params = build_runs_query(pipeline="collector", status="ok", limit=10)
    assert "pipeline = $1" in sql
    assert "status = $2" in sql
    assert "LIMIT $3" in sql
    assert params == ["collector", "ok", 10]


class FakeFetchConn:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, sql, *args):
        return self._rows


async def test_list_runs_shapes_rows():
    from datetime import datetime, timezone
    ts = datetime(2026, 7, 23, 1, 2, 3, tzinfo=timezone.utc)
    rows = [{
        "id": 1, "pipeline": "collector", "ref": "", "label": "",
        "trigger": "manual", "status": "ok",
        "result": '{"scraped": 3, "inserted": 3}',  # asyncpg가 jsonb를 str로 줄 수 있음
        "error": "", "started_at": ts, "finished_at": ts, "duration_ms": 1200,
    }]
    out = await list_runs(FakeFetchConn(rows), limit=5)
    item = out["items"][0]
    assert item["result"] == {"scraped": 3, "inserted": 3}
    assert item["finished_at"] == ts.isoformat()
    assert item["pipeline"] == "collector"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && python -m pytest tests/test_run_log_query.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_runs_query'`

- [ ] **Step 3: `run_log.py`에 조회 함수 추가**

`backend/app/run_log.py` 하단에 추가:

```python
_SELECT = (
    "SELECT id, pipeline, ref, label, trigger, status, result, error, "
    "started_at, finished_at, duration_ms FROM run_log"
)


def build_runs_query(*, pipeline: str | None = None, status: str | None = None,
                     limit: int = 30) -> tuple[str, list]:
    where: list[str] = []
    params: list = []
    if pipeline:
        params.append(pipeline)
        where.append(f"pipeline = ${len(params)}")
    if status:
        params.append(status)
        where.append(f"status = ${len(params)}")
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)
    sql = f"{_SELECT}{clause} ORDER BY finished_at DESC LIMIT ${len(params)}"
    return sql, params


def _row_to_item(row) -> dict:
    d = dict(row)
    res = d.get("result")
    if isinstance(res, str):
        d["result"] = json.loads(res)
    for k in ("started_at", "finished_at"):
        v = d.get(k)
        if v is not None:
            d[k] = v.isoformat()
    return d


async def list_runs(conn, *, pipeline: str | None = None, status: str | None = None,
                    limit: int = 30) -> dict:
    sql, params = build_runs_query(pipeline=pipeline, status=status, limit=limit)
    rows = await conn.fetch(sql, *params)
    return {"items": [_row_to_item(r) for r in rows]}
```

- [ ] **Step 4: 조회 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_run_log_query.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: `/api/runs` 라우터 작성**

`backend/app/routers/runs.py`:

```python
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from app.db import get_conn
from app.run_log import list_runs

router = APIRouter(prefix="/api", tags=["runs"])


@router.get("/runs")
async def get_runs(
    pipeline: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(30, ge=1, le=100),
    conn: Any = Depends(get_conn),
):
    return await list_runs(conn, pipeline=pipeline, status=status, limit=limit)
```

- [ ] **Step 6: 라우터 include (main.py)**

`backend/app/main.py`의 import 블록(13행 부근)에 추가:

```python
from app.routers import runs as runs_router
```

그리고 `app.include_router(status_router.router)` 다음 줄(54행 부근)에 추가:

```python
app.include_router(runs_router.router)
```

- [ ] **Step 7: 라우터 테스트 작성**

`backend/tests/test_runs_router.py`:

```python
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.routers import runs as runs_router


def _app(monkeypatch, payload):
    app = FastAPI()
    app.include_router(runs_router.router)

    async def _get_conn():
        yield object()
    app.dependency_overrides[runs_router.get_conn] = _get_conn

    captured = {}
    async def fake_list_runs(conn, *, pipeline=None, status=None, limit=30):
        captured.update(pipeline=pipeline, status=status, limit=limit)
        return payload
    monkeypatch.setattr(runs_router, "list_runs", fake_list_runs)
    return app, captured


async def test_get_runs_returns_items(monkeypatch):
    app, captured = _app(monkeypatch, {"items": [{"id": 1, "pipeline": "collector"}]})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/runs?limit=5&pipeline=collector")
    assert r.status_code == 200
    assert r.json()["items"][0]["pipeline"] == "collector"
    assert captured == {"pipeline": "collector", "status": None, "limit": 5}
```

- [ ] **Step 8: 라우터 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_runs_router.py -q`
Expected: PASS (1 passed)

- [ ] **Step 9: 커밋**

```bash
git add backend/app/run_log.py backend/app/routers/runs.py backend/app/main.py backend/tests/test_run_log_query.py backend/tests/test_runs_router.py
git commit -m "feat(run_log): GET /api/runs 조회 엔드포인트"
```

---

### Task 4: 수집기·워커를 logged_run으로 배선 (수동 + 스케줄러)

**Files:**
- Modify: `backend/app/routers/collect.py` (전체 교체)
- Modify: `backend/app/collect_scheduler.py:12-35` (collector_job/worker_job)
- Test: `backend/tests/test_collect_router.py` (기존 `Conn`을 기록형으로 교체 + run_log 기록 검증)

**Interfaces:**
- Consumes: `logged_run(conn, *, pipeline, trigger, clear, run)` (Task 2), `collect(conn, settings, *, http, on_stage)`, `worker_tick(conn, settings, *, http, on_stage)`.
- Produces: 수동 경로는 `trigger='manual'`, 스케줄러 경로는 `trigger='scheduled'`로 run_log 기록. on_stage/activity 라이브 배선은 그대로 유지.

- [ ] **Step 1: 기존 라우터 테스트를 기록형 Conn으로 갱신 + 신규 검증 추가**

`backend/tests/test_collect_router.py`의 `class Conn: pass`를 아래로 교체:

```python
class Conn:
    def __init__(self):
        self.executed = []

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
```

그리고 `_get_conn`이 이 conn을 재사용해 테스트에서 검사할 수 있도록 `_app`을 수정:

```python
def _app(monkeypatch, run_result, worker_result):
    app = FastAPI()
    app.state.http = object()
    app.state.activity = Activity()
    app.include_router(collect_router.router)

    conn = Conn()
    async def _get_conn():
        yield conn
    app.dependency_overrides[collect_router.get_conn] = _get_conn
    app.state._test_conn = conn  # 테스트에서 run_log insert 검사용

    async def fake_get_settings(conn):
        return Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"]))
    monkeypatch.setattr(collect_router, "get_settings", fake_get_settings)

    async def fake_collect(conn, s, *, http, on_stage=None): return run_result
    async def fake_worker(conn, s, *, http, on_stage=None): return worker_result
    monkeypatch.setattr(collect_router, "collect", fake_collect)
    monkeypatch.setattr(collect_router, "worker_tick", fake_worker)
    return app
```

파일 하단에 신규 테스트 추가:

```python
async def test_manual_collect_writes_run_log(monkeypatch):
    app = _app(monkeypatch, {"scraped": 5, "inserted": 5}, {})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post("/api/collect/run")
    inserts = [a for (sql, a) in app.state._test_conn.executed if "INSERT INTO run_log" in sql]
    assert inserts, "run_log INSERT가 실행되어야 함"
    args = inserts[0]
    assert args[0] == "collector" and args[3] == "manual" and args[4] == "ok"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && python -m pytest tests/test_collect_router.py -q`
Expected: FAIL — `test_manual_collect_writes_run_log`에서 run_log INSERT 없음(아직 배선 전).

- [ ] **Step 3: `collect.py` 라우터를 logged_run으로 교체**

`backend/app/routers/collect.py` 전체를 아래로 교체:

```python
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.collect.collector import collect
from app.collect.worker import worker_tick
from app.db import get_conn
from app.run_log import logged_run
from app.settings_repo import get_settings

router = APIRouter(prefix="/api/collect", tags=["collect"])


@router.post("/run", status_code=202)
async def run_collect(request: Request, conn: Any = Depends(get_conn)):
    settings = await get_settings(conn)
    activity = request.app.state.activity
    # 수동 실행도 진행상황을 activity에 반영 + 결과를 run_log에 기록.
    return await logged_run(
        conn, pipeline="collector", trigger="manual",
        clear=lambda: activity.clear("collector"),
        run=lambda: collect(conn, settings, http=request.app.state.http,
                            on_stage=lambda st, d, p: activity.set_stage("collector", st, d, str(p))),
    )


@router.post("/worker/run", status_code=202)
async def run_worker(request: Request, conn: Any = Depends(get_conn)):
    settings = await get_settings(conn)
    activity = request.app.state.activity
    return await logged_run(
        conn, pipeline="worker", trigger="manual",
        clear=lambda: activity.clear("worker"),
        run=lambda: worker_tick(conn, settings, http=request.app.state.http,
                                on_stage=lambda st, d, p: activity.set_stage("worker", st, d, str(p))),
    )
```

- [ ] **Step 4: 스케줄러 배선 (collect_scheduler.py)**

`backend/app/collect_scheduler.py`의 import 블록에 추가:

```python
from app.run_log import logged_run
```

`collector_job`/`worker_job` 두 함수를 아래로 교체:

```python
async def collector_job(get_ctx) -> None:
    pool, http, activity = get_ctx()
    async with pool.acquire() as conn:
        settings = await get_settings(conn)
        if not settings.enabled:
            return
        await logged_run(
            conn, pipeline="collector", trigger="scheduled",
            clear=lambda: activity.clear("collector"),
            run=lambda: collect(conn, settings, http=http,
                                on_stage=lambda st, d, p: activity.set_stage("collector", st, d, str(p))),
        )


async def worker_job(get_ctx) -> None:
    pool, http, activity = get_ctx()
    async with pool.acquire() as conn:
        settings = await get_settings(conn)
        if not settings.enabled:
            return
        await logged_run(
            conn, pipeline="worker", trigger="scheduled",
            clear=lambda: activity.clear("worker"),
            run=lambda: worker_tick(conn, settings, http=http,
                                    on_stage=lambda st, d, p: activity.set_stage("worker", st, d, str(p))),
        )
```

- [ ] **Step 5: 전체 collect 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_collect_router.py -q`
Expected: PASS (기존 activity 진행상황 테스트 4개 + 신규 run_log 테스트 1개 모두 통과)

- [ ] **Step 6: 커밋**

```bash
git add backend/app/routers/collect.py backend/app/collect_scheduler.py backend/tests/test_collect_router.py
git commit -m "feat(run_log): 수집기·워커 수동/스케줄 실행을 run_log에 기록"
```

---

### Task 5: 리서치 실행을 logged_run으로 배선 (bg 태스크 래퍼)

**Files:**
- Modify: `backend/app/routers/research.py` (로깅 래퍼 추가 + bg.add_task 타깃 교체)
- Test: `backend/tests/test_research_run_log.py`

**Interfaces:**
- Consumes: `logged_run` (Task 2), `runner.research_company(db, company, url='', *, force, activity)`, `runner.research_job(db, source, job_id, *, force, activity)`, `store.get_job_meta(db, source, job_id) -> {source, job_id, company, title, ...}|None`.
- Produces: 리서치 트리거 1건당 run_log 1행(`pipeline='research'`, `trigger='manual'`, `ref`=company 또는 `source:job_id`, `label`=기업명/공고 제목). 러너 자체는 불변.

- [ ] **Step 1: 리서치 로깅 테스트 작성**

`backend/tests/test_research_run_log.py`:

```python
from app.routers import research as research_router


class FakeConn:
    def __init__(self):
        self.executed = []

    async def execute(self, sql, *args):
        self.executed.append((sql, args))


class FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False
        return _Ctx()


async def test_logged_company_writes_run_log(monkeypatch):
    conn = FakeConn()
    pool = FakePool(conn)

    async def fake_research_company(db, company, url="", *, force=False, activity=None):
        return "done"
    monkeypatch.setattr(research_router.runner, "research_company", fake_research_company)

    await research_router._logged_company(pool, "미스릴", force=False, activity=None)

    inserts = [a for (sql, a) in conn.executed if "INSERT INTO run_log" in sql]
    assert inserts, "run_log INSERT가 실행되어야 함"
    args = inserts[0]
    assert args[0] == "research"      # pipeline
    assert args[1] == "미스릴"         # ref
    assert args[3] == "manual"        # trigger
    assert args[4] == "ok"            # status ("done" → ok)


async def test_logged_job_writes_run_log(monkeypatch):
    conn = FakeConn()
    pool = FakePool(conn)

    async def fake_research_job(db, source, job_id, *, force=False, activity=None):
        return "cached"
    monkeypatch.setattr(research_router.runner, "research_job", fake_research_job)

    await research_router._logged_job(
        pool, "wanted", "123", label="백엔드 개발자", force=False, activity=None,
    )
    inserts = [a for (sql, a) in conn.executed if "INSERT INTO run_log" in sql]
    args = inserts[0]
    assert args[0] == "research"
    assert args[1] == "wanted:123"    # ref
    assert args[2] == "백엔드 개발자"   # label
    assert args[4] == "skipped"       # "cached" → skipped
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && python -m pytest tests/test_research_run_log.py -q`
Expected: FAIL — `AttributeError: module 'app.routers.research' has no attribute '_logged_company'`

- [ ] **Step 3: 로깅 래퍼 추가 + bg 타깃 교체 (research.py)**

`backend/app/routers/research.py`의 import 블록에 추가:

```python
from app.run_log import logged_run
```

파일에 래퍼 함수 2개 추가(라우터 정의 위, `router = APIRouter(...)` 다음):

```python
async def _logged_company(pool, company: str, *, force: bool, activity) -> None:
    async with pool.acquire() as conn:
        await logged_run(
            conn, pipeline="research", trigger="manual", ref=company, label=company,
            run=lambda: runner.research_company(pool, company, "", force=force, activity=activity),
        )


async def _logged_job(pool, source: str, job_id: str, *, label: str, force: bool, activity) -> None:
    async with pool.acquire() as conn:
        await logged_run(
            conn, pipeline="research", trigger="manual",
            ref=f"{source}:{job_id}", label=label,
            run=lambda: runner.research_job(pool, source, job_id, force=force, activity=activity),
        )
```

`trigger_company`의 `bg.add_task(...)` 호출을 교체:

```python
    bg.add_task(
        _logged_company, request.app.state.db, req.company,
        force=req.force, activity=request.app.state.activity,
    )
```

`trigger_job`의 `bg.add_task(...)` 호출을 교체(래퍼는 `research_job`이 이미 존재를 검증하지만, 라우터는 이미 `meta`로 404를 처리하므로 label만 넘김):

```python
    label = meta.get("title") or meta.get("company") or f"{req.source}:{req.job_id}"
    bg.add_task(
        _logged_job, request.app.state.db, req.source, req.job_id,
        label=label, force=req.force, activity=request.app.state.activity,
    )
```

- [ ] **Step 4: 리서치 로깅 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_research_run_log.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: 리서치 라우터 회귀 테스트 확인**

Run: `cd backend && python -m pytest tests/ -q -k research`
Expected: PASS — 기존 리서치 관련 테스트가 깨지지 않음.

- [ ] **Step 6: 커밋**

```bash
git add backend/app/routers/research.py backend/tests/test_research_run_log.py
git commit -m "feat(run_log): 리서치 실행을 run_log에 기록(bg 태스크 래퍼)"
```

---

### Task 6: 프론트 API 클라이언트 + 포매터 (순수 함수)

**Files:**
- Create: `frontend/src/runsApi.ts`
- Create: `frontend/src/runsFormat.ts`
- Test: `frontend/src/runsFormat.test.ts`

**Interfaces:**
- Consumes: `GET /api/runs` (Task 3) 응답 `{items: RunLogItem[]}`.
- Produces:
  - `runsApi.ts`: `interface RunLogItem`, `getRuns(limit?: number): Promise<{items: RunLogItem[]}>`.
  - `runsFormat.ts`: `pipelineLabel`, `triggerLabel`, `statusClass`, `runSummary`, `durationLabel`, `relativeTime(iso, nowMs)` — 전부 순수 함수.

- [ ] **Step 1: 포매터 테스트 작성**

`frontend/src/runsFormat.test.ts`:

```typescript
import { test, expect } from "vitest";
import {
  pipelineLabel, triggerLabel, statusClass, runSummary, durationLabel, relativeTime,
} from "./runsFormat";
import type { RunLogItem } from "./runsApi";

function item(over: Partial<RunLogItem>): RunLogItem {
  return {
    id: 1, pipeline: "collector", ref: "", label: "", trigger: "manual",
    status: "ok", result: {}, error: "", started_at: "", finished_at: "", duration_ms: 0,
    ...over,
  };
}

test("labels and status class", () => {
  expect(pipelineLabel("collector")).toBe("수집기");
  expect(pipelineLabel("worker")).toBe("요약");
  expect(pipelineLabel("research")).toBe("리서치");
  expect(triggerLabel("scheduled")).toBe("자동");
  expect(triggerLabel("manual")).toBe("수동");
  expect(statusClass("ok")).toBe("rdot-ok");
  expect(statusClass("failed")).toBe("rdot-bad");
  expect(statusClass("skipped")).toBe("rdot-skip");
});

test("collector summary", () => {
  expect(runSummary(item({ pipeline: "collector", result: { scraped: 43, inserted: 43 } })))
    .toBe("스크레이핑 43·적재 43");
});

test("worker summary variants", () => {
  expect(runSummary(item({ pipeline: "worker", result: { done: 5, failed: 0 } })))
    .toBe("요약 5건");
  expect(runSummary(item({ pipeline: "worker", result: { done: 5, failed: 2 } })))
    .toBe("요약 5건·실패 2");
  expect(runSummary(item({ pipeline: "worker", status: "skipped", result: { skipped_tick: true } })))
    .toBe("건너뜀·LLM 대기");
});

test("research summary variants", () => {
  expect(runSummary(item({ pipeline: "research", label: "미스릴", status: "ok" })))
    .toBe("미스릴 완료");
  expect(runSummary(item({ pipeline: "research", label: "미스릴", status: "skipped" })))
    .toBe("미스릴 · 캐시");
  expect(runSummary(item({ pipeline: "research", label: "미스릴", status: "failed" })))
    .toBe("미스릴 · 실패");
});

test("duration and relative time", () => {
  expect(durationLabel(850)).toBe("850ms");
  expect(durationLabel(1500)).toBe("1.5s");
  const now = new Date("2026-07-23T10:00:00Z").getTime();
  expect(relativeTime("2026-07-23T09:59:30Z", now)).toBe("30초 전");
  expect(relativeTime("2026-07-23T09:55:00Z", now)).toBe("5분 전");
  expect(relativeTime("2026-07-23T08:00:00Z", now)).toBe("2시간 전");
});
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd frontend && npx vitest run src/runsFormat.test.ts`
Expected: FAIL — 모듈 `./runsFormat` / `./runsApi` 없음.

- [ ] **Step 3: `runsApi.ts` 작성**

`frontend/src/runsApi.ts`:

```typescript
export type Pipeline = "collector" | "worker" | "research";
export type RunStatus = "ok" | "failed" | "skipped";

export interface RunLogItem {
  id: number;
  pipeline: Pipeline;
  ref: string;
  label: string;
  trigger: "manual" | "scheduled";
  status: RunStatus;
  result: Record<string, unknown>;
  error: string;
  started_at: string;
  finished_at: string;
  duration_ms: number;
}

export async function getRuns(limit = 30): Promise<{ items: RunLogItem[] }> {
  const r = await fetch(`/api/runs?limit=${limit}`);
  if (!r.ok) throw new Error("runs load failed");
  return r.json();
}
```

- [ ] **Step 4: `runsFormat.ts` 작성**

`frontend/src/runsFormat.ts`:

```typescript
import type { RunLogItem } from "./runsApi";

export function pipelineLabel(p: string): string {
  return p === "collector" ? "수집기" : p === "worker" ? "요약" : "리서치";
}

export function triggerLabel(t: string): string {
  return t === "scheduled" ? "자동" : "수동";
}

export function statusClass(s: string): string {
  return s === "ok" ? "rdot-ok" : s === "failed" ? "rdot-bad" : "rdot-skip";
}

export function runSummary(it: RunLogItem): string {
  const r = it.result as Record<string, number>;
  if (it.pipeline === "collector") {
    return `스크레이핑 ${r.scraped ?? 0}·적재 ${r.inserted ?? 0}`;
  }
  if (it.pipeline === "worker") {
    if (it.status === "skipped") return "건너뜀·LLM 대기";
    const failed = Number(r.failed ?? 0);
    return `요약 ${r.done ?? 0}건${failed ? `·실패 ${failed}` : ""}`;
  }
  const name = it.label || it.ref;
  if (it.status === "skipped") return `${name} · 캐시`;
  if (it.status === "failed") return `${name} · 실패`;
  return `${name} 완료`;
}

export function durationLabel(ms: number): string {
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

export function relativeTime(iso: string, nowMs: number): string {
  const s = Math.max(0, Math.round((nowMs - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}초 전`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}분 전`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}시간 전`;
  return `${Math.round(h / 24)}일 전`;
}
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `cd frontend && npx vitest run src/runsFormat.test.ts`
Expected: PASS (5 passed)

- [ ] **Step 6: 커밋**

```bash
git add frontend/src/runsApi.ts frontend/src/runsFormat.ts frontend/src/runsFormat.test.ts
git commit -m "feat(run_log): 프론트 runs API 클라이언트 + 포매터"
```

---

### Task 7: Ops 대시보드 "실행 로그" 카드 + CSS + 갱신 트리거

**Files:**
- Modify: `frontend/src/pages/Ops.tsx`
- Modify: `frontend/src/index.css` (실행 로그 스타일 추가)
- Modify: `frontend/src/pages/Ops.test.tsx` (mockFetch에 /api/runs 추가 + 렌더/갱신 테스트)

**Interfaces:**
- Consumes: `getRuns` (Task 6), `runsFormat.*` (Task 6), 기존 `status.activity.collector/worker` (라이브 상태).
- Produces: 풋터에 "실행 로그" 카드. 갱신 트리거 3종(마운트 / 수동 실행 후 / 라이브 active→idle 전환).

- [ ] **Step 1: Ops.test.tsx에 실행 로그 목/검증 추가**

`frontend/src/pages/Ops.test.tsx`의 `mockFetch` 내부, `/api/settings` 분기 앞에 추가:

```typescript
    else if (u.includes("/api/runs")) body = {
      items: [
        { id: 2, pipeline: "collector", ref: "", label: "", trigger: "scheduled",
          status: "ok", result: { scraped: 43, inserted: 43 }, error: "",
          started_at: "2026-07-23T09:00:00Z", finished_at: "2026-07-23T09:00:03Z", duration_ms: 3000 },
      ],
    };
```

파일 하단에 신규 테스트 추가:

```typescript
test("실행 로그 카드가 최근 실행을 렌더한다", async () => {
  render(<Ops />);
  await waitFor(() => expect(screen.getByText("실행 로그")).toBeTruthy());
  expect(screen.getByText("스크레이핑 43·적재 43")).toBeTruthy();
  expect(screen.getByText("자동")).toBeTruthy();
});

test("수동 수집 후 실행 로그를 재조회한다", async () => {
  const fetchSpy = vi.fn(mockFetch());
  global.fetch = fetchSpy as unknown as typeof fetch;
  render(<Ops />);
  await waitFor(() => expect(screen.getByText("실행 로그")).toBeTruthy());
  const before = fetchSpy.mock.calls.filter(([u]) => String(u).includes("/api/runs")).length;
  fireEvent.click(screen.getByText("지금 수집"));
  await waitFor(() => {
    const after = fetchSpy.mock.calls.filter(([u]) => String(u).includes("/api/runs")).length;
    expect(after).toBeGreaterThan(before);
  });
});
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd frontend && npx vitest run src/pages/Ops.test.tsx`
Expected: FAIL — "실행 로그" 텍스트 없음.

- [ ] **Step 3: Ops.tsx에 실행 로그 상태·갱신·렌더 추가**

`frontend/src/pages/Ops.tsx` 수정:

(a) import에 `useRef` 추가 및 runs 모듈 import:

```typescript
import { useEffect, useRef, useState } from "react";
```

`import { SPRING_UI, stagger } from "../design/springs";` 다음 줄에 추가:

```typescript
import { getRuns, type RunLogItem } from "../runsApi";
import { pipelineLabel, triggerLabel, statusClass, runSummary, durationLabel, relativeTime } from "../runsFormat";
```

(b) 상태/헬퍼 추가 — `const [claude, setClaude] = ...` 다음:

```typescript
  const [runs, setRuns] = useState<RunLogItem[]>([]);
  const refreshRuns = () => getRuns(30).then((r) => setRuns(r.items)).catch(() => { /* keep last */ });
```

(c) 마운트 시 최초 조회 — 설정 로드 useEffect 다음에 추가:

```typescript
  useEffect(() => { refreshRuns(); }, []);
```

(d) `doRun`의 `finally` 블록에서 재조회 — 기존:

```typescript
    finally { setBusy(false); }
```

를 아래로 교체:

```typescript
    finally { setBusy(false); refreshRuns(); }
```

(e) 라이브 active→idle 전환 감지 — `const col = ...; const wrk = ...;` 다음에 추가:

```typescript
  const active = !!col || !!wrk;
  const prevActive = useRef(false);
  useEffect(() => {
    if (prevActive.current && !active) refreshRuns();
    prevActive.current = active;
  }, [active]);
```

(f) 실행 로그 카드 렌더 — 알림 `motion.section`(`card(4, "span-2")`) 닫는 태그 다음, `</>` 앞에 추가:

```tsx
          <motion.section {...card(5, "span-2")}>
            <div className="card-h">실행 로그</div>
            {runs.length === 0 ? (
              <p className="caption" style={{ margin: 0 }}>아직 기록된 실행이 없습니다.</p>
            ) : (
              <ul className="run-log">
                {runs.map((it) => (
                  <li key={it.id} className="run-row">
                    <span className={`rdot ${statusClass(it.status)}`} />
                    <span className="rpipe">{pipelineLabel(it.pipeline)}</span>
                    <span className="pill rtrig">{triggerLabel(it.trigger)}</span>
                    <span className="rsum">{runSummary(it)}</span>
                    <span className="rdur">{durationLabel(it.duration_ms)}</span>
                    <span className="rtime">{relativeTime(it.finished_at, Date.now())}</span>
                  </li>
                ))}
              </ul>
            )}
          </motion.section>
```

- [ ] **Step 4: index.css에 실행 로그 스타일 추가**

`frontend/src/index.css` 하단에 추가:

```css
/* ── 실행 로그 ── */
.run-log { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.run-row {
  display: grid;
  grid-template-columns: auto auto auto 1fr auto auto;
  align-items: center; gap: 10px;
  padding: 9px 2px; border-top: 1px solid var(--glass-edge); font-size: 13px;
}
.run-row:first-child { border-top: 0; }
.rdot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.rdot-ok { background: var(--good); }
.rdot-bad { background: var(--bad); }
.rdot-skip { background: var(--text-3); }
.rpipe { font-weight: 600; min-width: 44px; }
.rtrig { font-size: 11px; }
.rsum { color: var(--text-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rdur { color: var(--text-3); font-variant-numeric: tabular-nums; }
.rtime { color: var(--text-3); white-space: nowrap; font-variant-numeric: tabular-nums; }
```

- [ ] **Step 5: Ops 테스트 통과 확인**

Run: `cd frontend && npx vitest run src/pages/Ops.test.tsx`
Expected: PASS (기존 테스트 + 신규 실행 로그 렌더/재조회 테스트 통과)

- [ ] **Step 6: 프론트 전체 테스트 + 타입체크**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: 전체 PASS, 타입 에러 0.

- [ ] **Step 7: 커밋**

```bash
git add frontend/src/pages/Ops.tsx frontend/src/index.css frontend/src/pages/Ops.test.tsx
git commit -m "feat(run_log): Ops 대시보드 실행 로그 카드 + 갱신 트리거"
```

---

## 최종 검증 (전체 스위트)

- [ ] **백엔드 전체:** `cd backend && python -m pytest -q` → 기존 + 신규 전부 PASS.
- [ ] **프론트 전체:** `cd frontend && npx vitest run && npx tsc --noEmit` → 전부 PASS, 타입 0.
- [ ] 배포는 기존 CI/CD(Jenkins 자동 웹훅)가 처리하며, migrate 원샷이 `alembic upgrade head`로 0004를 적용한다.

## 자기 검토 결과

**스펙 커버리지:** DB 테이블(T1) · 기록 엔진/정규화/스케줄 실패 알림(T2) · 조회 API(T3) · 수집기·워커 배선(T4) · 리서치 배선(T5) · 프론트 API/포매터(T6) · Ops 카드/갱신 트리거(T7). 스펙의 모든 항목이 태스크로 매핑됨. 30일 보존은 T2 `record`의 `_PRUNE`. "완료된 실행만"은 logged_run 구조로 보장. SSE 미도입·훅 지점(logged_run)은 설계대로.

**플레이스홀더:** 없음 — 모든 코드 단계에 실제 코드 포함.

**타입 일관성:** `logged_run(conn, *, pipeline, trigger, ref, label, clear, run)` 시그니처가 T2 정의와 T4/T5 호출에서 일치. `RunLogItem` 필드가 T3 `list_runs` 응답·T6 타입·T7 렌더에서 일치. `pipelineLabel/statusClass/runSummary` 반환이 T6 정의와 T7 사용에서 일치. CSS 클래스 `rdot-ok/rdot-bad/rdot-skip`가 T6 `statusClass`와 T4 인덱스(`args[0]=pipeline … args[6]=error`)가 T2 `_INSERT` 파라미터 순서와 일치.
```
