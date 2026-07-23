# LLM 모델 티어 + 요약 claude 이관 설계

**작성일:** 2026-07-24
**목표:** `claude -p` 호출에 작업 난이도별 모델 티어(haiku/sonnet/opus)를 도입하고, 마지막으로 로컬 LLM에 남아 있는 career-agent 기능인 공고 요약을 claude로 옮긴다.

## 배경

career-agent의 LLM 호출은 두 갈래다.

| 기능 | 현재 실행 | 위치 |
|---|---|---|
| 공고 요약 | LM Studio (`summary_backend="local"`) | `collect/summarize.py` |
| 기업·공고 리서치 | `claude -p` (WebSearch/WebFetch) | `research/runner.py` |

`summary_backend`는 `local`/`claude` 스위치가 이미 있고 claude 분기도 구현돼 있다. 즉 요약 이관은 신규 개발이 아니라 **스위치를 넘길 수 있게 만드는 일**이다.

`claude_client.run_claude`에는 **`--model` 인자가 없다.** 리서치도, 요약의 claude 분기도 CLI 기본 모델 하나로 돈다. CLI는 `--model haiku|sonnet|opus` 별칭을 지원하므로 티어링의 배관은 이 함수 한 곳에 뚫으면 된다.

### 범위 밖 — 별도 스펙

n8n에 남은 LLM 기능은 이 스펙에 넣지 않는다.

- **07-mail-checker (메일 확인)** — IMAP 수신·분류·저장·알림 12노드짜리 독립 서브시스템. 이 스펙의 티어 러너를 소비하므로 **이 스펙 다음**에 별도 스펙으로 진행한다.
- **04-search 질의 분해** — 별건.
- **임베딩 (04/05, KURE-v1)** — claude에 임베딩 API가 없어 대체 불가. 로컬 유지.

## 결정 사항 (확정)

1. **티어는 코드 상수 + 설정 오버라이드.** 작업별 기본 티어를 코드에 두고, 설정에 비워둔 문자열 하나씩을 둔다. 비어 있으면 코드 기본값.
2. **기본 배정은 요약=haiku, 리서치=sonnet.**
3. **opus는 승급으로만 등장한다.** 재시도할 때만 한 단계 위 티어로 올린다. 비용이 실제로 어려웠던 실행에만 붙는다.
4. **요약 승급은 `attempts` 기반.** 새 상태를 만들지 않는다.
5. **모델 별칭은 `haiku|sonnet|opus` 세 개로 제한한다.**
6. **`settings.model`은 개명하지 않는다.**

## 아키텍처

### 티어 배관 — `app/llm_tier.py` (신설)

`claude_client.py`는 프로세스 래퍼로 얇게 유지하고 티어 정책은 별도 모듈에 둔다. 소비자가 `collect/summarize.py`와 `research/runner.py` 둘이라, 어느 한쪽에 두면 다른 쪽이 그 패키지를 끌어온다.

```python
LADDER = ("haiku", "sonnet", "opus")
TASK_MODEL = {"summary": "haiku", "research": "sonnet"}

def escalate(model: str) -> str:
    """한 단계 위 티어. 사다리에 없거나 상한(opus)이면 그대로 반환."""

def resolve(task: str, override: str = "", *, escalated: bool = False) -> str:
    """override(설정) → 없으면 TASK_MODEL[task]. escalated면 한 단계 승급.
    알 수 없는 task는 KeyError — 오타를 조용히 넘기지 않는다."""
```

`escalate`가 상한에서 예외 대신 그대로 반환하는 이유: 설정 오버라이드로 `research_model="opus"`를 넣은 사용자의 재시도가 크래시하면 안 된다. 상한에서의 승급은 "같은 모델로 재시도" — 현재 동작과 동일하다.

### `run_claude` 확장

```python
async def run_claude(prompt, *, model="", allowed_tools="", timeout=120,
                     claude_bin="claude", on_step=None) -> str:
    args = [claude_bin, "-p", prompt, "--output-format", "stream-json", "--verbose"]
    if model:
        args += ["--model", model]
    ...
```

`model=""`이면 **명령줄이 현재와 바이트 단위로 동일하다.** 기존 호출자가 하나도 안 깨진다.

### 설정 — 마이그레이션 `0007_task_models`

```sql
ALTER TABLE app_settings
  ADD COLUMN summary_model  text NOT NULL DEFAULT '',
  ADD COLUMN research_model text NOT NULL DEFAULT '';
```

down은 두 컬럼 DROP, `down_revision = "0006_notify_enabled"`.

`Settings` 모델·`SETTINGS_DEFAULTS`·`_COLUMNS` 3중 동기화(`0006`과 동일한 절차). 두 필드 모두 `str = ""` 기본값.

검증 validator:

```python
@field_validator("summary_model", "research_model")
@classmethod
def _tier(cls, v: str) -> str:
    v = (v or "").strip()
    if v and v not in LADDER:
        raise ValueError(f"model must be one of {LADDER} or empty")
    return v
```

자유 문자열을 허용하면 오타가 배포 후 첫 실행에서야 `claude` 프로세스 실패로 드러난다. 저장 시점에 막는다. 대가로 `claude-opus-4-8` 같은 풀네임 핀은 불가능하다 — 필요해지면 그때 넓힌다.

### 요약 이관

`summarize()`에 `model: str = ""`를 더하고 **claude 분기에서만** 쓴다:

```python
async def summarize(prompt, settings, *, http, model="", runner=run_claude, on_step=None):
    if settings.summary_backend == "claude":
        full = f"{SUMMARY_SYSTEM_PROMPT}\n\n{prompt}"
        return await runner(full, model=model, timeout=SUMMARY_TIMEOUT, on_step=on_step) or None
    # local 분기는 불변 — settings.model(LM Studio 모델명)을 그대로 사용
```

`worker_tick`에서 잡별로 해석한다. `claim_batch`의 `CLAIM_SQL`이 이미 `attempts`를 RETURNING하므로 새 조회가 없다:

```python
escalated = job["attempts"] > 0
model = resolve("summary", settings.summary_model, escalated=escalated)
content = await summarizer(prompt, settings, http=http, model=model)
```

승급 시점은 다음 틱(기본 5분 뒤)이다. 배치 파이프라인이라 즉시성이 필요 없고, 대신 한 틱 안에서 배치가 두 배로 늘어나는 일이 없다.

`attempts`는 **상세조회 실패로도 증가**한다(`worker.py:62`). 즉 네트워크 문제로 한 번 밀린 잡이 다음 틱에 sonnet으로 요약된다. 부정확하지만 드물고 무해하다 — 새 컬럼을 추가해 실패 원인을 구분하는 값어치가 없다.

### 헬스 게이트 수정 (이관에 필수)

`worker_tick`은 첫 줄에서 LM Studio `/v1/models`를 확인하고 down이면 틱 전체를 건너뛴다(`worker.py:47`). 요약이 claude로 옮겨간 뒤에도 이 게이트가 남아 있으면 **맥이 꺼져 있을 때 claude 요약까지 같이 멈춘다** — 이관의 목적을 정면으로 되돌린다.

게이트를 backend에 종속시킨다:

```python
if settings.summary_backend == "local" and not await health(http):
    return {"claimed": 0, "done": 0, "failed": 0, "escalated": 0, "skipped_tick": True}
```

claude 모드에는 게이트가 없다. `claude` 프로세스 실행 실패는 `summarize`의 예외 → 기존 `_RETRY_SQL`(attempts 캡)이 이미 처리한다.

`/status`의 `llm_health` 필드는 그대로 둔다 — LM Studio가 살아 있는지는 local 모드로 되돌릴 수 있는지를 알려주는 정보로 여전히 유효하다.

### 리서치 승급

`research_company`/`research_job`에 `settings` 키워드 인자를 더한다. `worker_tick(conn, settings, …)`, `notify_tick(conn, settings, …)`와 같은 모양이라 이 코드베이스의 기존 패턴이다.

**기본값은 `None`이고 "코드 기본 티어"를 뜻한다.** 호출처가 5곳(라우터 2, 자동 스케줄러 2, CLI `__main__` 4, `research_job`→`research_company` 내부 1)이고 기존 테스트가 `object()`를 db로 넘기므로, 러너가 스스로 `get_settings(db)`를 부르면 그 테스트들이 깨진다. `None` 허용이 그 결합을 피한다. 프로덕션 호출처는 모두 명시적으로 넘긴다.

```python
async def _run_and_parse(prompt, runner, model, on_step=None) -> tuple[dict, str]:
    """(파싱결과, 실제 사용 모델). 파싱 실패 시 한 단계 승급해 1회 재시도."""
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

호출부:

```python
model = resolve("research", settings.research_model if settings else "")
parsed, used = await _run_and_parse(prompt, runner, model, on_step=_step)
```

`research_job`은 자신이 받은 `settings`를 내부 `research_company` 호출에 그대로 넘긴다.

### 실제 사용 모델 기록

`store.save_company`/`save_job`의 `model=` 인자에는 지금 `RESEARCH_MODEL` env가 들어간다. 이 env의 기본값이 빈 문자열이고 프로덕션 backend 컨테이너에 설정돼 있지 않아 **`research_companies.model`/`research_jobs.model` 컬럼이 항상 비어 있다.**

이 자리를 `_run_and_parse`가 반환한 실제 사용 모델로 교체한다. 관측이 마이그레이션 없이 생기고 죽은 env가 하나 정리된다.

실패 경로(`status="failed"`)에는 **1차 시도 모델**을 기록한다. `_run_and_parse`가 예외를 던지면 호출부는 승급이 일어났는지 알 수 없고, 그걸 알려면 예외에 상태를 실어야 한다 — 실패 행의 모델 정확도를 위해 치를 값이 아니다. 승급 후에도 실패했다면 그 사실은 로그(`log.warning`)에 남는다.

`app/research/config.py`의 `RESEARCH_MODEL` 상수를 삭제한다.

### 라우터에서의 설정 조회

`routers/research.py`의 두 엔드포인트는 이미 `conn=Depends(get_conn)`을 갖고 있다. **엔드포인트 안에서** `get_settings(conn)`으로 읽어 `Settings` 객체를 BackgroundTask에 넘긴다.

BackgroundTask 안에서 조회하지 않는 이유: 리서치는 몇 분 걸리고 풀은 `max_size=10`이다. 이전에 run_log 래퍼가 커넥션을 리서치 전체에 걸쳐 붙들어 풀을 고갈시킨 적이 있다. 응답 전에 값을 읽어 평범한 객체로 넘기면 커넥션을 붙들지 않는다.

`research/scheduler.py`의 `tick`과 `research/__main__.py`도 각각 `await get_settings(db)` 한 줄을 더해 넘긴다.

## 화면 · 관측

승급이 실제로 도는지 볼 수 있는 표면을 함께 만든다. 알림 이관 때 프론트 포매터가 `notifier` 파이프라인을 몰라 **컷오버 검증에 쓰는 화면 자체가 잘못된 라벨을 보여준** 일이 있었다.

**1. 설정 페이지 (`Ops.tsx`)** — 기존 `모델` 입력 아래에 셀렉트 2개. 같이 그 입력의 라벨을 `모델` → `로컬 모델`로 바꾼다(컬럼명은 `model` 그대로 — 아래 YAGNI 참조). 세 필드가 나란히 놓이는 순간 어느 것이 LM Studio용인지 화면에서 구분되지 않으면 오설정이 난다.

- 라벨 `요약 모델`, `리서치 모델`
- 옵션: `자동 (haiku)` / `자동 (sonnet)`은 값 `""`, 그 외 `haiku`·`sonnet`·`opus`
- `settingsApi.ts`의 `Settings` 타입에 `summary_model: string`, `research_model: string` 추가(필수 필드)

**2. 실행 로그** — `worker_tick` 반환에 `"escalated": n`을 더하고 `runsFormat.ts`의 worker 분기에 노출한다.

```ts
// 현재: `요약 ${done}건${failed ? `·실패 ${failed}` : ""}`
// 변경: `요약 ${done}건${failed ? `·실패 ${failed}` : ""}${esc ? `·승급 ${esc}` : ""}`
```

`escalated`는 이번 틱에서 승급 티어로 요약을 **시도한** 잡 수다(성공 여부 무관). 승급이 성공했는지는 같은 줄의 `done`/`실패`와 함께 읽는다.

**3. 리서치 상세** — 사용 모델 칩. `research_companies.model`/`research_jobs.model`이 채워지므로 API가 이미 내려주는 값을 표시만 한다.

## 컷오버

알림 이관과 달리 이중 실행 위험이 없다. n8n `02-워커`는 2026-07-22 18:35을 마지막으로 이미 멈춰 있고, career-agent 워커가 단독으로 돈다. 스위치를 넘겨도 경합할 상대가 없다.

1. 배포 — `summary_model`/`research_model` 모두 `""`, `summary_backend`는 기존 `local`. 요약 동작 불변, 리서치만 sonnet으로 명시 고정된다.
2. 리서치 1건 수동 실행 → 리서치 상세에 `sonnet` 칩이 뜨는지 확인.
3. 설정에서 `summary_backend`를 `claude`로 전환.
4. 워커 한두 틱 관찰 — 실행 로그에 `요약 N건`이 뜨고 공고 상세의 요약 품질이 기존과 비슷한지 확인.

### 운영자가 알아야 할 것

- **3단계 전환 즉시 요약이 claude 구독 사용량을 쓴다.** 배치 크기가 20이고 워커 주기가 5분이므로, 밀린 `pending`이 많으면 한 번에 최대 20건이 연속 호출된다. 처음 전환할 때는 `pending`이 적은 시각(수집 직전)이 안전하다.
- **되돌리기는 설정 한 번이다.** `summary_backend`를 `local`로 되돌리면 즉시 LM Studio로 복귀한다(단 맥이 켜져 있어야 하고, local 모드에서는 헬스 게이트가 다시 작동한다).
- **`claude -p`는 잡당 Node 프로세스를 하나 띄운다.** A1은 2 OCPU다. 배치 20건은 직렬 처리라 동시 프로세스는 항상 1개지만, 건당 프로세스 기동 오버헤드가 붙어 틱 소요가 로컬 대비 늘 수 있다. 실행 로그의 소요 시간이 5분(워커 주기)에 근접하면 `batch_size`를 낮춘다.
- **승급은 조용하다.** 승급된 잡이 성공하면 로그에 `·승급 N`만 남고 원인은 남지 않는다. 특정 공고가 반복 승급되는지는 `jobs.attempts`로 확인한다.

## 테스트

**백엔드**

- `llm_tier.resolve`: 오버라이드 없음 → 코드 기본값 / 오버라이드 있음 → 그 값 / `escalated=True` → 한 단계 위 / 알 수 없는 task → `KeyError`.
- `llm_tier.escalate`: haiku→sonnet, sonnet→opus, **opus→opus**(상한), 사다리 밖 문자열 → 그대로.
- `run_claude`: `model=""`이면 argv에 `--model` 없음 / `model="haiku"`면 `["--model", "haiku"]`가 붙음. (subprocess를 monkeypatch해 argv 검사)
- `Settings` validator: `""` 허용 / `"haiku"` 허용 / `"gpt-4"` 거부 / 공백만 있는 값은 `""`로 정규화.
- 마이그레이션 `0007`: 기본값 `''`이 DDL·`SETTINGS_DEFAULTS`·모델 3곳 모두 일치.
- `summarize`: `summary_backend="claude"`면 `model`이 runner에 전달됨 / `"local"`이면 runner를 호출하지 않고 `settings.model`로 LM Studio 호출(불변).
- `worker_tick`:
  - `attempts=0` 잡 → `model="haiku"`로 summarizer 호출
  - `attempts=1` 잡 → `model="sonnet"`
  - `summary_model="sonnet"` 설정 시 `attempts=0` → `"sonnet"`, `attempts=1` → `"opus"`
  - `summary_backend="claude"`면 **health를 호출하지 않는다**(회귀 테스트: 이 게이트가 되살아나면 실패)
  - `summary_backend="local"`이고 health down이면 기존대로 `skipped_tick=True`
  - 반환 dict의 `escalated`가 승급 시도 건수와 일치
- `research/runner`:
  - 1차 호출 `model="sonnet"`, 파싱 성공 시 `save_*(model="sonnet")`
  - 1차 파싱 실패 → 재시도 호출 `model="opus"`, 성공 시 `save_*(model="opus")`
  - `settings=None`이면 코드 기본 티어(기존 테스트 호환)
  - 실패 경로에서 `save_*(model=<1차 시도 모델>)`
  - `research_job`이 `settings`를 `research_company`로 전달
- 라우터: 엔드포인트가 `get_settings`를 응답 전에 호출하고 결과를 BackgroundTask에 넘김.

**프론트**

- 설정 페이지에 두 셀렉트가 뜨고, 선택 시 PUT 본문에 `summary_model`/`research_model`이 실림.
- `runsFormat.runSummary`: worker + `escalated>0` → `·승급 N` 포함 / `escalated=0` 또는 없음 → 미포함(기존 문구 불변).
- 리서치 상세에 모델 칩 렌더.

## YAGNI (범위 밖)

- **`--fallback-model`** — 승급 사다리와 역할이 겹치고, "실제로 뭐가 돌았나"를 기록하려는 설계를 흐린다.
- **모델 풀네임 핀** — 별칭 3개로 충분.
- **`settings.model` 개명** — `model`(LM Studio 로컬 모델명)과 `summary_model`/`research_model`(claude 티어)이 나란히 있어 헷갈리지만, 개명은 마이그레이션 + 3중 동기화 + 프론트 변경을 이름 하나 때문에 치르는 일이다. 설정 페이지 라벨을 `모델` → `로컬 모델`로 바꿔 화면에서만 구분한다.
- **작업별 타임아웃 티어링** — `SUMMARY_TIMEOUT`/`RESEARCH_TIMEOUT` 그대로.
- **승급 사유 기록** — `jobs`에 실패 원인 컬럼을 더하지 않는다.
- **잡별 모델 수동 지정** — 설정은 작업 종류 단위까지만.
