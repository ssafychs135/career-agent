# 알림 발송 이관(n8n 03-notifier → career-agent) 설계

**작성일:** 2026-07-23
**목표:** n8n에서 실서비스 중인 공고 알림(Discord)을 career-agent로 이관한다. 전역 필터를 존중하고, 죽어 있던 기존 알림 경로도 되살린다.

## 배경 — 이건 신규 개발이 아니라 컷오버

n8n `03-notifier.json`이 **지금도 활성 상태로 5분마다** 돌고 있다. 측정 결과 `status='done'` 447건 전부 `notified_at`이 찍혀 있고 미전송은 0건 — 정상 동작 중인 기능이다. 따라서 양쪽이 동시에 돌면 같은 행을 두고 경합한다. 컷오버 절차가 설계의 일부다.

### 원본 동작 (n8n)

5분마다: `status='done' AND notified_at IS NULL` 30건 조회 → Discord 임베드 카드 생성(10개씩 묶음) → 웹훅 POST → `notified_at=now()` 마킹.

### 발견한 결함 — 기존 `push()`는 프로덕션에서 무동작

`app/research/discord.py`의 `push()`는 `os.environ["DISCORD_WEBHOOK_URL"]`에서만 읽고 비어 있으면 조용히 return한다. 확인 결과:

| 위치 | 상태 |
|---|---|
| `app_settings.discord_webhook_url` | **설정됨** (124자) |
| 백엔드 컨테이너 `DISCORD_WEBHOOK_URL` env | **없음** |

즉 **리서치 완료 알림도, run_log의 스케줄 실패 알림도 한 번도 발송된 적이 없다.** 실패를 조용히 무시하는 설계라 드러나지 않았다. n8n은 자체 env로 웹훅을 갖고 있어 공고 알림만 동작했다.

### 이미 준비된 것

`jobs.notified_at TIMESTAMPTZ`와 인덱스 `idx_jobs_notify (status, notified_at)`가 baseline 마이그레이션(0001)에 이미 있다. **컬럼 마이그레이션이 필요 없다.** 관련 타입: `id` = `bigint`, `tech_stacks` = `TEXT[]`(asyncpg가 리스트로 반환), `locations` = `text`.

## 결정 사항 (확정)

1. **전역 필터를 알림에도 적용.** 숨긴 기업·허용 지역 밖 공고는 발송하지 않는다.
2. **걸러진 공고는 소비 처리** — 발송 없이 `notified_at`을 찍는다. 나중에 숨김을 해제해도 밀린 알림이 한꺼번에 오지 않는다.
3. **웹훅 출처를 설정으로 통일.** 알림기와 기존 `push()` 모두 `app_settings.discord_webhook_url`을 쓴다(env는 폴백).
4. **컷오버는 플래그로.** `notify_enabled` 기본 false로 배포하고, 수동 검증 → n8n 비활성화 → 토글 ON 순으로 전환한다.

## 아키텍처

### 웹훅 출처 통일

`app/research/discord.py`에 모듈 캐시를 둔다(파일 위치는 유지 — 이동은 리서치/run_log 임포트까지 건드리므로 컷오버 중 위험을 키운다):

```python
_webhook = ""                       # 앱 시작·설정 저장 시 갱신
def set_webhook(url: str) -> None   # 캐시 설정
def _url() -> str                   # 캐시 → env 폴백
async def push(content) -> None                     # 기존 시그니처 유지
async def push_embeds(content, embeds) -> None      # 신규
```

배선 지점 2곳: `main.py` lifespan(설정 로드 직후), 설정 PUT 핸들러(저장 직후). 둘 다 이미 설정을 손에 쥐고 있는 지점이라 conn을 새로 흘릴 필요가 없다.

`push_embeds`는 실패 시 **예외를 던진다**(`push`와 다름) — 알림기가 마킹 여부를 판단해야 하므로 조용히 삼키면 안 된다.

### 알림기 `app/notify/notifier.py`

**조회** (원본 SELECT에 `locations` 추가 — 지역 필터에 필요):

```sql
SELECT id, source, job_id, company, title, url, locations,
       min_career, max_career, tech_stacks, summary
FROM jobs WHERE status='done' AND notified_at IS NULL
ORDER BY collected_at LIMIT $1
```

**마킹:** `UPDATE jobs SET notified_at=now() WHERE id = ANY($1::bigint[])`

**흐름:**
1. 조회(최대 `NOTIFY_BATCH = 30`).
2. 전역 필터로 분류 → 통과분 / 걸러진 분.
3. 걸러진 분은 **즉시 마킹**(발송 없음).
4. 통과분을 임베드로 만들어 10개씩 묶어 발송하고, **청크가 성공할 때마다 그 청크의 id만 마킹**.

4번이 원본과 다른 유일한 지점이다. n8n은 전부 보낸 뒤 한 번에 마킹하므로, 3청크 중 2번째가 실패하면 아무것도 마킹되지 않고 다음 틱에 1번째가 **중복 발송**된다. 청크 단위 마킹이면 실패 지점 뒤만 재시도되고 중복이 없다.

**순수 함수(단위 테스트 대상):**

- `build_embed(row) -> dict` — 원본 JS 이식. 제목 `{company} — {title}` 250자, 설명은 요약에서 `기술스택:` 줄을 제거 후 400자(초과 시 `…`), 빈 값이면 `(요약 없음)`. `color=5814783`. 필드 3개: 경력(`min~max`, 둘 다 없으면 `무관`), 기술스택(1000자, 없으면 `-`), 출처.
- `passes_filter(row, allowed_regions, hidden_companies) -> bool` — 기업명 정확일치 제외, 지역은 `locations` 문자열에 허용 지역이 하나라도 포함되면 통과. **빈 배열이면 해당 조건 미적용**(목록 필터와 동일 규칙).
- `chunk(items, size)` — 10개씩 분할.

**반환:** `{"picked": n, "sent": n, "skipped": n}`

### 스케줄러 · 트리거

- `notifier_job` 5분 주기(`NOTIFY_INTERVAL_MIN = 5`). `settings.notify_enabled`가 false면 no-op.
- 미전송이 0건이면 peek 게이트로 조기 종료 — 워커와 동일하게 **LLM/네트워크 요청도, run_log 행도 만들지 않는다**.
- `run_log`에 `pipeline='notifier'`로 기록(스케줄=`scheduled`, 수동=`manual`).
- 수동 트리거 `POST /api/notify/run` — 컷오버 검증용. `notify_enabled`와 무관하게 동작한다(수동 실행은 명시적 행동).

### 설정

마이그레이션 `0006_notify_enabled`: `app_settings.notify_enabled boolean NOT NULL DEFAULT false`. `Settings` 모델·`SETTINGS_DEFAULTS`·`_COLUMNS`에 동일 추가.

배치 크기는 상수 `NOTIFY_BATCH = 30`으로 고정한다(원본 값). 설정 노출은 YAGNI.

### 화면

Ops의 기존 **알림** 카드에 추가:
- `알림 활성화` 토글(`notify_enabled`)
- `지금 알림 발송` 버튼 → `POST /api/notify/run`, 결과를 기존 실행 결과 문구 패턴으로 표시(`발송 N건 · 건너뜀 M건`)

## 컷오버 절차

1. 배포 — `notify_enabled=false`라 아무 동작 없음(안전).
2. Ops에서 **지금 알림 발송**으로 수동 검증(현재 미전송 0건이므로 새 공고가 있을 때 확인).
3. **n8n `03-notifier` 비활성화** — 이 단계 전에는 토글을 켜지 않는다.
4. Ops에서 `알림 활성화` ON.

현재 미전송 0건이라 전환 시점에 밀린 알림이 쏟아지지 않는다.

## 테스트

**백엔드**
- `build_embed`: 기술스택 줄 제거, 400자 절단, 제목 250자, 경력 `무관`/`min~max`, 빈 요약 → `(요약 없음)`, 필드 3종.
- `passes_filter`: 숨긴 기업 제외, 허용 지역 포함/미포함, **빈 배열이면 통과**.
- `chunk`: 10개 경계.
- `notify_tick`: 걸러진 분은 발송 없이 마킹 / 통과분은 청크별 발송 후 그 청크만 마킹 / **중간 청크 실패 시 성공분만 마킹되고 예외 전파**(중복 방지 회귀 테스트) / 조회 0건이면 발송·마킹 없음.
- `set_webhook`/`_url` 폴백, `push_embeds`가 실패 시 예외를 던지는지.
- 스케줄러: `notify_enabled=false`면 no-op, 미전송 0건이면 run_log 미기록.
- `POST /api/notify/run` 응답 형태.

**프론트**
- 알림 토글이 `notify_enabled`로 저장됨.
- `지금 알림 발송` 클릭 → 결과 문구 표시.

## YAGNI (범위 밖)

- 이메일·Sheets·Notion 채널(원본 03-notifier는 Discord 전용).
- 배치 크기·주기·임베드 색상의 설정 노출.
- 알림 재발송/이력 UI(run_log가 실행 단위 기록을 담당).
- `discord.py`의 `app/notify/`로의 이동(임포트 3곳 변경 — 컷오버 후 별도 정리).
