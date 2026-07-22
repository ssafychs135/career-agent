# 수집 파이프라인 이관 + 설정 관리 페이지 설계

**작성일:** 2026-07-22
**상태:** 설계 확정, 구현 계획 대기

## 목표

n8n의 공고 수집(스크레이핑) 파이프라인을 career-agent 백엔드로 이관하고, 지금 n8n의 env·워크플로우 노드에 흩어져 있는 운영 변수를 DB 기반 **설정 관리 페이지** 한 곳에서 편집할 수 있게 한다. 더해 세 파이프라인(수집·요약·claude -p 리서치)이 **지금 무슨 작업을 어느 단계에서 실행 중인지** 실시간으로 보는 **상태 모니터 페이지**를 제공한다. 기존 워커 동작(소스·필터·요약·헬스게이트·재시도)을 그대로 보존한다.

## 배경 — 지금 n8n이 하는 일

수집은 2단계 파이프라인이다.

**① 01-collector (매일 09시)** — 목록 스크레이핑
- 소스: **원티드**(`chaos/navigation/v1/results` API) + **점핏**(`jumpit-api.saramin.co.kr/api/positions` API)
- 결과를 `jobs` 테이블에 `pending` 상태로 INSERT

**② 02-worker (5분마다)** — 상세 + AI 요약
- `pending` 배치(batchSize=20) 조회 → 상세 조회(원티드는 `JOB_PROXY` 경유) → **LM Studio 로컬 LLM 요약** → `done`
- LLM 헬스체크 게이트 + 재시도(maxAttempts=5)

### 키워드의 이중 역할 (보존 필수)

같은 키워드 리스트가 소스마다 다르게 쓰인다:
- **점핏**: 검색어(query). 키워드마다 `?keyword=` 검색 1회.
- **원티드**: 제목 필터(filter). 카테고리(`[518,507]`)로 목록을 받은 뒤, 제목에 키워드가 **단어 경계** 정규식으로 포함된 공고만 남김. (`titleHit`: `(^|[^A-Za-z0-9])kw([^A-Za-z0-9]|$)`, 대소문자 무시)

이 비대칭을 이관 코드에서 그대로 유지한다.

### 변수 현황 (세 군데 흩어짐)

| 층 | 변수 |
|---|---|
| env(.env) | `SEARCH_KEYWORDS`, `JOB_PROXY_URL`, `JOB_PROXY_SECRET`, `DISCORD_WEBHOOK_URL` |
| Config Set 노드(하드코딩) | collector: `maxPages`, `allowedWantedCategories`, `maxCareerYears` / worker: `batchSize`, `model`, `maxAttempts` |
| httpRequest 노드(하드코딩) | LLM 엔드포인트 `host.docker.internal:1234` |

## 설계 결정 (확정)

1. **요약 LLM**: 로컬/claude **둘 다 지원**, `summary_backend` 설정값(`local`|`claude`)으로 스위치. 과설계 금지 — 단순 분기.
2. **전환**: **기능 플래그(`enabled`) 토글 후 컷오버.** OFF 배포 → 수동 검증 → n8n OFF → ON.
3. **비밀값**: 기준은 "비밀이냐"가 아니라 "**자주 튜닝하는 손잡이냐, 한 번 세팅하는 인프라냐**".
   - UI 편집(DB): 운영 손잡이 + `DISCORD_WEBHOOK_URL`(평문 노출 — CF Access 뒤 단일 사용자라 위험 낮음).
   - env 유지(인프라): `JOB_PROXY_URL`, `JOB_PROXY_SECRET`, LLM 엔드포인트, `POSTGRES_*`.
   - 근거: Discord 웹훅은 채널 POST 전용 단일권한 URL(유출 시 30초 회전). 프록시 시크릿은 set-and-forget이라 손잡이가 아님.
4. **실행 모델**: **FastAPI 프로세스 내 APScheduler.** 기존 리서치 자동모드 스케줄러(`research/scheduler.py`)에 collector·worker 잡 2개 추가. 물량이 작아(하루 1회 + 5분 배치20) 별도 컨테이너 불필요.

## 아키텍처

```
career-agent/backend/app/
├── collect/                    ← 신규 (research/ 구조 미러)
│   ├── sources/
│   │   ├── wanted.py           ← 원티드 목록 스크레이핑+정규화 (카테고리 순회 + 제목필터)
│   │   └── jumpit.py           ← 점핏 목록 스크레이핑+정규화 (키워드 검색)
│   ├── collector.py            ← 목록 수집 → pending INSERT (dedup)
│   ├── worker.py               ← pending → 상세조회 → 요약 → done/skip/fail
│   ├── summarize.py            ← summary_backend 스위치 (local LM Studio | claude)
│   └── health.py               ← 로컬 LLM 헬스체크 게이트
├── settings_repo.py            ← app_settings 싱글턴 CRUD
├── activity.py                 ← 신규: 인메모리 Activity Registry (app.state 공유 상태)
├── claude_client.py            ← 수정: stream-json 파싱 + on_step 콜백
├── routers/
│   ├── settings.py             ← GET/PUT /api/settings
│   ├── collect.py              ← POST /api/collect/run, /api/collect/worker/run
│   └── status.py               ← 신규: GET /api/status (라이브 실행 상태)
└── research/scheduler.py       ← collector·worker 잡 등록 추가(기존 파일 확장)

frontend/src/
├── pages/Settings.tsx          ← 설정 관리 페이지 (/settings)
├── pages/Status.tsx            ← 신규: 라이브 상태 모니터 (/status)
├── components/ChipInput.tsx    ← text[]/int[] 공용 칩 입력
├── components/Segmented.tsx    ← summary_backend 토글
├── settingsApi.ts              ← getSettings/putSettings/runCollect/runWorker
└── statusApi.ts                ← getStatus (폴링)
```

### 데이터 흐름

1. **Collector 틱(매일 collect_hour시)** → `enabled`면 진행(아니면 no-op) → `settings` 읽기 → 원티드(카테고리 순회+제목필터)+점핏(키워드 검색) 스크레이핑 → 정규화 → `jobs`에 `pending` INSERT (`ON CONFLICT (source, job_id) DO NOTHING`)
2. **Worker 틱(worker_interval_min분)** → `enabled` && LLM 헬스 OK → `settings` 읽기 → `pending` batch_size건 원자적 점유(`SELECT … FOR UPDATE SKIP LOCKED`) → 상세조회(프록시 경유) → `summarize`(local/claude) → `done`/`skip`/`fail` UPDATE, `max_attempts` 초과 시 `fail`

두 스케줄 잡 모두 `enabled` 플래그로 게이트된다. **수동 트리거 엔드포인트(`/api/collect/run`, `/api/collect/worker/run`)는 `enabled`와 무관하게 실행**된다 — 컷오버 검증 시 `enabled=false` 상태에서 수동 실행이 목적이기 때문. (단 워커 수동 실행도 LLM 헬스게이트는 적용.)

### 에러 처리

- LLM 다운 → 워커 틱 스킵(헬스게이트), 공고를 억울하게 fail 안 함.
- 스크레이프 실패 → 로그 남기고 스케줄러는 안 죽음.
- `max_attempts` 초과 → `fail`.
- claude 백엔드는 기존 `claude_client` 재사용.

## 설정 스키마

### `app_settings` — 단일 행(싱글턴) 테이블

```sql
CREATE TABLE app_settings (
  id                        int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  -- 수집기
  keywords                  text[]  NOT NULL,
  allowed_wanted_categories int[]   NOT NULL,
  max_career_years          int     NOT NULL,
  max_pages                 int     NOT NULL,
  collect_hour              int     NOT NULL,
  -- 워커
  batch_size                int     NOT NULL,
  model                     text    NOT NULL,
  summary_backend           text    NOT NULL CHECK (summary_backend IN ('local','claude')),
  max_attempts              int     NOT NULL,
  worker_interval_min       int     NOT NULL,
  -- 제어 · 알림
  enabled                   boolean NOT NULL DEFAULT false,
  discord_webhook_url       text    NOT NULL DEFAULT '',
  updated_at                timestamptz NOT NULL DEFAULT now()
);
```

### 필드별 타입·검증·시드값

| 필드 | 타입 | 검증 | 시드(현 n8n) |
|---|---|---|---|
| `keywords` | `string[]` | 비어있지 않음, 각 항목 trim·공백 제거 | `SEARCH_KEYWORDS` env 분해 |
| `allowed_wanted_categories` | `int[]` | 각 항목 정수 | `[518, 507]` |
| `max_career_years` | `int` | `>= 0` | `2` |
| `max_pages` | `int` | `>= 1` | `9999` |
| `collect_hour` | `int` | `0–23` | `9` |
| `batch_size` | `int` | `1–100` | `20` |
| `model` | `string` | 비어있지 않음 | `kanana-1.5-8b-instruct-2505-mlx` |
| `summary_backend` | `'local'\|'claude'` | enum | `local` |
| `max_attempts` | `int` | `1–20` | `5` |
| `worker_interval_min` | `int` | `>= 1` | `5` |
| `enabled` | `bool` | — | `false` |
| `discord_webhook_url` | `string` | 선택(빈문자 허용) | `DISCORD_WEBHOOK_URL` env |

**시드 마이그레이션:** 최초 기동 시 싱글턴 행이 없으면 위 값으로 1행 INSERT. `keywords`·`discord_webhook_url`은 기존 env 값을 1회 읽어 채움 → 이후 두 값은 DB가 정본, env 무시.

### API 계약

```
GET /api/settings  → 200  { …전체 필드…, updated_at }
PUT /api/settings  → 200  본문=전체 객체 → Pydantic 검증 → 싱글턴 UPSERT → 갱신본 반환
                   → 422  검증 실패(필드별 에러)
POST /api/collect/run          → 202  collector 1회 (스크레이프 → pending), 결과 카운트 반환
POST /api/collect/worker/run   → 202  worker 1배치 (pending → done), 결과 카운트 반환
```
- 부분수정(PATCH) 없이 **전체 객체 교체** — 단순·멱등.

### 반영 타이밍

- **즉시 반영(다음 틱)**: `keywords, allowed_wanted_categories, max_career_years, max_pages, batch_size, model, summary_backend, max_attempts, enabled, discord_webhook_url` — 파이프라인이 매 틱 `settings`를 다시 읽음.
- **재스케줄**: `collect_hour`, `worker_interval_min` — PUT에서 이 값이 바뀌면 해당 APScheduler 잡을 `reschedule_job`으로 즉시 갱신(재시작 불필요).

## 컷오버 시퀀스

이중 쓰기 방어:

| 충돌 | 방어 |
|---|---|
| Collector 이중 INSERT | `INSERT … ON CONFLICT (source, job_id) DO NOTHING` (멱등) |
| Worker 이중 처리 | Python 워커는 `SELECT … FOR UPDATE SKIP LOCKED` 원자 점유 + 컷오버 순서로 n8n 워커 먼저 OFF |

**선행 의존성:** `jobs` 테이블에 `(source, job_id)` UNIQUE/PK 제약 존재 확인(구현 계획에서 검증). 없으면 추가.

```
0. [준비]  마이그레이션으로 app_settings 싱글턴 시드 (enabled=false), keywords·webhook은 env 1회 복사
1. [배포]  Python 파이프라인 배포. enabled=false → 스케줄러 등록되되 매 틱 no-op. n8n 무중단.
2. [검증-설정]  설정 페이지 GET/PUT 확인, 시드값이 n8n과 일치하는지 대조.
3. [검증-수집]  POST /api/collect/run → dedup으로 n8n 켜져 있어도 안전(중복 0).
              삽입 pending 행 필드 스팟체크. 재실행 시 신규 0건(멱등).
4. [n8n 워커 OFF]  n8n UI에서 02-worker 비활성화.
5. [검증-워커]  POST /api/collect/worker/run → pending→done, 요약, skip/fail, 헬스게이트(억울한 fail 없음) 확인.
6. [n8n 수집기 OFF]  n8n UI에서 01-collector 비활성화.
7. [전환]  설정 페이지에서 enabled=true 저장 → Python 스케줄러 인수.
8. [모니터]  다음 워커 틱 + 다음날 09시 collector 틱 관찰.
```

**롤백(언제든):** `enabled=false` 저장(Python 즉시 정지) + n8n 두 워크플로우 재활성화. Python은 DB만 건드리고 스키마 변경 없음.

## 설정 페이지 UI

기존 career-agent 디자인 토큰(liquid-glass, hanging-label `.field`, blue brand, `SPRING_UI`, pill/btn-primary) 재사용.

- 라우트 `/settings`, 상단 내비에 "설정" 추가. 진입 시 `GET /api/settings`로 폼 초기화.
- **한 폼, 4개 섹션**(여백 그룹핑): 수집 제어 / 수집기 / 워커 / 알림.

```
설정                                              [저장] ← dirty일 때만 활성

┌─ 수집 제어 ─────────────────────────────────┐
│  수집 활성화   ●━━ (마스터 스위치, enabled)    │
│  [지금 수집] [워커 1회]   방금: +12건 pending  │  ← 저장상태에서 실행
└──────────────────────────────────────────────┘
┌─ 수집기 ───────────────────────────────────┐
│  키워드   [백엔드 ×][데이터 엔지니어 ×] [+…]  │  ← text[] 칩
│  원티드 카테고리  [518 ×][507 ×] [+…]        │  ← int[] 칩
│  경력 상한 [2]년   페이지 상한 [9999]         │
│  수집 시각 매일 [09]시                        │
└──────────────────────────────────────────────┘
┌─ 워커 ─────────────────────────────────────┐
│  배치 크기 [20]   재시도 [5]회   워커 주기 [5]분│
│  요약 백엔드 ( 로컬 LLM )|( claude )           │  ← segmented
│  모델 [kanana-1.5-8b-instruct-2505-mlx]      │
└──────────────────────────────────────────────┘
┌─ 알림 ─────────────────────────────────────┐
│  Discord 웹훅 [https://discord.com/api/…]    │  ← 평문 노출
└──────────────────────────────────────────────┘
```

### 상호작용·피드백

- **저장:** 폼 로컬 상태 + dirty 추적(변경 없으면 저장 비활성). `PUT` 전체 객체. 성공→"저장됨" 토스트+dirty 해제. 422→필드별 인라인 에러. 클라이언트 선검증으로 대부분 차단.
- **마스터 스위치:** 폼 필드로 취급(플립→dirty→저장 적용). 상태 색+위치로 명확(회색 OFF/블루 ON), press 즉각 반응 + `SPRING_UI`.
- **수동 트리거:** 저장된 설정으로 서버 실행 → **dirty일 땐 비활성**("먼저 저장하세요"). 실행 중 `Working` 점(리서치 패널 재사용), 완료 시 결과 요약.
- **칩 입력:** Enter 추가(trim·중복·빈값 제거), × 제거. 추가/제거 spring rise, `prefers-reduced-motion`이면 fade만. 카테고리는 숫자만 허용.
- **반영 힌트:** `수집 시각`·`워커 주기` 옆 caption "저장 시 즉시 재적용".

### 컴포넌트 분해

```
Settings.tsx      ← 페이지: GET/PUT, dirty 상태, 섹션 조립
├── ChipInput.tsx ← text[]/int[] 공용 칩 입력 (mode: 'text'|'number')
├── Segmented.tsx ← summary_backend 토글
└── (재사용) Working, .field, pill, btn-primary
```
- 검증은 백엔드 Pydantic이 정본, 프론트는 UX용 선검증.

## 모니터링 — 라이브 실행 상태

"서버가 지금 무슨 작업을 어느 단계에서 실행 중인가"를 실시간으로 본다. DB 카운트가 아니라 **실행 중 작업이 자기 진행 단계를 게시**하는 방식.

### 데이터 소스: 인메모리 Activity Registry

- `app.state.activity` — 파이프라인별 현재 상태 dict: `{stage, detail, progress, started_at}`.
- 실행 중 collector/worker/research가 단계 이동 시마다 이 구조를 갱신.
- **단일 프로세스(APScheduler in-process) 아키텍처라 가능** — 파이프라인과 status 엔드포인트가 같은 프로세스라 별도 DB 하트비트·이벤트버스 불필요. (재시작 시 초기화됨 = 라이브 상태이므로 OK.)
- `activity.py`가 registry 접근을 캡슐화(`set_stage(pipeline, ...)`, `clear(pipeline)`, `snapshot()`).

### 파이프라인별 게시 단계

| 파이프라인 | 단계 | 진행률 |
|---|---|---|
| Collector | `idle` → `스크레이핑(소스·카테고리/키워드·페이지)` → `pending 적재` → `idle` | 페이지 n/전체, 누적 건수 |
| Worker | `idle` → `배치 N건 점유` → `상세조회(job)` → `요약 중(job·backend)` → `기록` | i / batch |
| claude -p 리서치 | `idle` → `기업 리서치 중` → (claude 서브스텝) → `공고 리서치 중` → (claude 서브스텝) → `파싱` | 실행 중 작업 |

### claude -p 스트림 파싱 (결정: B — 내부 서브스텝까지)

현재 `claude_client.run_claude`는 `--output-format json`(블로킹, 최종 봉투 1개). 서브스텝을 보려면 **스트리밍으로 전환**:

- `--output-format json` → **`--output-format stream-json --verbose`** (`-p`+stream-json은 `--verbose` 필수).
- `proc.communicate()`(끝까지 대기) → **`proc.stdout` 라인별 NDJSON 파싱**(실시간). 이벤트 순서: `system(init)` → `assistant`(텍스트/`tool_use`) → `user`(tool_result) → `result`(최종).
- `type:result` 라인에서 기존처럼 `result` 추출·반환 → **반환 계약 유지**. 타임아웃은 `communicate()` 대신 전체 데드라인으로 재구성, 기존 실패·타임아웃 `RuntimeError` 처리 보존.
- **결합 분리 — 콜백 주입**: `run_claude(prompt, *, on_step=None, ...)`. 이벤트마다 `on_step(label)` 호출. `claude_client`는 Activity Registry를 모름 — 러너가 `on_step`에 registry 갱신 콜백을 꽂음.
- 잘린 라인·비JSON 라인은 무시(방어적 파싱).

**tool_use → 단계 라벨 매핑:**

| claude 이벤트 | 라벨 |
|---|---|
| `WebSearch` | `웹 검색: "{query}"` |
| `WebFetch` | `페이지 확인: {domain}` |
| assistant 텍스트(도구 없음) | `분석·작성 중` |
| 기타 tool | `{tool} 실행 중` |

### API

```
GET /api/status → 200 {
  activity: { collector: {stage, detail, progress, started_at}|null,
              worker:    {...}|null,
              research:  [ {stage, detail, ...} ]  // 동시 여러 건 가능 },
  counts:   { pending, done, failed, skipped, research_running },  // DB 파생(보조)
  llm_health: 'ok'|'down',
  enabled:  bool,
  next_ticks: { collector: <다음 09:00>, worker: <다음 주기> }
}
```
- `counts`·`llm_health`는 파생(싸므로 라이브 뷰의 맥락으로 함께 반환).

### UI: `/status` 페이지

- 실행 중 카드(수집기/워커/리서치): stage + progress bar + detail. idle이면 "다음 예정 틱".
- 상단 보조 스트립: 백로그 `pending N`, LLM 헬스 pill, `enabled` 상태.
- 프론트 **2~3초 폴링**(`getStatus`, 리서치 패널 폴링 패턴 재사용). 페이지 벗어나면 폴링 중단.
- 렌더 예:
  ```
  ● 실행 중
    워커     요약 중  ▓▓▓▓░░ 4/20   "토스 · 백엔드 엔지니어" (claude)
    리서치   웹 검색 중             "당근마켓 자본금 매출"
    수집기   idle · 다음 09:00
  ```
- 디자인 토큰 재사용(liquid-glass, `Working` 점, pill, `SPRING_UI`). 애니는 `prefers-reduced-motion` 준수.

### 범위

- v1 = **라이브 활동 + 파생 카운트**. 실행 이력 로그(`pipeline_runs` 테이블)는 이번 want("지금 실행/단계")와 별개라 **future**(무인 운영 강화 시 추가).

## 테스트

**백엔드**
- 스크레이핑 파싱·정규화: **녹화된 fixture JSON**으로(라이브 외부 API 호출 금지). 원티드 카테고리+제목필터, 점핏 키워드검색 각각.
- 키워드 이중역할: 점핏 query 생성, 원티드 `titleHit` 단어경계 매칭(포함/미포함 케이스).
- settings CRUD + Pydantic 검증(범위·enum·빈 키워드).
- 워커 상태전이: pending→done/skip/fail, `max_attempts` 초과→fail.
- dedup: 같은 (source, job_id) 재삽입 시 신규 0.
- 헬스게이트: LLM 다운 시 틱 스킵, fail 안 함.
- summarize 스위치: local/claude 분기.
- Activity Registry: set_stage/clear/snapshot, 파이프라인별 독립 키, research 동시 여러 건.
- claude_client 스트림 파서: NDJSON 이벤트 fixture → 단계 라벨(tool_use 매핑)·최종 `result` 추출, 잘린/비JSON 라인 무시, `on_step` 호출 순서.
- `GET /api/status` 응답 구조(activity + counts + llm_health + next_ticks).

**프론트**
- ChipInput: 추가/중복/빈값/숫자모드 거부.
- dirty→저장 흐름(모킹 PUT), 422 에러 렌더.
- 수동 트리거 dirty 비활성.
- Status: 모킹 `getStatus` → 실행 중 카드/진행률/idle 렌더, 폴링 갱신, 언마운트 시 폴링 중단.

## 범위 밖 (YAGNI)

- 03-notifier 이관(Discord 알림 발송)은 이번 범위 아님. 웹훅 필드는 미리 한 탭에 모아두는 용도이며, notifier 이관 전까진 n8n 알림 동작에 영향 없음.
- 마스킹/write-only 시크릿 처리(과설계로 판단).
- 별도 worker 컨테이너, 외부 cron.
- 수집 소스 추가(사람인 등) — 현행 원티드+점핏만 이식.
- 실행 이력 로그 테이블(`pipeline_runs`) — 라이브 모니터는 v1, 과거 이력·실패원인 아카이브는 future.
