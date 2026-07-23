# LLM 모델 티어 + 요약 claude 이관 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `claude -p` 호출에 작업 난이도별 모델 티어(haiku/sonnet/opus)를 도입하고, 공고 요약을 로컬 LLM에서 claude로 옮길 수 있게 만든다.

**Architecture:** 티어 정책을 담는 순수 모듈 `app/llm_tier.py`를 신설하고, `run_claude`에 `--model` 플래그를 뚫는다. 작업별 기본 티어는 코드 상수, 설정(`app_settings.summary_model`/`research_model`)이 있으면 그것이 이긴다. 재시도할 때만 한 단계 위 티어로 승급한다 — 요약은 `jobs.attempts > 0`, 리서치는 JSON 파싱 실패 재시도.

**Tech Stack:** Python 3.12 / FastAPI / asyncpg / Alembic / pytest(asyncio_mode=auto), React 18 / TypeScript / Vite / vitest

**스펙:** `docs/superpowers/specs/2026-07-24-llm-model-tier-design.md`

## Global Constraints

- 모델 별칭은 `("haiku", "sonnet", "opus")` 세 개만 허용한다. 풀네임 핀은 범위 밖.
- 승급 사다리는 `haiku < sonnet < opus`. 상한(`opus`)에서의 승급은 **예외가 아니라 `opus` 그대로 반환**한다.
- 작업별 기본 티어: `{"summary": "haiku", "research": "sonnet"}`.
- `run_claude(model="")`이면 argv가 현재와 **완전히 동일**해야 한다(`--model` 미부착). 기존 호출자 무손상.
- 설정 기본값은 `summary_model=""`, `research_model=""` — DDL의 `DEFAULT ''`, `SETTINGS_DEFAULTS`, Pydantic 모델 세 곳이 모두 일치해야 한다.
- `settings.model`은 LM Studio 로컬 모델명이다. **개명하지 않는다** — 화면 라벨만 `로컬 모델`로 바꾼다.
- `summarize`의 local 분기는 손대지 않는다. `model` 인자는 claude 분기에서만 쓴다.
- LM Studio 헬스 게이트는 `summary_backend == "local"`일 때만 적용한다.
- 리서치 러너의 `settings` 인자는 **키워드 전용, 기본값 `None`**이며 `None`은 "코드 기본 티어"를 뜻한다.
- 리서치 실패 경로(`status="failed"`)에는 **1차 시도 모델**을 기록한다.
- 리서치 테이블명은 `company_research` / `job_research`다.
- 백엔드 테스트: `cd backend && python -m pytest`. 프론트: `cd frontend && npx vitest run` + `npx tsc --noEmit`.
- 커밋 메시지는 한국어, 기존 컨벤션(`feat:`/`fix:`/`docs:`)을 따른다.

## 파일 구조

| 파일 | 책임 | 태스크 |
|---|---|---|
| `backend/app/llm_tier.py` (신규) | 티어 사다리·기본값·해석/승급. 순수 함수만 | 1 |
| `backend/app/claude_client.py` | `claude -p` 프로세스 실행. `--model` 전달 | 2 |
| `backend/migrations/versions/0007_task_models.py` (신규) | `summary_model`·`research_model` 컬럼 | 3 |
| `backend/app/settings_repo.py` | 설정 3중 동기화 + 별칭 검증 | 3 |
| `backend/app/collect/summarize.py` | claude 분기에 `model` 전달 | 4 |
| `backend/app/collect/worker.py` | 잡별 티어 해석·승급 카운트·헬스 게이트 조건화 | 4 |
| `backend/app/research/runner.py` | 리서치 티어 해석·파싱 실패 승급·실제 모델 반환 | 5 |
| `backend/app/research/config.py` | 죽은 `RESEARCH_MODEL` 제거 | 5 |
| `backend/app/routers/research.py` | 응답 전 설정 조회 → BackgroundTask로 전달 | 6 |
| `backend/app/research/scheduler.py` | 자동 틱에 설정 전달 | 6 |
| `backend/app/research/__main__.py` | CLI에 설정 전달 | 6 |
| `backend/app/jobs_repo.py` | 공고 상세에 `jr_model` 노출 | 7 |
| `frontend/src/ResearchPanel.tsx` | 사용 모델 칩 | 7 |
| `frontend/src/settingsApi.ts` | `Settings` 타입 2필드 | 8 |
| `frontend/src/pages/Ops.tsx` | 모델 셀렉트 2개 + 라벨 변경 | 8 |
| `frontend/src/runsFormat.ts` | 실행 로그 `·승급 N` | 8 |

---

### Task 1: 티어 모듈

**Files:**
- Create: `backend/app/llm_tier.py`
- Test: `backend/tests/test_llm_tier.py`

**Interfaces:**
- Consumes: 없음(순수 모듈, 프로젝트 내 임포트 없음)
- Produces:
  - `LADDER: tuple[str, str, str]` = `("haiku", "sonnet", "opus")`
  - `TASK_MODEL: dict[str, str]` = `{"summary": "haiku", "research": "sonnet"}`
  - `escalate(model: str) -> str`
  - `resolve(task: str, override: str = "", *, escalated: bool = False) -> str`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_llm_tier.py`:

```python
import pytest
from app.llm_tier import LADDER, TASK_MODEL, escalate, resolve


def test_ladder_is_ordered_cheap_to_capable():
    assert LADDER == ("haiku", "sonnet", "opus")


def test_task_defaults():
    assert TASK_MODEL == {"summary": "haiku", "research": "sonnet"}


def test_escalate_steps_up_one_rung():
    assert escalate("haiku") == "sonnet"
    assert escalate("sonnet") == "opus"


def test_escalate_caps_at_top():
    """상한에서 예외를 던지면 opus로 고정한 사용자의 재시도가 크래시한다."""
    assert escalate("opus") == "opus"


def test_escalate_passes_through_values_off_the_ladder():
    assert escalate("gpt-4") == "gpt-4"
    assert escalate("") == ""


def test_resolve_uses_task_default_when_no_override():
    assert resolve("summary") == "haiku"
    assert resolve("research") == "sonnet"


def test_resolve_override_wins():
    assert resolve("summary", "opus") == "opus"


def test_resolve_blank_override_falls_back_to_default():
    assert resolve("summary", "   ") == "haiku"
    assert resolve("research", "") == "sonnet"


def test_resolve_escalated_steps_up_from_the_resolved_value():
    assert resolve("summary", escalated=True) == "sonnet"
    assert resolve("research", escalated=True) == "opus"
    assert resolve("summary", "sonnet", escalated=True) == "opus"
    assert resolve("research", "opus", escalated=True) == "opus"


def test_resolve_unknown_task_raises():
    """오타난 작업명을 조용히 기본 티어로 넘기지 않는다."""
    with pytest.raises(KeyError):
        resolve("mailcheck")
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && python -m pytest tests/test_llm_tier.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.llm_tier'`

- [ ] **Step 3: 구현**

`backend/app/llm_tier.py`:

```python
"""claude -p 호출의 작업별 모델 티어.

정책만 담는다 — 프로세스 실행은 app.claude_client, 저장은 app.settings_repo.
소비자가 collect/summarize.py와 research/runner.py 둘이라, 어느 한쪽에 두면
다른 패키지를 끌어온다.
"""

# 싼 것 → 유능한 것 순. 승급은 이 순서로 한 칸씩 올라간다.
LADDER = ("haiku", "sonnet", "opus")

# 작업 종류별 기본 티어. 설정 오버라이드가 비어 있을 때 쓰인다.
TASK_MODEL = {"summary": "haiku", "research": "sonnet"}


def escalate(model: str) -> str:
    """한 단계 위 티어. 상한이거나 사다리 밖 값이면 그대로 반환.

    상한에서 예외를 던지지 않는 이유: 설정으로 opus를 고정한 사용자의
    재시도가 크래시하면 안 된다. 상한에서의 승급 = 같은 모델로 재시도.
    """
    try:
        i = LADDER.index(model)
    except ValueError:
        return model
    return LADDER[min(i + 1, len(LADDER) - 1)]


def resolve(task: str, override: str = "", *, escalated: bool = False) -> str:
    """override(설정) → 비어 있으면 TASK_MODEL[task]. escalated면 한 단계 승급.

    알 수 없는 task는 KeyError — 오타를 조용히 기본 티어로 넘기지 않는다.
    """
    model = (override or "").strip() or TASK_MODEL[task]
    return escalate(model) if escalated else model
```

- [ ] **Step 4: 통과 확인**

Run: `cd backend && python -m pytest tests/test_llm_tier.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: 전체 스위트 확인**

Run: `cd backend && python -m pytest -q`
Expected: 161(기존) + 10 = 171 passed

- [ ] **Step 6: 커밋**

```bash
git add backend/app/llm_tier.py backend/tests/test_llm_tier.py
git commit -m "feat(llm): 작업별 모델 티어 모듈(사다리·기본값·승급)"
```

---

### Task 2: `run_claude`에 `--model` 전달

**Files:**
- Modify: `backend/app/claude_client.py:24-35`
- Test: `backend/tests/test_claude_client.py`

**Interfaces:**
- Consumes: 없음(티어 모듈에 의존하지 않는다 — `run_claude`는 받은 문자열을 그대로 전달만 한다)
- Produces: `run_claude(prompt, *, model: str = "", allowed_tools="", timeout=120, claude_bin="claude", on_step=None) -> str`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_claude_client.py` 끝에 추가. `_lines`·`FakeProc`은 파일 상단에 이미 있다.

```python
async def test_run_claude_omits_model_flag_when_unset(monkeypatch):
    """model=""이면 명령줄이 현재와 동일해야 한다 — 기존 호출자 무손상."""
    seen = {}

    async def fake_exec(*args, **kwargs):
        seen["args"] = list(args)
        return FakeProc(_lines({"type": "result", "result": "ok"}))

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    assert await run_claude("hi") == "ok"
    assert "--model" not in seen["args"]


async def test_run_claude_passes_model_flag(monkeypatch):
    seen = {}

    async def fake_exec(*args, **kwargs):
        seen["args"] = list(args)
        return FakeProc(_lines({"type": "result", "result": "ok"}))

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    assert await run_claude("hi", model="haiku") == "ok"
    args = seen["args"]
    assert args[args.index("--model") + 1] == "haiku"


async def test_run_claude_keeps_allowed_tools_alongside_model(monkeypatch):
    seen = {}

    async def fake_exec(*args, **kwargs):
        seen["args"] = list(args)
        return FakeProc(_lines({"type": "result", "result": "ok"}))

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    await run_claude("hi", model="opus", allowed_tools="WebSearch")
    args = seen["args"]
    assert args[args.index("--model") + 1] == "opus"
    assert args[args.index("--allowedTools") + 1] == "WebSearch"
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && python -m pytest tests/test_claude_client.py -v -k model`
Expected: FAIL — `TypeError: run_claude() got an unexpected keyword argument 'model'`

- [ ] **Step 3: 구현**

`backend/app/claude_client.py`의 `run_claude` 시그니처와 argv 조립을 아래로 교체:

```python
async def run_claude(
    prompt: str,
    *,
    model: str = "",
    allowed_tools: str = "",
    timeout: int = 120,
    claude_bin: str = "claude",
    on_step=None,
) -> str:
    """`claude -p`를 stream-json으로 실행. 이벤트마다 on_step(label) 호출, 최종 result 반환."""
    args = [claude_bin, "-p", prompt, "--output-format", "stream-json", "--verbose"]
    if model:
        args += ["--model", model]
    if allowed_tools:
        args += ["--allowedTools", allowed_tools]
```

함수 나머지(프로세스 기동·`_consume`·타임아웃 처리)는 그대로 둔다.

- [ ] **Step 4: 통과 확인**

Run: `cd backend && python -m pytest tests/test_claude_client.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: 전체 스위트 확인**

Run: `cd backend && python -m pytest -q`
Expected: 174 passed

- [ ] **Step 6: 커밋**

```bash
git add backend/app/claude_client.py backend/tests/test_claude_client.py
git commit -m "feat(llm): run_claude에 --model 전달(빈 값이면 미부착)"
```

---

### Task 3: 설정 컬럼 + 별칭 검증

**Files:**
- Create: `backend/migrations/versions/0007_task_models.py`
- Modify: `backend/app/settings_repo.py:6-26`(DEFAULTS·_COLUMNS), `backend/app/settings_repo.py:29-56`(모델·validator)
- Test: `backend/tests/test_settings_repo.py`

**Interfaces:**
- Consumes: `app.llm_tier.LADDER`
- Produces: `Settings.summary_model: str = ""`, `Settings.research_model: str = ""` (모두 `SETTINGS_DEFAULTS`와 `_COLUMNS`에 포함)

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_settings_repo.py` 끝에 추가:

```python
def test_task_models_default_to_empty():
    from app.settings_repo import Settings, SETTINGS_DEFAULTS
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"]))
    assert s.summary_model == ""
    assert s.research_model == ""


def test_task_models_accept_ladder_aliases():
    from app.settings_repo import Settings, SETTINGS_DEFAULTS
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"],
                        summary_model="haiku", research_model="opus"))
    assert s.summary_model == "haiku"
    assert s.research_model == "opus"


def test_task_models_reject_unknown_alias():
    """오타를 저장 시점에 막는다 — 안 막으면 배포 후 첫 실행에서 프로세스 실패로 드러난다."""
    from app.settings_repo import Settings, SETTINGS_DEFAULTS
    with pytest.raises(ValidationError):
        Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], summary_model="gpt-4"))
    with pytest.raises(ValidationError):
        Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], research_model="claude-opus-4-8"))


def test_task_models_normalize_blank_to_empty():
    from app.settings_repo import Settings, SETTINGS_DEFAULTS
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], research_model="   "))
    assert s.research_model == ""


def test_upsert_includes_task_model_columns():
    from app.settings_repo import Settings, SETTINGS_DEFAULTS, build_upsert
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"],
                        summary_model="sonnet", research_model="opus"))
    sql, params = build_upsert(s)
    assert "summary_model" in sql and "research_model" in sql
    assert params[-2] == "sonnet"
    assert params[-1] == "opus"


def test_migration_defaults_match_settings_defaults():
    """DDL의 DEFAULT와 SETTINGS_DEFAULTS가 어긋나면 배포 직후 동작이 조용히 바뀐다."""
    from pathlib import Path
    from app.settings_repo import SETTINGS_DEFAULTS
    ddl = (Path(__file__).resolve().parents[1]
           / "migrations" / "versions" / "0007_task_models.py").read_text()
    assert "summary_model text NOT NULL DEFAULT ''" in ddl
    assert "research_model text NOT NULL DEFAULT ''" in ddl
    assert SETTINGS_DEFAULTS["summary_model"] == ""
    assert SETTINGS_DEFAULTS["research_model"] == ""
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && python -m pytest tests/test_settings_repo.py -v -k task_model`
Expected: FAIL — `Settings` 에 `summary_model` 필드가 없어 `ValidationError`(extra field) 또는 `AttributeError`

- [ ] **Step 3: 마이그레이션 작성**

`backend/migrations/versions/0007_task_models.py`:

```python
"""작업별 claude 모델 티어 오버라이드

Revision ID: 0007_task_models
Revises: 0006_notify_enabled
Create Date: 2026-07-24
"""
from alembic import op

revision = "0007_task_models"
down_revision = "0006_notify_enabled"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE app_settings "
        "ADD COLUMN IF NOT EXISTS summary_model text NOT NULL DEFAULT '', "
        "ADD COLUMN IF NOT EXISTS research_model text NOT NULL DEFAULT '';"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE app_settings "
        "DROP COLUMN IF EXISTS summary_model, "
        "DROP COLUMN IF EXISTS research_model;"
    )
```

- [ ] **Step 4: `settings_repo.py` 3중 동기화**

파일 상단 임포트에 추가:

```python
from app.llm_tier import LADDER
```

`SETTINGS_DEFAULTS`의 `notify_enabled=False,` 다음 줄에 추가:

```python
    summary_model="", research_model="",
```

`_COLUMNS` 리스트의 `"notify_enabled",` 다음 줄에 추가:

```python
    "summary_model", "research_model",
```

`Settings` 클래스에서 `notify_enabled: bool = False` 다음, `updated_at` 앞에 추가:

```python
    # claude 모델 티어 오버라이드. 빈 문자열이면 llm_tier.TASK_MODEL의 코드 기본값.
    summary_model: str = ""
    research_model: str = ""
```

`Settings` 클래스의 `_clean_keywords` validator 아래에 추가:

```python
    @field_validator("summary_model", "research_model")
    @classmethod
    def _tier_alias(cls, v: str) -> str:
        v = (v or "").strip()
        if v and v not in LADDER:
            raise ValueError(f"model must be empty or one of {LADDER}")
        return v
```

- [ ] **Step 5: 통과 확인**

Run: `cd backend && python -m pytest tests/test_settings_repo.py -v`
Expected: PASS (전부 통과 — 기존 `test_build_upsert_is_singleton_and_parameterized`의 `"$14" in sql`도 컬럼이 17개로 늘어도 여전히 참)

- [ ] **Step 6: 전체 스위트 확인**

Run: `cd backend && python -m pytest -q`
Expected: 180 passed

- [ ] **Step 7: 커밋**

```bash
git add backend/migrations/versions/0007_task_models.py backend/app/settings_repo.py backend/tests/test_settings_repo.py
git commit -m "feat(settings): 작업별 모델 티어 오버라이드 컬럼 + 별칭 검증"
```

---

### Task 4: 요약 티어 + 승급 + 헬스 게이트 조건화

**Files:**
- Modify: `backend/app/collect/summarize.py:22-26`
- Modify: `backend/app/collect/worker.py:45-78`
- Test: `backend/tests/test_collect_summarize.py`, `backend/tests/test_worker.py`

**Interfaces:**
- Consumes: `app.llm_tier.resolve`, `Settings.summary_model`, `run_claude(model=...)`
- Produces:
  - `summarize(prompt, settings, *, http, model: str = "", runner=run_claude, on_step=None) -> str | None`
  - `worker_tick(...) -> dict` 반환에 `"escalated": int` 키 추가(승급 티어로 요약을 **시도한** 잡 수)

- [ ] **Step 1: 기존 테스트 fake 시그니처 갱신**

`backend/tests/test_worker.py`의 summarizer fake 3개는 `model` 키워드를 받지 못해 깨진다. 세 곳 모두 `model=""`를 추가한다.

```python
# test_worker_summarizes_and_marks_done
    async def summ(prompt, settings, *, http, model="", on_step=None): return "요약본\n기술스택: Go"

# test_worker_retry_cap_marks_failed_on_empty
    async def summ(prompt, settings, *, http, model="", on_step=None): return None  # 빈 응답

# test_worker_summarizer_error_routes_to_retry
    async def boom(prompt, settings, *, http, model="", on_step=None): raise RuntimeError("llm error mid-call")
```

- [ ] **Step 2: 실패하는 테스트 작성**

`backend/tests/test_collect_summarize.py` 끝에 추가:

```python
async def test_summarize_claude_forwards_model():
    calls = {}

    async def fake_runner(prompt, *, model="", on_step=None, **kw):
        calls["model"] = model
        return "클로드 요약"

    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], summary_backend="claude"))
    await summarize("공고", s, http=Http(), model="haiku", runner=fake_runner)
    assert calls["model"] == "haiku"


async def test_summarize_local_ignores_model_arg():
    """local 분기는 티어와 무관 — settings.model(LM Studio 모델명)을 그대로 쓴다."""
    http = Http(post_resp=Resp(200, {"choices": [{"message": {"content": "3줄"}}]}))
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], summary_backend="local"))
    out = await summarize("공고", s, http=http, model="opus")
    assert out == "3줄"
    assert http.posted["model"] == s.model
```

`backend/tests/test_worker.py` 끝에 추가:

```python
_DETAIL = {"result": {"responsibility": "일", "qualifications": "q", "preferredRequirements": "p"}}


def _claimed(attempts: int):
    return [{"id": 1, "source": "jumpit", "job_id": "5", "company": "A",
             "title": "T", "attempts": attempts}]


async def _up(http, base_url=None):
    return True


async def test_worker_uses_base_tier_for_fresh_job():
    conn = Conn(_claimed(0))
    seen = {}

    async def summ(prompt, settings, *, http, model="", on_step=None):
        seen["model"] = model
        return "요약\n기술스택: Go"

    r = await worker_tick(conn, _settings(summary_backend="claude"),
                          http=Http(_DETAIL), summarizer=summ, health=_up)
    assert seen["model"] == "haiku"
    assert r["escalated"] == 0


async def test_worker_escalates_previously_failed_job():
    conn = Conn(_claimed(1))
    seen = {}

    async def summ(prompt, settings, *, http, model="", on_step=None):
        seen["model"] = model
        return "요약\n기술스택: Go"

    r = await worker_tick(conn, _settings(summary_backend="claude"),
                          http=Http(_DETAIL), summarizer=summ, health=_up)
    assert seen["model"] == "sonnet"
    assert r["escalated"] == 1


async def test_worker_setting_override_shifts_the_whole_ladder():
    conn = Conn(_claimed(1))
    seen = {}

    async def summ(prompt, settings, *, http, model="", on_step=None):
        seen["model"] = model
        return "요약"

    await worker_tick(conn, _settings(summary_backend="claude", summary_model="sonnet"),
                      http=Http(_DETAIL), summarizer=summ, health=_up)
    assert seen["model"] == "opus"


async def test_worker_does_not_health_check_when_backend_is_claude():
    """회귀: claude 요약이 LM Studio 헬스에 묶이면 맥이 꺼졌을 때 같이 멈춘다."""
    conn = Conn(_claimed(0))
    calls = []

    async def down(http, base_url=None):
        calls.append(1)
        return False

    async def summ(prompt, settings, *, http, model="", on_step=None):
        return "요약"

    r = await worker_tick(conn, _settings(summary_backend="claude"),
                          http=Http(_DETAIL), summarizer=summ, health=down)
    assert calls == []                 # 호출 자체가 없어야 한다
    assert r["skipped_tick"] is False
    assert r["done"] == 1


async def test_worker_still_health_gates_local_backend():
    conn = Conn([])

    async def down(http, base_url=None):
        return False

    r = await worker_tick(conn, _settings(summary_backend="local"),
                          http=Http(_DETAIL), health=down)
    assert r["skipped_tick"] is True
    assert r["escalated"] == 0
    assert conn.updates == []
```

- [ ] **Step 3: 실패 확인**

Run: `cd backend && python -m pytest tests/test_worker.py tests/test_collect_summarize.py -v`
Expected: FAIL — `KeyError: 'escalated'`, `summarize() got an unexpected keyword argument 'model'`

- [ ] **Step 4: `summarize.py` 구현**

`backend/app/collect/summarize.py`의 `summarize` 함수를 아래로 교체:

```python
async def summarize(prompt, settings, *, http, model="", runner=run_claude, on_step=None) -> str | None:
    if settings.summary_backend == "claude":
        full = f"{SUMMARY_SYSTEM_PROMPT}\n\n{prompt}"
        text = await runner(full, model=model, timeout=SUMMARY_TIMEOUT, on_step=on_step)
        return text or None
    # local: LM Studio OpenAI 호환 chat completions.
    # settings.model은 LM Studio 로컬 모델명 — claude 티어(model 인자)와 무관하다.
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

- [ ] **Step 5: `worker.py` 구현**

임포트에 추가:

```python
from app.llm_tier import resolve
```

`worker_tick`을 아래로 교체:

```python
async def worker_tick(conn, settings, *, http, summarizer=summarize,
                      health=llm_healthy, on_stage=None) -> dict:
    # LM Studio 헬스는 local 백엔드일 때만 본다. claude 요약은 맥 상태와 무관하며,
    # 여기에 묶어두면 맥이 꺼졌을 때 claude 요약까지 같이 멈춘다.
    if settings.summary_backend == "local" and not await health(http):
        return {"claimed": 0, "done": 0, "failed": 0, "escalated": 0, "skipped_tick": True}

    batch = await claim_batch(conn, settings.batch_size)
    if on_stage and batch:
        on_stage("배치 점유", f"{len(batch)}건", 0)
    done = failed = escalated = 0
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
        # 전에 실패한 적 있는 잡은 한 단계 위 티어로 재시도한다.
        # attempts는 상세조회 실패로도 오르지만, 그 부정확은 드물고 무해하다.
        is_retry = job["attempts"] > 0
        model = resolve("summary", settings.summary_model, escalated=is_retry)
        if is_retry:
            escalated += 1
        if on_stage:
            on_stage("요약 중", f"{job.get('company') or ''} · {title}", f"{i+1}/{len(batch)}")
        try:
            content = await summarizer(prompt, settings, http=http, model=model)
        except Exception:  # noqa: BLE001 — 요약 실패도 상세 실패와 동일하게 재시도 캡으로
            content = None
        if content:
            await conn.execute(_DONE_SQL, content, extract_stacks(content), job["id"])
            done += 1
        else:
            await conn.execute(_RETRY_SQL, settings.max_attempts, job["id"])
            failed += 1
    return {"claimed": len(batch), "done": done, "failed": failed,
            "escalated": escalated, "skipped_tick": False}
```

- [ ] **Step 6: 통과 확인**

Run: `cd backend && python -m pytest tests/test_worker.py tests/test_collect_summarize.py -v`
Expected: PASS

- [ ] **Step 7: 회귀 테스트가 의미 있는지 검증**

`worker.py`의 헬스 게이트를 잠시 `if not await health(http):`로 되돌리고 실행:

Run: `cd backend && python -m pytest tests/test_worker.py::test_worker_does_not_health_check_when_backend_is_claude -v`
Expected: **FAIL** (`assert calls == []`이 깨짐)

되돌린 코드를 다시 Step 5의 버전으로 복구하고 재실행:
Expected: PASS

- [ ] **Step 8: 전체 스위트 확인**

Run: `cd backend && python -m pytest -q`
Expected: 187 passed

- [ ] **Step 9: 커밋**

```bash
git add backend/app/collect/summarize.py backend/app/collect/worker.py backend/tests/test_worker.py backend/tests/test_collect_summarize.py
git commit -m "feat(worker): 요약 모델 티어·재시도 승급, 헬스 게이트를 local 백엔드로 한정"
```

---

### Task 5: 리서치 승급 + 실제 사용 모델 기록

**Files:**
- Modify: `backend/app/research/runner.py`
- Modify: `backend/app/research/config.py:3`(`RESEARCH_MODEL` 삭제)
- Test: `backend/tests/test_research_runner.py`

**Interfaces:**
- Consumes: `app.llm_tier.escalate`, `app.llm_tier.resolve`, `Settings.research_model`, `run_claude(model=...)`
- Produces:
  - `_run_and_parse(prompt, runner, model, on_step=None) -> tuple[dict, str]` — (파싱결과, 실제 성공 모델)
  - `research_company(db, company, url="", *, settings=None, force=False, runner=run_claude, notify=push, activity=None) -> str`
  - `research_job(db, source, job_id, *, settings=None, force=False, runner=run_claude, notify=push, activity=None) -> str`
  - `settings=None`은 "코드 기본 티어"를 뜻한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_research_runner.py` 끝에 추가. 파일 상단의 `wired` fixture와 `make_runner`는 그대로 쓴다. `make_runner`의 `fake(prompt, **kw)`가 `model=`를 이미 흡수하므로 기존 테스트는 안 깨진다.

```python
def make_model_recording_runner(*replies):
    """호출마다 (model) 을 기록하는 러너. models 리스트를 함께 반환."""
    replies = list(replies)
    models = []

    async def fake(prompt, *, model="", **kw):
        models.append(model)
        return replies.pop(0)

    return fake, models


class _Settings:
    """research_model만 있는 최소 설정 대역."""
    def __init__(self, research_model=""):
        self.research_model = research_model


async def test_company_uses_sonnet_by_default(wired):
    run, models = make_model_recording_runner('{"overview":"o"}')
    out = await runner.research_company(None, "토스", runner=run, notify=wired.notify)
    assert out == "done"
    assert models == ["sonnet"]


async def test_company_records_model_actually_used(wired):
    run, _ = make_model_recording_runner('{"overview":"o"}')
    await runner.research_company(None, "토스", runner=run, notify=wired.notify)
    assert wired.saved[-1][2]["model"] == "sonnet"


async def test_company_escalates_to_opus_on_parse_failure(wired):
    run, models = make_model_recording_runner("헛소리", '{"overview":"o"}')
    out = await runner.research_company(None, "토스", runner=run, notify=wired.notify)
    assert out == "done"
    assert models == ["sonnet", "opus"]
    assert wired.saved[-1][2]["model"] == "opus"   # 실제로 성공한 모델


async def test_company_failure_records_first_attempt_model(wired):
    run, _ = make_model_recording_runner("bad", "still bad")
    out = await runner.research_company(None, "토스", runner=run, notify=wired.notify)
    assert out == "failed"
    assert wired.saved[-1][2]["model"] == "sonnet"


async def test_company_settings_override_shifts_ladder(wired):
    run, models = make_model_recording_runner("헛소리", '{"overview":"o"}')
    await runner.research_company(
        None, "토스", settings=_Settings("opus"), runner=run, notify=wired.notify,
    )
    assert models == ["opus", "opus"]  # 상한에서의 승급 = 같은 모델 재시도


async def test_job_threads_settings_into_company_research(wired):
    wired.state["job_meta"][("wanted", "42")] = {
        "company": "토스", "title": "백엔드", "tech_stacks": "Java",
        "summary": "s", "url": "https://x",
    }
    run, models = make_model_recording_runner(
        '{"overview":"o"}', '{"tech_detail":"t","role_detail":"r"}',
    )
    out = await runner.research_job(
        None, "wanted", "42", settings=_Settings("haiku"), runner=run, notify=wired.notify,
    )
    assert out == "done"
    assert models == ["haiku", "haiku"]  # 선행 기업 리서치도 같은 설정을 쓴다
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && python -m pytest tests/test_research_runner.py -v`
Expected: FAIL — `models == []`(러너가 `model=`을 받지 못함) 및 `KeyError: 'model'` 또는 저장된 모델이 빈 문자열

- [ ] **Step 3: `research/config.py`에서 죽은 상수 제거**

`RESEARCH_MODEL = os.environ.get("RESEARCH_MODEL", "")` 줄을 삭제한다. 파일의 나머지(`RESEARCH_TIMEOUT`, 자동모드 3개 상수)는 그대로 둔다.

삭제 전에 다른 참조가 없는지 확인:

Run: `cd backend && grep -rn "RESEARCH_MODEL" app tests`
Expected: `app/research/runner.py`의 임포트 1줄과 사용 4곳만 — Step 4에서 함께 사라진다

- [ ] **Step 4: `runner.py` 구현**

임포트를 아래로 교체:

```python
import logging

from app.claude_client import run_claude
from app.llm_tier import escalate, resolve
from app.research import store
from app.research.config import RESEARCH_TIMEOUT
from app.research.discord import push
from app.research.parse import parse_research_json
from app.research.prompts import (
    RESEARCH_TOOLS,
    build_company_prompt,
    build_job_prompt,
)

log = logging.getLogger("research")


def _model_for(settings) -> str:
    """settings가 없으면(=CLI·구 호출자) 코드 기본 티어."""
    return resolve("research", settings.research_model if settings else "")
```

`_run_and_parse`를 아래로 교체:

```python
async def _run_and_parse(prompt, runner, model, on_step=None) -> tuple[dict, str]:
    """claude 호출 → JSON 파싱. 파싱 실패 시 한 단계 승급해 1회만 재시도.

    반환: (파싱결과, 실제로 성공한 모델). 같은 모델에게 같은 걸 다시 시키는 대신
    승급하므로, 비용이 실제로 어려웠던 실행에만 붙는다.
    """
    text = await runner(prompt, model=model, allowed_tools=RESEARCH_TOOLS,
                        timeout=RESEARCH_TIMEOUT, on_step=on_step)
    try:
        return parse_research_json(text), model
    except ValueError:
        up = escalate(model)
        retry = prompt + "\n\n[재시도] 반드시 JSON 객체 하나만 출력. 그 외 텍스트 금지."
        text = await runner(retry, model=up, allowed_tools=RESEARCH_TOOLS,
                            timeout=RESEARCH_TIMEOUT, on_step=on_step)
        return parse_research_json(text), up
```

`research_company`를 아래로 교체:

```python
async def research_company(
    db, company, url="", *, settings=None, force=False, runner=run_claude,
    notify=push, activity=None,
) -> str:
    existing = await store.get_company(db, company)
    if existing and existing.get("status") == "done" and not force:
        return "cached"

    await store.mark_company_running(db, company)
    prompt = build_company_prompt(company, url)
    model = _model_for(settings)

    def _step(label):
        if activity is not None:
            activity.add_research(company, "기업 리서치 중", label)

    _step("")  # 시작 시 stage 게시(라벨 없이)
    try:
        parsed, used = await _run_and_parse(prompt, runner, model, on_step=_step)
    except Exception as e:  # noqa: BLE001 — 어떤 실패든 failed로 표면화
        log.warning("company research failed: %s (model=%s): %s", company, model, e)
        # 승급 여부는 예외에 실리지 않으므로 1차 시도 모델을 남긴다.
        await store.save_company(db, company, status="failed", model=model)
        await notify(f"🔴 기업 리서치 실패: {company}")
        if activity is not None:
            activity.clear_research(company)
        return "failed"

    await store.save_company(
        db, company, status="done",
        overview=parsed.get("overview"), stability=parsed.get("stability"),
        data=parsed, sources=parsed.get("sources"), model=used,
    )
    await notify(f"🏢 기업 리서치 완료: {company}")
    if activity is not None:
        activity.clear_research(company)
    return "done"
```

`research_job`을 아래로 교체:

```python
async def research_job(
    db, source, job_id, *, settings=None, force=False, runner=run_claude,
    notify=push, activity=None,
) -> str:
    existing = await store.get_job(db, source, job_id)
    if existing and existing.get("status") == "done" and not force:
        return "cached"

    meta = await store.get_job_meta(db, source, job_id)
    if meta is None:
        raise LookupError(f"job not found: {source}:{job_id}")

    key = f"{source}:{job_id}"

    def _step(label):
        if activity is not None:
            activity.add_research(key, "공고 리서치 중", label)

    # ① 기업 리서치 선행(캐시되면 내부에서 skip). 같은 설정을 그대로 넘긴다.
    await research_company(
        db, meta["company"], meta.get("url", "") or "", settings=settings,
        runner=runner, notify=notify, activity=activity,
    )
    company_row = await store.get_company(db, meta["company"])
    overview = (company_row or {}).get("overview", "") or ""

    await store.mark_job_running(db, source, job_id, meta["company"])
    prompt = build_job_prompt(
        overview, meta.get("title", ""), meta.get("tech_stacks", ""),
        meta.get("summary", ""), meta.get("url", ""),
    )
    model = _model_for(settings)
    _step("")  # 시작 시 stage 게시(라벨 없이)
    try:
        parsed, used = await _run_and_parse(prompt, runner, model, on_step=_step)
    except Exception as e:  # noqa: BLE001
        log.warning("job research failed: %s:%s (model=%s): %s", source, job_id, model, e)
        await store.save_job(
            db, source, job_id, meta["company"], status="failed", model=model,
        )
        await notify(f"🔴 공고 리서치 실패: {meta['company']} {source}:{job_id}")
        if activity is not None:
            activity.clear_research(key)
        return "failed"

    await store.save_job(
        db, source, job_id, meta["company"], status="done",
        tech_detail=parsed.get("tech_detail"), role_detail=parsed.get("role_detail"),
        data=parsed, sources=parsed.get("sources"), model=used,
    )
    await notify(f"📋 공고 리서치 완료: {meta['company']} {source}:{job_id}")
    if activity is not None:
        activity.clear_research(key)
    return "done"
```

- [ ] **Step 5: 통과 확인**

Run: `cd backend && python -m pytest tests/test_research_runner.py tests/test_activity_wiring.py -v`
Expected: PASS

- [ ] **Step 6: 전체 스위트 확인**

Run: `cd backend && python -m pytest -q`
Expected: 193 passed

- [ ] **Step 7: 커밋**

```bash
git add backend/app/research/runner.py backend/app/research/config.py backend/tests/test_research_runner.py
git commit -m "feat(research): 파싱 실패 시 모델 승급 + 실제 사용 모델 기록"
```

---

### Task 6: 리서치 호출처에 설정 전달

**Files:**
- Modify: `backend/app/routers/research.py`
- Modify: `backend/app/research/scheduler.py:15-22`
- Modify: `backend/app/research/__main__.py:19-30`
- Test: `backend/tests/test_research_router.py`, `backend/tests/test_research_run_log.py`, `backend/tests/test_research_scheduler.py`, `backend/tests/test_research_cli.py`

**Interfaces:**
- Consumes: `app.settings_repo.get_settings(conn) -> Settings`, Task 5의 `research_company(..., settings=...)` / `research_job(..., settings=...)`
- Produces: 없음(배선만)

- [ ] **Step 1: 기존 테스트의 fake db·fake 러너 갱신**

네 파일 모두 `settings`를 못 받거나 `get_settings`를 못 견디는 대역을 쓰고 있다. 먼저 고친다.

`backend/tests/test_research_router.py` — `make_app`의 conn 오버라이드를 `object()`에서 fetchrow를 가진 대역으로 바꾼다. `get_settings`는 row가 None이면 `Settings(**SETTINGS_DEFAULTS)`를 돌려주므로 이걸로 충분하다. 파일 상단 `_FakePoolConn` 아래에 추가:

```python
class _FakeReqConn:
    """요청 스코프 conn 대역. get_settings가 기본 설정을 얻도록 fetchrow가 None을 반환."""
    async def fetchrow(self, sql, *args):
        return None

    async def execute(self, sql, *args):
        pass
```

`make_app` 안의 오버라이드를 교체:

```python
    app.dependency_overrides[research.get_conn] = lambda: _FakeReqConn()
```

같은 파일의 fake 러너 2개(`fake_company`, `fake_job`)에 `settings=None`을 추가한다:

```python
    async def fake_company(db, company, url="", *, settings=None, force=False, activity=None):
    async def fake_job(db, source, job_id, *, settings=None, force=False, activity=None):
```

`backend/tests/test_research_run_log.py` — 이 파일은 HTTP를 거치지 않고 `_logged_*` 헬퍼를 직접 부른다. 고칠 곳이 네 군데다.

fake 러너 2개의 시그니처:

```python
    async def fake_research_company(db, company, url="", *, settings=None, force=False, activity=None):
    async def fake_research_job(db, source, job_id, *, settings=None, force=False, activity=None):
```

헬퍼 호출 2곳 — `settings`가 필수 키워드가 되므로 `settings=None`을 넘긴다:

```python
    await research_router._logged_company(pool, "미스릴", settings=None, force=False, activity=None)

    await research_router._logged_job(
        pool, "wanted", "123", label="백엔드 개발자", settings=None, force=False, activity=None,
    )
```

`backend/tests/test_research_scheduler.py` — `tick`이 `get_settings(db)`를 부르므로 db 대역이 필요하다. 파일 상단에 추가:

```python
class _FakeDb:
    async def fetchrow(self, sql, *args):
        return None
```

`await scheduler.tick(lambda: object())` 형태의 호출을 모두 `await scheduler.tick(lambda: _FakeDb())`로 바꾼다(`lambda: object(), lambda: sentinel` 형태도 첫 인자만 교체). 러너 fake는 이미 `**kw`라 그대로 둔다.

`backend/tests/test_research_cli.py` — `dispatch`가 `get_settings(db)`를 부른다. 파일 상단에 같은 `_FakeDb`를 추가하고 `await dispatch(object(), args)`를 `await dispatch(_FakeDb(), args)`로 바꾼다. fake 러너 2개에 `settings=None`을 추가:

```python
    async def rc(db, company, url="", *, settings=None, force=False):
    async def rj(db, source, job_id, *, settings=None, force=False):
```

- [ ] **Step 2: 실패하는 테스트 작성**

`backend/tests/test_research_router.py` 끝에 추가:

```python
def test_company_trigger_passes_settings_to_runner(monkeypatch):
    """설정 조회는 202 응답 전에 끝나야 한다 — 러너가 몇 분씩 conn을 붙들면 풀이 마른다."""
    seen = {}
    app = make_app(monkeypatch)

    async def fake_company(db, company, url="", *, settings=None, force=False, activity=None):
        seen["settings"] = settings

    async def fake_mark(conn, company):
        pass

    monkeypatch.setattr(research.runner, "research_company", fake_company)
    monkeypatch.setattr(research.store, "mark_company_running", fake_mark)

    r = TestClient(app).post("/api/research/company", json={"company": "토스"})
    assert r.status_code == 202
    assert seen["settings"] is not None
    assert seen["settings"].research_model == ""   # 기본 설정이 전달됨
```

`backend/tests/test_research_scheduler.py` 끝에 추가:

```python
async def test_tick_threads_settings(monkeypatch):
    seen = []

    async def pending_companies(db, limit):
        return ["토스"]

    async def pending_jobs(db, limit):
        return [("wanted", "42")]

    async def research_company(db, company, **kw):
        seen.append(kw.get("settings"))

    async def research_job(db, source, job_id, **kw):
        seen.append(kw.get("settings"))

    monkeypatch.setattr(scheduler.store, "pending_companies", pending_companies)
    monkeypatch.setattr(scheduler.store, "pending_jobs", pending_jobs)
    monkeypatch.setattr(scheduler.runner, "research_company", research_company)
    monkeypatch.setattr(scheduler.runner, "research_job", research_job)

    await scheduler.tick(lambda: _FakeDb())
    assert len(seen) == 2
    assert all(s is not None and s.research_model == "" for s in seen)
```

- [ ] **Step 3: 실패 확인**

Run: `cd backend && python -m pytest tests/test_research_router.py tests/test_research_scheduler.py -v`
Expected: FAIL — `seen["settings"] is None`(라우터가 아직 안 넘김), `assert len(seen) == 2`는 통과하나 `s is not None`이 깨짐

- [ ] **Step 4: `routers/research.py` 구현**

임포트에 추가:

```python
from app.settings_repo import get_settings
```

두 헬퍼에 `settings`를 받아 러너로 넘긴다:

```python
async def _logged_company(pool, company: str, *, settings, force: bool, activity) -> None:
    await logged_pool_run(
        pool, pipeline="research", trigger="manual", ref=company, label=company,
        run=lambda: runner.research_company(pool, company, "", settings=settings,
                                            force=force, activity=activity),
    )


async def _logged_job(pool, source: str, job_id: str, *, label: str, settings,
                      force: bool, activity) -> None:
    await logged_pool_run(
        pool, pipeline="research", trigger="manual",
        ref=f"{source}:{job_id}", label=label,
        run=lambda: runner.research_job(pool, source, job_id, settings=settings,
                                        force=force, activity=activity),
    )
```

`trigger_company` 엔드포인트에서 `mark_company_running` 다음, `bg.add_task` 전에 설정을 읽는다:

```python
    # 응답 전에 읽어 평범한 객체로 넘긴다 — BackgroundTask 안에서 조회하면
    # 몇 분짜리 리서치 내내 커넥션을 붙들어 풀(max_size=10)이 마른다.
    settings = await get_settings(conn)
    bg.add_task(
        _logged_company, request.app.state.db, req.company,
        settings=settings, force=req.force, activity=request.app.state.activity,
    )
```

`trigger_job` 엔드포인트도 같은 위치에 `settings = await get_settings(conn)`을 넣고, `bg.add_task(...)` 호출에 `settings=settings,`를 추가한다.

- [ ] **Step 5: `research/scheduler.py` 구현**

임포트에 추가:

```python
from app.settings_repo import get_settings
```

`tick`을 아래로 교체:

```python
async def tick(get_pool, get_activity=lambda: None) -> None:
    """미리서치 대상 회사/공고를 limit만큼 처리(자동모드 잡 본체)."""
    db = get_pool()
    activity = get_activity()
    settings = await get_settings(db)
    for company in await store.pending_companies(db, RESEARCH_AUTO_LIMIT):
        await runner.research_company(db, company, settings=settings, activity=activity)
    for source, job_id in await store.pending_jobs(db, RESEARCH_AUTO_LIMIT):
        await runner.research_job(db, source, job_id, settings=settings, activity=activity)
```

- [ ] **Step 6: `research/__main__.py` 구현**

임포트에 추가:

```python
from app.settings_repo import get_settings
```

`dispatch`를 아래로 교체:

```python
async def dispatch(db, args) -> None:
    settings = await get_settings(db)
    if args.company:
        print(await runner.research_company(db, args.company, settings=settings, force=args.force))
    elif args.job:
        source, job_id = args.job.split(":", 1)
        print(await runner.research_job(db, source, job_id, settings=settings, force=args.force))
    elif args.pending_companies:
        for company in await store.pending_companies(db, args.limit):
            print(company, await runner.research_company(db, company, settings=settings, force=args.force))
    elif args.pending_jobs:
        for source, job_id in await store.pending_jobs(db, args.limit):
            print(source, job_id, await runner.research_job(db, source, job_id, settings=settings, force=args.force))
```

- [ ] **Step 7: 통과 확인**

Run: `cd backend && python -m pytest tests/test_research_router.py tests/test_research_run_log.py tests/test_research_scheduler.py tests/test_research_cli.py -v`
Expected: PASS

- [ ] **Step 8: 전체 스위트 확인**

Run: `cd backend && python -m pytest -q`
Expected: 195 passed

- [ ] **Step 9: 커밋**

```bash
git add backend/app/routers/research.py backend/app/research/scheduler.py backend/app/research/__main__.py backend/tests/test_research_router.py backend/tests/test_research_run_log.py backend/tests/test_research_scheduler.py backend/tests/test_research_cli.py
git commit -m "feat(research): 라우터·스케줄러·CLI에서 설정을 러너로 전달"
```

---

### Task 7: 리서치 모델 API 노출 + 프론트 칩

**Files:**
- Modify: `backend/app/jobs_repo.py:108-160`
- Modify: `frontend/src/ResearchPanel.tsx`
- Test: `backend/tests/test_jobs_repo.py`, `frontend/src/pages/JobDetailView.test.tsx`

**Interfaces:**
- Consumes: Task 5가 채우는 `job_research.model`
- Produces: `GET /api/jobs/{source}/{job_id}` 응답의 `jobResearch.model: string | null`

- [ ] **Step 1: 실패하는 백엔드 테스트 작성**

`backend/tests/test_jobs_repo.py` 끝에 추가:

```python
def test_detail_sql_selects_research_model():
    from app.jobs_repo import _DETAIL_SQL
    assert "jr.model AS jr_model" in _DETAIL_SQL


def test_split_detail_exposes_research_model():
    from app.jobs_repo import _split_detail
    row = {
        "source": "wanted", "job_id": "42", "company": "토스", "title": "백엔드",
        "url": "https://x", "locations": "서울", "min_career": 0, "max_career": 3,
        "tech_stacks": None, "summary": "s", "status": "done", "attempts": 0,
        "collected_at": None, "updated_at": None, "closed_at": None,
        "cr_overview": None, "cr_stability": None, "cr_sources": None,
        "cr_status": None, "cr_researched_at": None,
        "jr_tech_detail": "t", "jr_role_detail": "r", "jr_sources": None,
        "jr_status": "done", "jr_researched_at": None, "jr_model": "opus",
    }
    out = _split_detail(row)
    assert out["jobResearch"]["model"] == "opus"
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && python -m pytest tests/test_jobs_repo.py -v -k model`
Expected: FAIL — `"jr.model AS jr_model" not in _DETAIL_SQL`, `KeyError: 'model'`

- [ ] **Step 3: `jobs_repo.py` 구현**

`_DETAIL_SQL`의 `jr.researched_at AS jr_researched_at ` 줄을 아래로 교체:

```python
    "  jr.researched_at AS jr_researched_at, jr.model AS jr_model "
```

`_split_detail`의 `job_research` 블록을 아래로 교체:

```python
    job_research = None if d["jr_status"] is None else {
        "tech_detail": d["jr_tech_detail"],
        "role_detail": d["jr_role_detail"],
        "sources": _maybe_json(d["jr_sources"]),
        "status": d["jr_status"],
        "researched_at": d["jr_researched_at"],
        "model": d["jr_model"],
    }
```

- [ ] **Step 4: 백엔드 통과 확인**

Run: `cd backend && python -m pytest -q`
Expected: 197 passed (백엔드 최종)

- [ ] **Step 5: 실패하는 프론트 테스트 작성**

이 파일은 `vi.mock("../api")` + `(getJob as Mock).mockResolvedValue(...)`로 상세를 주입한다. `beforeEach`가 이미 기본 응답을 깔아두므로, 각 테스트에서 `mockResolvedValue`를 다시 호출해 덮어쓴다. 파일 끝에 추가:

```tsx
const BASE_JOB = {
  source: "saramin", job_id: "1", company: "Acme", title: "백엔드 개발자",
  url: "http://x", locations: "서울", min_career: 0, max_career: 3,
  tech_stacks: ["python"], summary: "요약", status: "open", attempts: 0,
  collected_at: "2026-07-20", updated_at: null, closed_at: null,
};

test("리서치 완료 시 사용 모델 칩을 보여준다", async () => {
  (getJob as Mock).mockResolvedValue({
    job: BASE_JOB,
    companyResearch: { status: "done", overview: "안정적", stability: null, sources: null, researched_at: null },
    jobResearch: { status: "done", tech_detail: "t", role_detail: "r", sources: null, researched_at: null, model: "opus" },
  });
  render(<JobDetailView source="saramin" jobId="1" />);
  // 이 프로젝트에는 @testing-library/jest-dom이 없다 — toBeInTheDocument/
  // toHaveTextContent 대신 .textContent를 비교한다(기존 테스트와 동일).
  expect((await screen.findByTestId("research-model")).textContent).toBe("opus");
});

test("모델이 비어 있으면 칩을 그리지 않는다", async () => {
  (getJob as Mock).mockResolvedValue({
    job: BASE_JOB,
    companyResearch: { status: "done", overview: "안정적", stability: null, sources: null, researched_at: null },
    jobResearch: { status: "done", tech_detail: "t", role_detail: "r", sources: null, researched_at: null, model: "" },
  });
  render(<JobDetailView source="saramin" jobId="1" />);
  await waitFor(() => expect(screen.getByTestId("job-title").textContent).toBe("백엔드 개발자"));
  expect(screen.queryByTestId("research-model")).toBeNull();
});
```

`waitFor`는 이 파일 상단 import에 이미 있다. `Mock` 타입도 마찬가지다.

- [ ] **Step 6: 실패 확인**

Run: `cd frontend && npx vitest run src/pages/JobDetailView.test.tsx`
Expected: FAIL — `Unable to find an element with the text: opus`

- [ ] **Step 7: `ResearchPanel.tsx` 구현**

`Research` 타입에 필드를 추가한다:

```tsx
type Research = {
  status?: string;
  overview?: string;
  stability?: string;
  tech_detail?: string;
  role_detail?: string;
  sources?: string[];
  model?: string;
} | null;
```

섹션 제목 `<AnimatePresence mode="wait">` 블록 안, `jrStatus === "failed"` 분기 **뒤**에 완료 상태의 모델 칩을 더한다:

```tsx
          {!busy && jrStatus === "done" && jr?.model && (
            <motion.span
              key="model"
              data-testid="research-model"
              className="pill"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              {jr.model}
            </motion.span>
          )}
```

`jr?.model &&` 가드가 빈 문자열도 걸러내므로, 이관 전에 저장된 행(모델이 빈 문자열)에는 칩이 안 뜬다.

- [ ] **Step 8: 프론트 통과 확인**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: 52(기존) + 2 = 54 passed, 타입 에러 없음

- [ ] **Step 9: 커밋**

```bash
git add backend/app/jobs_repo.py backend/tests/test_jobs_repo.py frontend/src/ResearchPanel.tsx frontend/src/pages/JobDetailView.test.tsx
git commit -m "feat(research): 공고 상세에 리서치 사용 모델 노출"
```

---

### Task 8: 설정 화면 + 실행 로그 승급 표시

**Files:**
- Modify: `frontend/src/settingsApi.ts:1-18`
- Modify: `frontend/src/pages/Ops.tsx:210-213`
- Modify: `frontend/src/runsFormat.ts:20-24`
- Test: `frontend/src/pages/Ops.test.tsx`, `frontend/src/pages/Filters.test.tsx`, `frontend/src/runsFormat.test.ts`

**Interfaces:**
- Consumes: Task 3의 `summary_model`/`research_model`, Task 4의 `worker_tick` 반환 `escalated`
- Produces: 없음(최종 표면)

- [ ] **Step 1: 테스트 픽스처에 새 필드 추가**

`Settings` 타입에 필수 필드가 늘어나므로 픽스처를 안 고치면 `tsc`가 깨진다.

`frontend/src/pages/Ops.test.tsx`의 `SETTINGS` 상수와 `frontend/src/pages/Filters.test.tsx`의 동일 상수, 두 곳 모두 `notify_enabled: false,` 다음 줄에 추가:

```tsx
  summary_model: "", research_model: "",
```

- [ ] **Step 2: 실패하는 테스트 작성**

`frontend/src/runsFormat.test.ts` 끝에 추가. 이 파일 상단의 `item(over: Partial<RunLogItem>)` 헬퍼를 쓴다:

```ts
test("worker 요약에 승급 건수를 덧붙인다", () => {
  expect(runSummary(item({
    pipeline: "worker", result: { claimed: 5, done: 5, failed: 0, escalated: 2 },
  }))).toBe("요약 5건·승급 2");
});

test("승급이 없으면 기존 문구 그대로", () => {
  expect(runSummary(item({
    pipeline: "worker", result: { claimed: 5, done: 5, failed: 0, escalated: 0 },
  }))).toBe("요약 5건");
});

test("escalated 키가 없는 옛 기록도 깨지지 않는다", () => {
  expect(runSummary(item({
    pipeline: "worker", result: { claimed: 5, done: 5, failed: 1 },
  }))).toBe("요약 5건·실패 1");
});
```

`frontend/src/pages/Ops.test.tsx` 끝에 추가. 이 파일의 `beforeEach`가 이미 `putBody = null`과 `global.fetch = mockFetch()`를 세팅하므로 테스트 안에서 다시 하지 않는다. 저장 버튼은 기존 테스트와 동일하게 `{ name: "저장" }`으로 찾는다.

```tsx
test("요약·리서치 모델을 선택해 저장한다", async () => {
  render(<Ops />);
  const summary = await screen.findByLabelText("요약 모델");
  fireEvent.change(summary, { target: { value: "sonnet" } });
  fireEvent.change(screen.getByLabelText("리서치 모델"), { target: { value: "opus" } });
  fireEvent.click(screen.getByRole("button", { name: "저장" }));
  await waitFor(() => expect(putBody).not.toBeNull());
  expect(putBody!.summary_model).toBe("sonnet");
  expect(putBody!.research_model).toBe("opus");
});
```

- [ ] **Step 3: 실패 확인**

Run: `cd frontend && npx vitest run src/runsFormat.test.ts src/pages/Ops.test.tsx`
Expected: FAIL — `expected "요약 5건" to be "요약 5건·승급 2"`, `Unable to find a label with the text of: 요약 모델`

- [ ] **Step 4: `settingsApi.ts` 구현**

`Settings` 인터페이스의 `notify_enabled: boolean;` 다음 줄에 추가:

```ts
  summary_model: string;
  research_model: string;
```

- [ ] **Step 5: `runsFormat.ts` 구현**

worker 분기를 아래로 교체:

```ts
  if (it.pipeline === "worker") {
    if (it.status === "skipped") return "건너뜀·LLM 대기";
    const failed = Number(r.failed ?? 0);
    const esc = Number(r.escalated ?? 0);
    return `요약 ${r.done ?? 0}건${failed ? `·실패 ${failed}` : ""}${esc ? `·승급 ${esc}` : ""}`;
  }
```

- [ ] **Step 6: `Ops.tsx` 구현**

기존 `모델` 입력 행(`<label className="form-row"><span className="rl">모델</span>…`)을 아래 세 행으로 교체한다. 첫 행은 라벨만 바뀌고 바인딩(`form.model`)은 그대로다 — 세 필드가 나란히 놓이는 순간 어느 것이 LM Studio용인지 구분되지 않으면 오설정이 난다.

```tsx
            <label className="form-row">
              <span className="rl">로컬 모델</span>
              <input className="control" aria-label="로컬 모델" type="text" value={form.model} onChange={(e) => set("model", e.target.value)} />
            </label>
            <label className="form-row">
              <span className="rl">요약 모델</span>
              <select className="control" aria-label="요약 모델" value={form.summary_model}
                onChange={(e) => set("summary_model", e.target.value)}>
                <option value="">자동 (haiku)</option>
                <option value="haiku">haiku</option>
                <option value="sonnet">sonnet</option>
                <option value="opus">opus</option>
              </select>
            </label>
            <label className="form-row">
              <span className="rl">리서치 모델</span>
              <select className="control" aria-label="리서치 모델" value={form.research_model}
                onChange={(e) => set("research_model", e.target.value)}>
                <option value="">자동 (sonnet)</option>
                <option value="haiku">haiku</option>
                <option value="sonnet">sonnet</option>
                <option value="opus">opus</option>
              </select>
            </label>
```

- [ ] **Step 7: 통과 확인**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: 54 + 4 = 58 passed, 타입 에러 없음

- [ ] **Step 8: 표시 테스트가 의미 있는지 검증**

`runsFormat.ts`의 `esc ? ... : ""`를 `""`로 잠시 바꾸고 실행:

Run: `cd frontend && npx vitest run src/runsFormat.test.ts`
Expected: **FAIL** (`요약 5건·승급 2` 기대가 깨짐)

원래 코드로 복구하고 재실행: Expected: PASS

- [ ] **Step 9: 커밋**

```bash
git add frontend/src/settingsApi.ts frontend/src/pages/Ops.tsx frontend/src/runsFormat.ts frontend/src/pages/Ops.test.tsx frontend/src/pages/Filters.test.tsx frontend/src/runsFormat.test.ts
git commit -m "feat(ops): 모델 티어 설정 UI + 실행 로그 승급 표시"
```

---

## 배포 후 컷오버 (구현 완료·머지 후, 운영자가 수행)

계획의 일부가 아니라 배포 뒤 절차다. 스펙의 「컷오버」 절을 따른다.

1. 배포 — `summary_model`/`research_model` 모두 `""`, `summary_backend`는 기존 `local`. **요약 동작 불변**, 리서치만 sonnet으로 명시 고정된다.
2. 리서치 1건 수동 실행 → 공고 상세에 `sonnet` 칩이 뜨는지 확인.
3. 설정에서 `summary_backend`를 `claude`로 전환. `pending`이 적은 시각(수집 직전)이 안전하다.
4. 워커 한두 틱 관찰 — 실행 로그에 `요약 N건`이 뜨고 요약 품질이 기존과 비슷한지 확인. 실행 로그의 소요 시간이 5분에 근접하면 `batch_size`를 낮춘다.

되돌리기는 `summary_backend`를 `local`로 되돌리는 것 하나다(맥이 켜져 있어야 한다).
