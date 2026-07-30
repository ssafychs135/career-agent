# 마감·삭제 공고 숨기기(공고 생존 재검증) 설계

**작성일:** 2026-07-30
**목표:** 마감·삭제된 공고를 감지해 목록과 알림에서 제외한다.

## 배경 — 목록의 3할이 지원할 수 없는 공고다

프로덕션 표본 조사 결과:

| 소스 | 전체 | 마감일 보유 | 죽은 공고 |
|---|---|---|---|
| 원티드 | 434 | 0 | 표본 25건 중 **8건(32%)** |
| 점핏 | 55 | 55 | **13건**(`closed_at` 경과) |

원티드 434건에 32%를 대입하면 약 139건, 점핏 13건을 더해 **489건 중 약 150건(31%)이 이미 죽은 공고**로 추정된다. 사용자가 목록에서 클릭한 공고가 3번에 1번꼴로 마감돼 있다는 뜻이다. 목록 신뢰도 문제다.

### 감지 신호 — 소스별로 완전히 다르다

실측한 API 반응:

| 상태 | 원티드 | 점핏 |
|---|---|---|
| 살아있음 | `status: "active"`, `hidden: false` | `closedAt` 미래 |
| 마감 | `status: "close"` 또는 `"draft"` + `hidden: true` | `closedAt < now()` |
| 삭제 | **HTTP 404** (`error_code: 11001`) | **HTTP 400** |

점핏은 마감돼도 `status=0`, `positionStatus="CHECKED"`로 살아있는 공고와 **동일하다** — `closedAt`만이 유일한 신호다. 반대로 원티드는 `due_time`이 항상 null이라 마감일이 무의미하고, `status` 필드가 유일한 신호다. 두 소스의 판정 로직은 공유할 수 없다.

**점핏 만료는 API 호출이 필요 없다.** `closed_at`이 이미 수집돼 DB에 있다.

## 결정 사항 (확정)

1. **재검증 워커를 신설한다.** 수집 목록에서 사라진 것을 마감으로 간주하는 방식은 키워드·정렬 변동에 취약해 채택하지 않는다.
2. **상태를 기록하고 목록에서 숨긴다.** 행을 지우지 않는다 — 오판정 복구와 통계가 가능해야 한다.
3. **하루 1회 전수검사, `open` 상태만 검사한다.** 죽은 공고는 다시 보지 않는다.
4. **실행 시각은 00:00 KST.** 수집(09시)·요약과 겹치지 않는 조용한 시간대다.
5. **프론트 변경 없음.** 마감 공고를 다시 보는 토글·화면은 만들지 않는다.

## 아키텍처

### 데이터 모델 — 마이그레이션 `0008_posting_state`

`jobs.status`는 파이프라인 상태(`pending`/`processing`/`done`/`failed`)다. 여기에 마감을 섞으면 두 의미가 충돌하므로 별도 컬럼을 둔다.

```sql
ALTER TABLE jobs
  ADD COLUMN IF NOT EXISTS posting_state text NOT NULL DEFAULT 'open',
  ADD COLUMN IF NOT EXISTS state_checked_at timestamptz;
CREATE INDEX IF NOT EXISTS idx_jobs_posting_state
  ON jobs (posting_state, state_checked_at);
```

`posting_state` ∈ `open` | `closed` | `deleted`.

기본값 `open`이라 **배포 직후 기존 489건이 전부 그대로 보인다** — 첫 검사가 돌기 전까지 동작이 바뀌지 않는다.

`state_checked_at`은 판정 시각이다. 전수검사라 스케줄링에 필요하진 않지만, 없으면 오판정이 언제 생겼는지 추적할 수 없다.

down은 두 컬럼과 인덱스 DROP, `down_revision = "0007_task_models"`.

### 판정 로직 — `app/collect/liveness.py` (신설)

소스별 신호가 다르므로 순수 함수 둘로 분리한다. 네트워크는 호출자가 담당한다.

```python
OPEN, CLOSED, DELETED = "open", "closed", "deleted"

def wanted_state(http_status: int, payload: dict) -> str:
    """404 → deleted / status != "active" 또는 hidden → closed / 그 외 open."""

def jumpit_state(http_status: int, payload: dict, now: datetime) -> str:
    """400 → deleted / closedAt < now → closed / 그 외 open."""
```

**판정 불가는 `open`을 유지한다.** 타임아웃·5xx·프록시 오류로 공고를 숨기면 안 된다. 잘못 숨기는 쪽이 잘못 보여주는 쪽보다 나쁘다 — 사용자는 숨겨진 공고의 존재를 모르므로 복구를 요청할 수조차 없다. 따라서 두 함수 모두 **명확한 사망 신호가 있을 때만** `closed`/`deleted`를 반환하고, 나머지는 전부 `open`이다.

`jumpit_state`가 `now`를 인자로 받는 이유: 시간에 의존하는 판정을 테스트 가능하게 만들기 위해서다.

### 재검증 워커 — `app/collect/verify.py` (신설)

```python
VERIFY_LOCK_KEY = 8123402      # 알림기(8123401)와 다른 키
VERIFY_HOUR = 0                # KST 자정
```

**흐름:**

1. `pg_try_advisory_lock(VERIFY_LOCK_KEY)` — 미획득이면 즉시 종료(수동·스케줄 중복 방지).
2. **점핏 만료 일괄 처리** — API 없이 SQL 한 번:
   ```sql
   UPDATE jobs SET posting_state='closed', state_checked_at=now()
   WHERE posting_state='open' AND source='jumpit'
     AND closed_at IS NOT NULL AND closed_at < now()
   ```
3. 남은 `posting_state='open'` 행을 조회해 상세 API를 순회한다. 원티드는 기존 프록시 경로(`JOB_PROXY_URL`)를 그대로 쓴다.
4. 판정 결과를 행별로 기록한다(`state_checked_at`은 판정이 `open`이어도 갱신).
5. `finally`에서 `pg_advisory_unlock`.

**반환:** `{"checked": n, "closed": n, "deleted": n, "failed": n}` — `failed`는 판정 불가(=open 유지)한 건수다.

`run_log`에 `pipeline='verify'`로 기록한다. `run_log.py`의 `_KO`에 `"verify": "생존 확인"`을 더하고, 프론트 `runsFormat.ts`의 `Pipeline` 유니온·`pipelineLabel`·`runSummary`에도 추가한다 — **알림기 이관 때 프론트 포매터가 새 파이프라인을 몰라 검증 화면이 잘못된 라벨을 보여준 전례가 있다.**

### 스케줄러 배선

`collect_scheduler.py`에 잡을 하나 더 등록한다:

```python
sched.add_job(verify_job, "cron", id="verify", hour=VERIFY_HOUR, minute=0, args=[get_ctx])
```

스케줄러는 이미 `timezone="Asia/Seoul"`이므로 `hour=0`은 KST 자정에 뜬다.

`settings.enabled`가 false면 no-op한다(수집기·워커와 동일한 컷오버 규칙).

수동 트리거 `POST /api/verify/run`을 둔다 — 배포 직후 첫 검사를 자정까지 기다리지 않고 검증하기 위해서다. 수집기·알림기의 수동 엔드포인트와 같은 패턴이다.

### 목록 필터

`jobs_repo.build_list_query`의 절 조립부에 추가한다(전역 필터가 붙는 자리와 동일):

```python
clauses.append("posting_state = 'open'")
```

사용자 입력이 아니고 항상 적용되므로 파라미터가 아니라 리터럴이다. **프론트 변경은 없다.**

**공고 상세(`get_job`)는 필터하지 않는다.** 디스코드 알림 링크나 북마크로 들어온 사용자에게 마감됐다고 404를 내면 혼란스럽다. 목록에서만 빠진다.

### 알림기

`notifier.py`의 `SELECT_SQL`에 `AND posting_state = 'open'`을 더한다. 현재 미전송이 0건이라 당장 영향은 없지만, 마감된 공고를 디스코드로 보내는 것은 명백한 오동작이다.

### 되살아남

수집기가 목록에서 다시 본 공고는 살아있다는 뜻이다. 오판정과 재게시를 자동 복구하기 위해, `collect()`의 삽입 루프가 끝난 뒤 이번 회차에 긁힌 키 전체를 대상으로 UPDATE를 한 번 실행한다:

```sql
UPDATE jobs SET posting_state = 'open', state_checked_at = NULL
WHERE posting_state <> 'open'
  AND (source, job_id) IN (SELECT unnest($1::text[]), unnest($2::text[]))
```

`$1`/`$2`는 이번 수집의 `source` 배열과 `job_id` 배열이다(같은 길이, 같은 순서). 긁힌 행이 없으면 실행하지 않는다.

`state_checked_at`을 NULL로 되돌리는 이유: 목록에 보였다는 것은 재검증기가 상세 API로 확인한 것과 다른 종류의 근거다. "재검증기가 확인한 적 없음"으로 되돌려 두는 편이 정직하다(전수검사라 스케줄링에는 영향 없음).

`INSERT ... ON CONFLICT DO UPDATE`로 합치지 않는 이유: 방금 고친 `inserted` 카운트가 `RETURNING id`로 실제 신규 삽입만 센다. `DO UPDATE`로 바꾸면 중복 행도 `RETURNING`에 잡혀 카운트가 다시 거짓말을 한다.

## 테스트

**백엔드**

- `wanted_state`: 404 → deleted / `status="close"` → closed / `status="draft"` → closed / `hidden=true`인데 `status="active"` → closed / 정상 → open / **500·타임아웃 페이로드 → open**(안전 기본값 회귀 테스트).
- `jumpit_state`: 400 → deleted / `closedAt` 과거 → closed / `closedAt` 미래 → open / `closedAt` 없음 → open / **판정 불가 → open**.
- 실측 페이로드 기반 테스트: 원티드 `{"error_code": 11001}` 404, 점핏 만료 응답(`status=0`·`positionStatus="CHECKED"`이지만 `closedAt` 과거)이 각각 올바로 판정되는지 — **점핏은 status가 살아있는 공고와 같으므로 이 케이스가 회귀 방지의 핵심이다.**
- `verify_tick`: 점핏 만료가 API 호출 없이 처리되는지 / `open`이 아닌 행은 조회되지 않는지 / 락 미획득 시 no-op / 반환 dict 형태 / 판정 불가가 `failed`로 집계되고 상태는 안 바뀌는지.
- `build_list_query`: `posting_state = 'open'` 절이 항상 포함되고(다른 필터가 하나도 없을 때도), limit/offset이 여전히 마지막 파라미터인지.
- 수집기 되살아남: `posting_state='closed'`인 행이 이번 수집에 다시 긁히면 `open`으로 돌아오는지 / 긁힌 행이 없으면 UPDATE를 실행하지 않는지 / `inserted` 카운트가 되살아남 때문에 늘지 않는지(회귀).
- `notifier`: `SELECT_SQL`에 `posting_state` 조건 포함.
- 마이그레이션 `0008`: 기본값 `'open'`이 DDL과 일치.
- 스케줄러: `verify` 잡이 `hour=0` cron으로 등록되고 타임존이 Asia/Seoul인지 / `enabled=false`면 no-op.
- `POST /api/verify/run` 응답 형태.

**프론트**

- `runsFormat`: `verify` 파이프라인 라벨이 `생존 확인`이고 요약이 `확인 N건 · 마감 M · 삭제 K` 형태인지. 다른 파이프라인 문구는 불변.

## 배포·검증

1. 배포 — 전 행이 `posting_state='open'`이라 **동작 불변**.
2. `POST /api/verify/run`으로 첫 전수검사를 수동 실행한다.
3. 결과를 표본 예측치와 대조: 원티드 약 139건(32%), 점핏 13건, 합계 약 150건. **크게 어긋나면 판정 로직을 의심한다** — 특히 실제가 훨씬 많으면 판정 불가를 closed로 잘못 처리하고 있을 가능성이 있다.
4. 목록에서 해당 공고들이 사라졌는지, 남은 공고 수가 예상과 맞는지 확인한다.

### 운영자가 알아야 할 것

- **첫 검사는 몇 분 걸린다.** 476건에 대해 상세 API를 순회하며, 원티드는 프록시를 거친다. 요약 워커가 건당 약 14초 걸리는 것과 달리 여기는 네트워크만 쓰므로 훨씬 빠르지만, 수동 실행 시 응답을 기다리지 말고 `run_log`로 확인하는 편이 낫다.
- **되돌리기는 SQL 한 줄이다.** `UPDATE jobs SET posting_state='open'`으로 전부 되살릴 수 있다. 행을 지우지 않는 설계의 이유다.
- **판정 불가는 조용하다.** 프록시가 통째로 죽으면 476건 전부 `failed`로 집계되고 아무것도 숨겨지지 않는다. `run_log`의 `failed` 수가 `checked`에 근접하면 감지가 아니라 인프라 문제다.

## YAGNI (범위 밖)

- 마감 공고 보기 토글·전용 화면
- 재검증 주기·시각의 설정 노출(상수 고정)
- 마감 임박 알림
- 점핏 `publishedAt`(게시일) 수집 — 별건
- 원티드 게시일 확보를 위한 HTML 스크레이핑
