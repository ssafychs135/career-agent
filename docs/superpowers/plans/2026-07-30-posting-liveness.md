# 마감·삭제 공고 숨기기(공고 생존 재검증) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 마감·삭제된 공고를 매일 감지해 목록과 알림에서 제외한다.

**Architecture:** `jobs`에 `posting_state` 컬럼(`open`/`closed`/`deleted`)을 두고, 매일 00:00 KST에 `open` 행만 전수 재검증한다. 판정 로직은 소스별로 완전히 다르므로(원티드=`status` 필드, 점핏=`closed_at`) 순수 함수 둘로 분리한다. 목록 쿼리와 알림기 SELECT에 `posting_state='open'` 절을 더해 숨긴다.

**Tech Stack:** Python 3.12 / FastAPI / asyncpg / Alembic / APScheduler / pytest(asyncio_mode=auto), React 18 / TypeScript / vitest

**스펙:** `docs/superpowers/specs/2026-07-30-posting-liveness-design.md`

## Global Constraints

- `posting_state` ∈ `"open"` | `"closed"` | `"deleted"`. DDL 기본값은 `'open'` — 배포 직후 기존 489건이 전부 그대로 보여야 한다(동작 불변).
- **판정 불가는 반드시 `open`을 유지한다.** 타임아웃·5xx·프록시 오류·파싱 실패는 전부 `open`. 명확한 사망 신호가 있을 때만 `closed`/`deleted`를 반환한다.
- 원티드 판정: HTTP 404 → `deleted` / `status != "active"` 또는 `hidden` 참 → `closed` / 그 외 `open`.
- 점핏 판정: HTTP 400 → `deleted` / `closedAt < now` → `closed` / 그 외 `open`. **점핏은 마감돼도 `status=0`·`positionStatus="CHECKED"`로 살아있는 공고와 동일하다 — 이 두 필드로 판정하면 안 된다.**
- 점핏 만료는 API 호출 없이 SQL로 먼저 처리한다(`closed_at`이 이미 DB에 있음).
- `jobs.status`(파이프라인 상태)와 `posting_state`(공고 생존)는 다른 것이다. 섞지 않는다.
- 재검증 실행 시각은 `VERIFY_HOUR = 0`(KST 자정). 스케줄러는 이미 `timezone="Asia/Seoul"`.
- advisory lock 키 `VERIFY_LOCK_KEY = 8123402` — 알림기(`8123401`)와 달라야 한다.
- 공고 상세(`jobs_repo.get_job`)는 필터하지 않는다. 목록에서만 뺀다.
- 프론트는 `runsFormat.ts`만 바꾼다. 새 화면·토글 없음.
- 백엔드 테스트: `cd backend && python -m pytest`. 프론트: `cd frontend && npx vitest run` + `npx tsc --noEmit`.
- 주석·docstring·커밋 메시지는 한국어. 커밋 프리픽스 `feat:`.
- 베이스라인: 백엔드 **208 passed**, 프론트 **58 passed**.

## 파일 구조

| 파일 | 책임 | 태스크 |
|---|---|---|
| `backend/migrations/versions/0008_posting_state.py` (신규) | 컬럼 2개 + 인덱스 | 1 |
| `backend/app/collect/liveness.py` (신규) | 소스별 생존 판정 순수 함수 | 2 |
| `backend/app/collect/verify.py` (신규) | 재검증 틱(락·일괄 만료·API 순회) | 3 |
| `backend/app/collect_scheduler.py` | `verify_job` 등록(cron hour=0) | 4 |
| `backend/app/routers/verify.py` (신규) | `POST /api/verify/run` | 4 |
| `backend/app/main.py` | 라우터 include | 4 |
| `backend/app/run_log.py` | `_KO`에 `verify` 추가 | 4 |
| `backend/app/jobs_repo.py` | 목록 쿼리에 `posting_state='open'` | 5 |
| `backend/app/notify/notifier.py` | SELECT에 `posting_state='open'` | 5 |
| `backend/app/collect/collector.py` | 되살아남 UPDATE | 6 |
| `frontend/src/runsApi.ts` · `runsFormat.ts` | `verify` 파이프라인 표시 | 7 |

---

### Task 1: 마이그레이션 — `posting_state` 컬럼

**Files:**
- Create: `backend/migrations/versions/0008_posting_state.py`
- Test: `backend/tests/test_posting_state_migration.py`

**Interfaces:**
- Consumes: 없음
- Produces: `jobs.posting_state text NOT NULL DEFAULT 'open'`, `jobs.state_checked_at timestamptz`, 인덱스 `idx_jobs_posting_state`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_posting_state_migration.py`:

```python
from pathlib import Path

DDL = (Path(__file__).resolve().parents[1]
       / "migrations" / "versions" / "0008_posting_state.py").read_text()


def test_columns_and_default():
    # 기본값 'open'이라야 배포 직후 기존 공고가 전부 그대로 보인다(동작 불변).
    assert "posting_state text NOT NULL DEFAULT 'open'" in DDL
    assert "state_checked_at timestamptz" in DDL


def test_index_present():
    assert "idx_jobs_posting_state" in DDL


def test_revision_chain():
    assert 'revision = "0008_posting_state"' in DDL
    assert 'down_revision = "0007_task_models"' in DDL


def test_downgrade_drops_both_columns():
    down = DDL.split("def downgrade")[1]
    assert "posting_state" in down and "state_checked_at" in down
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && python -m pytest tests/test_posting_state_migration.py -v`
Expected: FAIL — `FileNotFoundError: ...0008_posting_state.py`

- [ ] **Step 3: 마이그레이션 작성**

`backend/migrations/versions/0008_posting_state.py`:

```python
"""공고 생존 상태(마감·삭제) 기록

Revision ID: 0008_posting_state
Revises: 0007_task_models
Create Date: 2026-07-30
"""
from alembic import op

revision = "0008_posting_state"
down_revision = "0007_task_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 기본값 'open' — 기존 행은 전부 살아있는 것으로 두고, 첫 재검증이 판정한다.
    op.execute(
        "ALTER TABLE jobs "
        "ADD COLUMN IF NOT EXISTS posting_state text NOT NULL DEFAULT 'open', "
        "ADD COLUMN IF NOT EXISTS state_checked_at timestamptz;"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_posting_state "
        "ON jobs (posting_state, state_checked_at);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_jobs_posting_state;")
    op.execute(
        "ALTER TABLE jobs "
        "DROP COLUMN IF EXISTS posting_state, "
        "DROP COLUMN IF EXISTS state_checked_at;"
    )
```

- [ ] **Step 4: 통과 확인**

Run: `cd backend && python -m pytest tests/test_posting_state_migration.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 전체 스위트**

Run: `cd backend && python -m pytest -q`
Expected: 212 passed

- [ ] **Step 6: 커밋**

```bash
git add backend/migrations/versions/0008_posting_state.py backend/tests/test_posting_state_migration.py
git commit -m "feat(db): 공고 생존 상태 컬럼(posting_state·state_checked_at)"
```

---

### Task 2: 생존 판정 순수 함수

**Files:**
- Create: `backend/app/collect/liveness.py`
- Test: `backend/tests/test_liveness.py`

**Interfaces:**
- Consumes: 없음(순수 모듈)
- Produces:
  - `OPEN = "open"`, `CLOSED = "closed"`, `DELETED = "deleted"`
  - `wanted_state(http_status: int, payload: dict) -> str`
  - `jumpit_state(http_status: int, payload: dict, now: datetime) -> str`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_liveness.py`:

```python
from datetime import datetime

from app.collect.liveness import CLOSED, DELETED, OPEN, jumpit_state, wanted_state

NOW = datetime(2026, 7, 30, 12, 0, 0)


def test_wanted_active_is_open():
    p = {"data": {"job": {"status": "active", "hidden": False}}}
    assert wanted_state(200, p) == OPEN


def test_wanted_404_is_deleted():
    # 실측: {"error_code": 11001, "message": "job not found exception", "data": None}
    assert wanted_state(404, {"error_code": 11001, "data": None}) == DELETED


def test_wanted_close_and_draft_are_closed():
    assert wanted_state(200, {"data": {"job": {"status": "close", "hidden": True}}}) == CLOSED
    assert wanted_state(200, {"data": {"job": {"status": "draft", "hidden": True}}}) == CLOSED


def test_wanted_hidden_alone_is_closed():
    assert wanted_state(200, {"data": {"job": {"status": "active", "hidden": True}}}) == CLOSED


def test_wanted_unknown_response_stays_open():
    """판정 불가는 open — 인프라 장애로 공고를 숨기면 안 된다."""
    assert wanted_state(500, {}) == OPEN
    assert wanted_state(200, {}) == OPEN                      # 페이로드 비정상
    assert wanted_state(200, {"data": None}) == OPEN
    assert wanted_state(200, {"data": {"job": {}}}) == OPEN   # status 키 없음
    assert wanted_state(429, {"message": "rate limited"}) == OPEN


def test_jumpit_400_is_deleted():
    assert jumpit_state(400, {}, NOW) == DELETED


def test_jumpit_expired_closedat_is_closed():
    # 실측: 만료돼도 status=0·positionStatus=CHECKED로 살아있는 공고와 동일 —
    # closedAt만이 유일한 신호다.
    p = {"result": {"status": 0, "positionStatus": "CHECKED",
                    "closedAt": "2026-07-12 23:59:59"}}
    assert jumpit_state(200, p, NOW) == CLOSED


def test_jumpit_future_closedat_is_open():
    p = {"result": {"status": 0, "positionStatus": "CHECKED",
                    "closedAt": "2026-08-28 23:59:59"}}
    assert jumpit_state(200, p, NOW) == OPEN


def test_jumpit_status_fields_never_decide():
    """status=0·CHECKED는 생사와 무관하므로 이것만으로 closed 판정하면 안 된다."""
    p = {"result": {"status": 0, "positionStatus": "CHECKED"}}  # closedAt 없음
    assert jumpit_state(200, p, NOW) == OPEN


def test_jumpit_unknown_response_stays_open():
    assert jumpit_state(500, {}, NOW) == OPEN
    assert jumpit_state(200, {}, NOW) == OPEN
    assert jumpit_state(200, {"result": None}, NOW) == OPEN
    assert jumpit_state(200, {"result": {"closedAt": "not-a-date"}}, NOW) == OPEN
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && python -m pytest tests/test_liveness.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.collect.liveness'`

- [ ] **Step 3: 구현**

`backend/app/collect/liveness.py`:

```python
"""공고 생존 판정 — 소스별 신호가 완전히 달라 함수를 나눈다.

안전 기본값은 항상 OPEN이다. 타임아웃·5xx·페이로드 이상 등 판정 불가 상황에서
공고를 숨기면, 사용자는 그 공고의 존재조차 모르므로 복구를 요청할 수 없다.
잘못 숨기는 쪽이 잘못 보여주는 쪽보다 나쁘다.
"""
from datetime import datetime

from app.collect.collector import parse_dt

OPEN, CLOSED, DELETED = "open", "closed", "deleted"


def wanted_state(http_status: int, payload: dict) -> str:
    """원티드 상세 응답 → 생존 상태.

    실측 신호: 404(error_code 11001) = 삭제, status "close"/"draft" 또는
    hidden = 마감. due_time은 항상 null이라 쓰지 않는다.
    """
    if http_status == 404:
        return DELETED
    if http_status != 200 or not isinstance(payload, dict):
        return OPEN
    job = ((payload.get("data") or {}) if isinstance(payload.get("data"), dict) else {}).get("job")
    if not isinstance(job, dict) or not job:
        return OPEN
    status = job.get("status")
    if status is not None and status != "active":
        return CLOSED
    if job.get("hidden") or job.get("is_private"):
        return CLOSED
    return OPEN


def jumpit_state(http_status: int, payload: dict, now: datetime) -> str:
    """점핏 상세 응답 → 생존 상태.

    실측: 없는 ID는 HTTP 400. 마감돼도 status=0·positionStatus="CHECKED"로
    살아있는 공고와 같으므로, closedAt 경과만이 유일한 마감 신호다.
    """
    if http_status == 400:
        return DELETED
    if http_status != 200 or not isinstance(payload, dict):
        return OPEN
    result = payload.get("result")
    if not isinstance(result, dict):
        return OPEN
    closed_at = parse_dt(result.get("closedAt"))
    if closed_at is None:
        return OPEN
    # parse_dt는 tz 없는 값을 naive로 돌려준다. now도 naive로 받는다(호출자 책임).
    if closed_at.tzinfo is not None and now.tzinfo is None:
        closed_at = closed_at.replace(tzinfo=None)
    return CLOSED if closed_at < now else OPEN
```

- [ ] **Step 4: 통과 확인**

Run: `cd backend && python -m pytest tests/test_liveness.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: 안전 기본값이 진짜인지 뮤테이션 검증**

`wanted_state`의 `if http_status != 200 or not isinstance(payload, dict): return OPEN`을 잠시 `return CLOSED`로 바꾸고 실행:

Run: `cd backend && python -m pytest tests/test_liveness.py::test_wanted_unknown_response_stays_open -v`
Expected: **FAIL**

원래 코드로 복구하고 재실행 → PASS. 결과를 보고서에 남긴다.

- [ ] **Step 6: 전체 스위트**

Run: `cd backend && python -m pytest -q`
Expected: 222 passed

- [ ] **Step 7: 커밋**

```bash
git add backend/app/collect/liveness.py backend/tests/test_liveness.py
git commit -m "feat(collect): 공고 생존 판정 함수(원티드 status·점핏 closedAt)"
```

---

### Task 3: 재검증 틱

**Files:**
- Create: `backend/app/collect/verify.py`
- Test: `backend/tests/test_verify_tick.py`

**Interfaces:**
- Consumes: `app.collect.liveness.{OPEN, CLOSED, DELETED, wanted_state, jumpit_state}`, `app.collect.detail.detail_url`, `app.collect.config.{JOB_PROXY_URL, JOB_PROXY_SECRET, DETAIL_TIMEOUT}`
- Produces:
  - `VERIFY_LOCK_KEY = 8123402`, `VERIFY_HOUR = 0`, `EXPIRE_JUMPIT_SQL`, `SELECT_OPEN_SQL`, `MARK_STATE_SQL`
  - `async def verify_tick(conn, *, http, on_stage=None) -> dict` → `{"checked": n, "closed": n, "deleted": n, "failed": n}`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_verify_tick.py`:

```python
from app.collect.verify import VERIFY_LOCK_KEY, verify_tick


class Resp:
    def __init__(self, code=200, payload=None):
        self.status_code = code
        self._p = payload if payload is not None else {}
    def json(self): return self._p


class Http:
    """URL에 따라 정해진 응답을 돌려주는 대역. 호출 URL을 기록한다."""
    def __init__(self, by_id=None, boom=False):
        self.by_id = by_id or {}
        self.boom = boom
        self.calls = []
    async def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        if self.boom:
            raise RuntimeError("네트워크 끊김")
        for jid, resp in self.by_id.items():
            if jid in url:
                return resp
        return Resp(200, {})


class Conn:
    def __init__(self, rows, lock=True):
        self.rows = rows
        self.lock = lock
        self.executed = []
        self.expired = 0
    async def fetchval(self, sql, *args):
        if "pg_try_advisory_lock" in sql:
            return self.lock
        return None
    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return "UPDATE 0"
    async def fetch(self, sql, *args):
        return self.rows


def _row(source, job_id):
    return {"id": 1, "source": source, "job_id": job_id}


async def test_returns_zero_when_lock_not_acquired():
    conn = Conn([], lock=False)
    r = await verify_tick(conn, http=Http())
    assert r == {"checked": 0, "closed": 0, "deleted": 0, "failed": 0}
    assert conn.executed == []   # 아무것도 건드리지 않음


async def test_expires_jumpit_by_sql_before_api():
    """점핏 만료는 closed_at이 이미 DB에 있으므로 API 없이 처리한다."""
    conn = Conn([])
    http = Http()
    await verify_tick(conn, http=http)
    sqls = " ".join(s for s, _a in conn.executed)
    assert "posting_state='closed'" in sqls.replace(" ", "").replace("=", "=")
    assert "closed_at" in sqls
    assert http.calls == []      # 만료 처리에 API를 쓰지 않음


async def test_marks_wanted_closed_and_deleted():
    conn = Conn([_row("wanted", "111"), _row("wanted", "222")])
    http = Http({
        "111": Resp(200, {"data": {"job": {"status": "close", "hidden": True}}}),
        "222": Resp(404, {"error_code": 11001}),
    })
    r = await verify_tick(conn, http=http)
    assert r["checked"] == 2 and r["closed"] == 1 and r["deleted"] == 1
    assert r["failed"] == 0


async def test_open_posting_is_not_marked_dead():
    conn = Conn([_row("wanted", "111")])
    http = Http({"111": Resp(200, {"data": {"job": {"status": "active", "hidden": False}}})})
    r = await verify_tick(conn, http=http)
    assert r["closed"] == 0 and r["deleted"] == 0 and r["failed"] == 0
    marks = [a for s, a in conn.executed if "posting_state" in s and "closed_at" not in s]
    assert marks and marks[-1][0] == "open"   # 상태는 open으로 갱신(확인 시각 기록)


async def test_network_failure_counts_as_failed_and_keeps_open():
    """프록시가 죽어도 공고를 숨기면 안 된다."""
    conn = Conn([_row("wanted", "111")])
    r = await verify_tick(conn, http=Http(boom=True))
    assert r["failed"] == 1 and r["closed"] == 0 and r["deleted"] == 0


async def test_jumpit_uses_direct_url_not_proxy():
    conn = Conn([_row("jumpit", "555")])
    http = Http({"555": Resp(200, {"result": {"closedAt": "2030-01-01 00:00:00"}})})
    await verify_tick(conn, http=http)
    assert any("jumpit-api" in u for u in http.calls)
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && python -m pytest tests/test_verify_tick.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.collect.verify'`

- [ ] **Step 3: 구현**

`backend/app/collect/verify.py`:

```python
"""공고 생존 재검증 — 매일 open 상태 전수검사.

점핏 만료는 closed_at이 이미 DB에 있어 SQL 한 번으로 끝난다. 나머지는
상세 API를 순회하며 소스별로 판정한다. 판정 불가는 open을 유지한다.
"""
import logging
from datetime import datetime
from urllib.parse import quote

from app.collect.config import DETAIL_TIMEOUT, JOB_PROXY_SECRET, JOB_PROXY_URL
from app.collect.detail import detail_url
from app.collect.liveness import CLOSED, DELETED, jumpit_state, wanted_state

log = logging.getLogger("collect.verify")

VERIFY_LOCK_KEY = 8123402  # 알림기(8123401)와 다른 키
VERIFY_HOUR = 0            # KST 자정(스케줄러 timezone=Asia/Seoul)

_UA = {"User-Agent": "Mozilla/5.0"}

# 점핏 만료는 API 없이 일괄 처리 — closed_at은 수집 시점에 이미 저장돼 있다.
EXPIRE_JUMPIT_SQL = (
    "UPDATE jobs SET posting_state='closed', state_checked_at=now() "
    "WHERE posting_state='open' AND source='jumpit' "
    "AND closed_at IS NOT NULL AND closed_at < now()"
)
SELECT_OPEN_SQL = (
    "SELECT id, source, job_id FROM jobs WHERE posting_state='open' ORDER BY id"
)
MARK_STATE_SQL = (
    "UPDATE jobs SET posting_state=$1, state_checked_at=now() WHERE id=$2"
)


def _request(source: str, job_id: str):
    """(url, headers) — 원티드만 프록시를 경유한다(수집기와 동일 규칙)."""
    url = detail_url(source, job_id)
    if source == "wanted" and JOB_PROXY_URL:
        return (f"{JOB_PROXY_URL}/?url={quote(url, safe='')}",
                {**_UA, "X-Proxy-Secret": JOB_PROXY_SECRET})
    return url, _UA


async def verify_tick(conn, *, http, on_stage=None) -> dict:
    # 스케줄 틱과 수동 실행이 겹치면 같은 행을 두 번 조회·판정한다. 하나만 돌린다.
    if not await conn.fetchval("SELECT pg_try_advisory_lock($1)", VERIFY_LOCK_KEY):
        return {"checked": 0, "closed": 0, "deleted": 0, "failed": 0}
    try:
        await conn.execute(EXPIRE_JUMPIT_SQL)

        rows = [dict(r) for r in await conn.fetch(SELECT_OPEN_SQL)]
        now = datetime.now()
        closed = deleted = failed = 0
        for i, row in enumerate(rows):
            source, job_id = row["source"], row["job_id"]
            if on_stage:
                on_stage("생존 확인", f"{source}:{job_id}", f"{i+1}/{len(rows)}")
            url, hdr = _request(source, job_id)
            try:
                resp = await http.get(url, headers=hdr, timeout=DETAIL_TIMEOUT)
                payload = resp.json()
                status_code = resp.status_code
            except Exception:  # noqa: BLE001 — 판정 불가. 숨기지 않는다.
                failed += 1
                continue
            try:
                state = (wanted_state(status_code, payload) if source == "wanted"
                         else jumpit_state(status_code, payload, now))
            except Exception:  # noqa: BLE001 — 파싱 이상도 판정 불가로 취급
                failed += 1
                continue
            await conn.execute(MARK_STATE_SQL, state, row["id"])
            if state == CLOSED:
                closed += 1
            elif state == DELETED:
                deleted += 1
        log.info("verify: checked=%d closed=%d deleted=%d failed=%d",
                 len(rows), closed, deleted, failed)
        return {"checked": len(rows), "closed": closed,
                "deleted": deleted, "failed": failed}
    finally:
        await conn.execute("SELECT pg_advisory_unlock($1)", VERIFY_LOCK_KEY)
```

- [ ] **Step 4: 통과 확인**

Run: `cd backend && python -m pytest tests/test_verify_tick.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: 전체 스위트**

Run: `cd backend && python -m pytest -q`
Expected: 228 passed

- [ ] **Step 6: 커밋**

```bash
git add backend/app/collect/verify.py backend/tests/test_verify_tick.py
git commit -m "feat(collect): 공고 생존 재검증 틱(락·점핏 일괄 만료·API 순회)"
```

---

### Task 4: 스케줄러·수동 트리거·실행 로그 배선

**Files:**
- Modify: `backend/app/collect_scheduler.py`
- Create: `backend/app/routers/verify.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/run_log.py`
- Test: `backend/tests/test_collect_scheduler.py`, `backend/tests/test_verify_router.py`

**Interfaces:**
- Consumes: `app.collect.verify.{verify_tick, VERIFY_HOUR}`, `app.run_log.logged_run`, `app.settings_repo.get_settings`
- Produces: `verify_job(get_ctx)`, `POST /api/verify/run` → `verify_tick` 반환 dict

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_collect_scheduler.py` 끝에 추가:

```python
def test_start_registers_verify_job_at_midnight(monkeypatch):
    monkeypatch.setattr(cs, "AsyncIOScheduler", FakeSched)
    app = _app()
    cs.start_collect_scheduler(app)
    sched = app.state.collect_scheduler
    assert "verify" in sched.jobs
    trigger, kw = sched.jobs["verify"]
    assert trigger == "cron" and kw["hour"] == 0 and kw["minute"] == 0


async def test_verify_job_noop_when_disabled(monkeypatch):
    """enabled=false면 재검증도 돌지 않는다(수집기·워커와 동일한 컷오버 규칙)."""
    from app.settings_repo import Settings, SETTINGS_DEFAULTS
    calls = {"verify_tick": 0, "logged_run": 0}

    async def fake_get_settings(c):
        return Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], enabled=False))
    monkeypatch.setattr(cs, "get_settings", fake_get_settings)

    async def fake_verify_tick(*a, **kw):
        calls["verify_tick"] += 1
        return {"checked": 0, "closed": 0, "deleted": 0, "failed": 0}
    monkeypatch.setattr(cs, "verify_tick", fake_verify_tick)

    async def fake_logged_run(c, *, pipeline, trigger, run, **kw):
        calls["logged_run"] += 1
        return await run()
    monkeypatch.setattr(cs, "logged_run", fake_logged_run)

    conn = _Conn(has_pending=False)
    await cs.verify_job(lambda: (_Pool(conn), object(), Activity()))
    assert calls == {"verify_tick": 0, "logged_run": 0}


async def test_verify_job_runs_when_enabled(monkeypatch):
    from app.settings_repo import Settings, SETTINGS_DEFAULTS
    calls = {"verify_tick": 0, "pipeline": None, "trigger": None}

    async def fake_get_settings(c):
        return Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], enabled=True))
    monkeypatch.setattr(cs, "get_settings", fake_get_settings)

    async def fake_verify_tick(*a, **kw):
        calls["verify_tick"] += 1
        return {"checked": 1, "closed": 0, "deleted": 0, "failed": 0}
    monkeypatch.setattr(cs, "verify_tick", fake_verify_tick)

    async def fake_logged_run(c, *, pipeline, trigger, run, **kw):
        calls["pipeline"], calls["trigger"] = pipeline, trigger
        return await run()
    monkeypatch.setattr(cs, "logged_run", fake_logged_run)

    conn = _Conn(has_pending=False)
    await cs.verify_job(lambda: (_Pool(conn), object(), Activity()))
    assert calls["verify_tick"] == 1
    assert calls["pipeline"] == "verify" and calls["trigger"] == "scheduled"
```

`_Conn(has_pending=...)`·`_Pool`·`Activity`는 이 파일에 이미 있는 대역이다. `_Conn.fetchval`은 `status='pending'`이 아닌 SQL에는 `None`을 돌려주므로 재검증 경로에 그대로 쓸 수 있다.

`backend/tests/test_verify_router.py` (신규):

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import verify as verify_router


class FakeConn:
    async def fetchrow(self, sql, *args): return None
    async def execute(self, sql, *args): return "UPDATE 0"
    async def fetchval(self, sql, *args): return None


def make_app(monkeypatch):
    app = FastAPI()
    app.state.http = object()
    app.include_router(verify_router.router)
    app.dependency_overrides[verify_router.get_conn] = lambda: FakeConn()
    return app


def test_manual_verify_returns_counts(monkeypatch):
    async def fake_tick(conn, *, http, on_stage=None):
        return {"checked": 3, "closed": 1, "deleted": 0, "failed": 0}
    monkeypatch.setattr(verify_router, "verify_tick", fake_tick)
    app = make_app(monkeypatch)
    r = TestClient(app).post("/api/verify/run")
    assert r.status_code == 202
    assert r.json()["closed"] == 1 and r.json()["checked"] == 3
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && python -m pytest tests/test_collect_scheduler.py tests/test_verify_router.py -v`
Expected: FAIL — `"verify" not in sched.jobs`, `ModuleNotFoundError: app.routers.verify`

- [ ] **Step 3: `run_log.py`에 파이프라인 라벨 추가**

`_KO` 딕셔너리에 항목 하나를 더한다:

```python
_KO = {"collector": "수집", "worker": "요약 처리", "research": "리서치",
       "notifier": "알림 발송", "verify": "생존 확인"}
```

- [ ] **Step 4: `collect_scheduler.py`에 잡 등록**

임포트에 추가:

```python
from app.collect.verify import VERIFY_HOUR, verify_tick
```

`notifier_job` 아래에 잡 본체를 추가한다(`collector_job`과 같은 구조):

```python
async def verify_job(get_ctx) -> None:
    pool, http, activity = get_ctx()
    async with pool.acquire() as conn:
        settings = await get_settings(conn)
        if not settings.enabled:
            return
        await logged_run(
            conn, pipeline="verify", trigger="scheduled",
            clear=lambda: activity.clear("verify"),
            run=lambda: verify_tick(conn, http=http,
                                    on_stage=lambda st, d, p: activity.set_stage("verify", st, d, str(p))),
        )
```

`start_collect_scheduler`의 잡 등록부에 한 줄 추가(`notifier` 등록 다음):

```python
    sched.add_job(verify_job, "cron", id="verify", hour=VERIFY_HOUR, minute=0, args=[get_ctx])
```

- [ ] **Step 5: 수동 트리거 라우터 작성**

`backend/app/routers/verify.py`:

```python
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.collect.verify import verify_tick
from app.db import get_conn
from app.run_log import logged_run

router = APIRouter(prefix="/api", tags=["verify"])


@router.post("/verify/run", status_code=202)
async def run_verify(request: Request, conn: Any = Depends(get_conn)):
    # 수동 실행은 settings.enabled와 무관 — 배포 직후 첫 검사를 자정까지
    # 기다리지 않고 검증하기 위한 명시적 행동이다(수집기·알림기와 동일 규칙).
    return await logged_run(
        conn, pipeline="verify", trigger="manual",
        run=lambda: verify_tick(conn, http=request.app.state.http),
    )
```

- [ ] **Step 6: `main.py`에 라우터 include**

임포트 블록(현재 `app/main.py:10-18`, 알파벳순)의 `status_router` 다음 줄에 추가:

```python
from app.routers import verify as verify_router
```

include 블록(현재 `app/main.py:55-62`)의 `notify_router` 다음 줄에 추가:

```python
app.include_router(verify_router.router)
```

- [ ] **Step 7: 통과 확인**

Run: `cd backend && python -m pytest tests/test_collect_scheduler.py tests/test_verify_router.py -v`
Expected: PASS

- [ ] **Step 8: 전체 스위트**

Run: `cd backend && python -m pytest -q`
Expected: 232 passed

- [ ] **Step 9: 커밋**

```bash
git add backend/app/collect_scheduler.py backend/app/routers/verify.py backend/app/main.py backend/app/run_log.py backend/tests/test_collect_scheduler.py backend/tests/test_verify_router.py
git commit -m "feat(verify): 자정 스케줄 잡 + 수동 트리거 + 실행 로그 라벨"
```

---

### Task 5: 목록·알림에서 숨기기

**Files:**
- Modify: `backend/app/jobs_repo.py`(`build_list_query`)
- Modify: `backend/app/notify/notifier.py:57-62`(`SELECT_SQL`)
- Test: `backend/tests/test_jobs_repo.py`, `backend/tests/test_notifier_pure.py`

**Interfaces:**
- Consumes: Task 1의 `jobs.posting_state`
- Produces: 없음(질의 변경)

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_jobs_repo.py` 끝에 추가:

```python
def test_list_query_always_hides_non_open_postings():
    from app.jobs_repo import build_list_query
    sql, params = build_list_query()
    assert "posting_state = 'open'" in sql          # 필터가 하나도 없어도 붙는다
    sql2, params2 = build_list_query(status="done", keyword="AI")
    assert "posting_state = 'open'" in sql2


def test_list_query_keeps_limit_offset_last():
    from app.jobs_repo import build_list_query
    sql, params = build_list_query(keyword="AI", limit=20, offset=40)
    assert params[-2:] == [20, 40]                  # posting_state는 파라미터가 아님


def test_detail_query_does_not_filter_dead_postings():
    """디스코드 링크·북마크로 들어온 사용자에게 404를 내면 안 된다 — 목록에서만 뺀다."""
    from app.jobs_repo import _DETAIL_SQL
    assert "posting_state" not in _DETAIL_SQL
```

`backend/tests/test_notifier_pure.py` 끝에 추가:

```python
def test_notifier_select_excludes_dead_postings():
    from app.notify.notifier import SELECT_SQL
    # 마감된 공고를 디스코드로 보내는 것은 명백한 오동작.
    assert "posting_state = 'open'" in SELECT_SQL
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && python -m pytest tests/test_jobs_repo.py tests/test_notifier_pure.py -v -k "posting_state or open"`
Expected: FAIL — `assert "posting_state = 'open'" in sql`

- [ ] **Step 3: `jobs_repo.py` 수정**

`build_list_query`의 `clauses`/`params` 초기화 직후, `add` 헬퍼 정의 다음에 절을 추가한다(전역 필터보다 앞, `where` 조립보다 훨씬 앞):

```python
    # 마감·삭제된 공고는 항상 숨긴다. 사용자 입력이 아니고 늘 적용되므로 리터럴.
    clauses.append("posting_state = 'open'")
```

- [ ] **Step 4: `notifier.py` 수정**

`SELECT_SQL`을 아래로 교체:

```python
SELECT_SQL = (
    "SELECT id, source, job_id, company, title, url, locations, "
    "min_career, max_career, tech_stacks, summary "
    "FROM jobs WHERE status='done' AND notified_at IS NULL "
    "AND posting_state = 'open' "
    "ORDER BY collected_at LIMIT $1"
)
```

- [ ] **Step 5: 통과 확인**

Run: `cd backend && python -m pytest tests/test_jobs_repo.py tests/test_jobs_routes.py tests/test_notifier_pure.py tests/test_notify_tick.py -v`
Expected: PASS

- [ ] **Step 6: 전체 스위트**

Run: `cd backend && python -m pytest -q`
Expected: 236 passed

- [ ] **Step 7: 커밋**

```bash
git add backend/app/jobs_repo.py backend/app/notify/notifier.py backend/tests/test_jobs_repo.py backend/tests/test_notifier_pure.py
git commit -m "feat(jobs): 마감·삭제 공고를 목록과 알림에서 제외"
```

---

### Task 6: 수집 시 되살아남

**Files:**
- Modify: `backend/app/collect/collector.py`(`collect`)
- Test: `backend/tests/test_collector.py`

**Interfaces:**
- Consumes: Task 1의 `jobs.posting_state`
- Produces: `REVIVE_SQL` (모듈 상수)

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_collector.py` 끝에 추가. 이 파일의 `FakeConn`은 `fetchval`만 갖고 있으므로 `execute`를 기록하도록 확장한다(기존 테스트는 영향 없음 — 파일 상단 `FakeConn`에 메서드를 더할 것):

```python
async def test_collect_revives_previously_dead_postings():
    """목록에 다시 보였다는 것은 살아있다는 뜻 — 오판정·재게시를 자동 복구한다."""
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["백엔드"], max_pages=3))
    conn = FakeConn()
    await collect(conn, s, http=FakeHttp())
    revives = [(sql, a) for sql, a in conn.executed if "posting_state" in sql]
    assert len(revives) == 1
    sql, args = revives[0]
    assert "posting_state <> 'open'" in sql
    assert sorted(args[0]) == ["jumpit", "wanted"]   # $1 source 배열
    assert sorted(args[1]) == ["1", "10"]            # $2 job_id 배열


async def test_collect_skips_revive_when_nothing_scraped():
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["백엔드"], max_pages=3))
    conn = FakeConn()
    await collect(conn, s, http=FakeHttpMalformedJumpit())   # 0건
    assert [sql for sql, _a in conn.executed if "posting_state" in sql] == []


async def test_revive_does_not_inflate_inserted_count():
    """되살아남은 UPDATE라 inserted(RETURNING id 기반)에 영향을 주면 안 된다."""
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["백엔드"], max_pages=3))
    conn = FakeConn(existing={("jumpit", "1"), ("wanted", "10")})   # 둘 다 이미 있음
    result = await collect(conn, s, http=FakeHttp())
    assert result == {"scraped": 2, "inserted": 0}
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && python -m pytest tests/test_collector.py -v -k revive`
Expected: FAIL — `AttributeError: 'FakeConn' object has no attribute 'executed'` 또는 `assert len(revives) == 1` 실패

- [ ] **Step 3: `FakeConn`에 execute 기록 추가**

`backend/tests/test_collector.py`의 `FakeConn`을 아래로 교체(기존 `fetchval` 동작은 그대로):

```python
class FakeConn:
    """실제 conn 대역: fetchval이 INSERT … ON CONFLICT DO NOTHING RETURNING id를 흉내낸다.
    이미 있는 (source, job_id)는 None(중복→건너뜀), 새 키는 가짜 id(비-None)를 반환."""
    def __init__(self, existing=()):
        self.existing = set(existing)
        self.inserts = []          # 실제로 새로 들어간 키
        self.executed = []         # (sql, args) — 되살아남 UPDATE 등
    async def fetchval(self, sql, *args):
        key = (args[0], args[1])   # $1 source, $2 job_id
        if key in self.existing:
            return None
        self.existing.add(key)
        self.inserts.append(key)
        return len(self.inserts)   # 가짜 id
    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return "UPDATE 0"
```

- [ ] **Step 4: `collector.py` 구현**

모듈 상수에 추가(`INSERT_SQL` 아래):

```python
# 목록에 다시 보인 공고는 살아있다 — 재검증기의 오판정과 재게시를 자동 복구한다.
# INSERT의 ON CONFLICT DO UPDATE로 합치지 않는 이유: RETURNING id에 중복 행까지
# 잡혀 inserted 카운트가 다시 거짓말을 하게 된다.
REVIVE_SQL = (
    "UPDATE jobs SET posting_state = 'open', state_checked_at = NULL "
    "WHERE posting_state <> 'open' "
    "AND (source, job_id) IN (SELECT unnest($1::text[]), unnest($2::text[]))"
)
```

`collect`의 삽입 루프 다음, `log.info` 앞에 추가:

```python
    if rows:
        await conn.execute(REVIVE_SQL, [r["source"] for r in rows],
                           [r["job_id"] for r in rows])
```

- [ ] **Step 5: 통과 확인**

Run: `cd backend && python -m pytest tests/test_collector.py -v`
Expected: PASS (11 passed)

- [ ] **Step 6: 전체 스위트**

Run: `cd backend && python -m pytest -q`
Expected: 239 passed

- [ ] **Step 7: 커밋**

```bash
git add backend/app/collect/collector.py backend/tests/test_collector.py
git commit -m "feat(collect): 목록에 다시 보인 공고는 open으로 되살림"
```

---

### Task 7: 실행 로그에 `verify` 파이프라인 표시

**Files:**
- Modify: `frontend/src/runsApi.ts`(`Pipeline` 유니온)
- Modify: `frontend/src/runsFormat.ts`(`pipelineLabel`, `runSummary`)
- Test: `frontend/src/runsFormat.test.ts`

**Interfaces:**
- Consumes: Task 3의 반환 dict `{"checked", "closed", "deleted", "failed"}`
- Produces: 없음(최종 표면)

- [ ] **Step 1: 실패하는 테스트 작성**

`frontend/src/runsFormat.test.ts` 끝에 추가. 이 파일 상단의 `item(over: Partial<RunLogItem>)` 헬퍼를 쓴다:

```ts
test("verify 파이프라인 라벨", () => {
  expect(pipelineLabel("verify")).toBe("생존 확인");
});

test("verify 요약 — 마감·삭제 건수", () => {
  expect(runSummary(item({
    pipeline: "verify", result: { checked: 476, closed: 139, deleted: 11, failed: 0 },
  }))).toBe("확인 476건 · 마감 139 · 삭제 11");
});

test("verify 요약 — 아무것도 죽지 않았으면 건수만", () => {
  expect(runSummary(item({
    pipeline: "verify", result: { checked: 476, closed: 0, deleted: 0, failed: 0 },
  }))).toBe("확인 476건");
});

test("verify 요약 — 판정 불가가 있으면 표시", () => {
  expect(runSummary(item({
    pipeline: "verify", result: { checked: 476, closed: 0, deleted: 0, failed: 476 },
  }))).toBe("확인 476건 · 실패 476");
});
```

- [ ] **Step 2: 실패 확인**

Run: `cd frontend && npx vitest run src/runsFormat.test.ts`
Expected: FAIL — `expected "리서치" to be "생존 확인"`

- [ ] **Step 3: `runsApi.ts`의 유니온 확장**

`Pipeline` 유니온 타입에 `"verify"`를 더한다(파일에서 `"notifier"`가 들어 있는 유니온을 찾아 그 옆에 추가).

- [ ] **Step 4: `runsFormat.ts` 수정**

`pipelineLabel`을 아래로 교체:

```ts
export function pipelineLabel(p: string): string {
  return p === "collector" ? "수집기" : p === "worker" ? "요약"
    : p === "notifier" ? "알림" : p === "verify" ? "생존 확인" : "리서치";
}
```

`runSummary`의 `notifier` 분기 다음에 추가:

```ts
  if (it.pipeline === "verify") {
    const closed = Number(r.closed ?? 0);
    const deleted = Number(r.deleted ?? 0);
    const failed = Number(r.failed ?? 0);
    return `확인 ${r.checked ?? 0}건`
      + (closed ? ` · 마감 ${closed}` : "")
      + (deleted ? ` · 삭제 ${deleted}` : "")
      + (failed ? ` · 실패 ${failed}` : "");
  }
```

- [ ] **Step 5: 통과 확인**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: 58 + 4 = 62 passed, 타입 에러 없음

- [ ] **Step 6: 표시 테스트가 의미 있는지 검증**

`pipelineLabel`의 `p === "verify" ? "생존 확인" :` 부분을 잠시 지우고 실행:

Run: `cd frontend && npx vitest run src/runsFormat.test.ts`
Expected: **FAIL**

복구 후 재실행 → PASS. 결과를 보고서에 남긴다.

- [ ] **Step 7: 커밋**

```bash
git add frontend/src/runsApi.ts frontend/src/runsFormat.ts frontend/src/runsFormat.test.ts
git commit -m "feat(ops): 실행 로그에 생존 확인 파이프라인 표시"
```

---

## 배포 후 검증 (구현·머지 후, 운영자가 수행)

1. 배포 — 전 행이 `posting_state='open'`이라 **동작 불변**.
2. `POST /api/verify/run`으로 첫 전수검사를 수동 실행한다. 응답을 기다리지 말고 `run_log`로 확인한다.
3. 결과를 표본 예측치와 대조: **원티드 약 139건(32%), 점핏 13건, 합계 약 150건.**
   - 실제가 훨씬 많으면 판정 불가를 `closed`로 잘못 처리하고 있을 가능성 — 로직을 의심한다.
   - `failed`가 `checked`에 근접하면 감지가 아니라 프록시·네트워크 문제다.
4. 목록에서 해당 공고들이 사라지고 남은 수가 예상과 맞는지 확인한다.

되돌리기: `UPDATE jobs SET posting_state='open';` 한 줄로 전부 복구된다.
