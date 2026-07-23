# 실행 로그(작업 이력) 설계

**작성일:** 2026-07-23
**목표:** 수집기·워커·리서치 실행이 끝난 뒤에도 그 결과(성공/실패·건수·소요시간)를 대시보드에서 볼 수 있게 한다. 무인 스케줄 실행 실패는 디스코드로 알린다.

## 배경 / 문제

현재 `Activity`(인메모리 단일 슬롯)는 실행 **중** 단계만 담고, 각 실행 경로의 `finally: activity.clear(...)`로 완료 즉시 지워진다. 따라서 "방금 수집 눌렀는데 지나간 뒤 결과를 볼 수 없다". 게다가 push마다 Jenkins가 컨테이너를 자동 재배포하므로 인메모리 보관은 배포 때마다 소실된다 → **DB 영속화**가 필요하다.

## 결정 사항 (확정)

1. **저장:** Postgres `run_log` 테이블 (Alembic 마이그레이션 0004).
2. **범위:** 세 파이프라인 전부 — collector, worker, research.
3. **디스코드:** **스케줄러 실행 실패 시에만** 핑. 수동 실행·성공·워커 정상 틱은 무음. (리서치는 러너가 이미 자체 알림하므로 run_log 경로에서 중복 알림하지 않는다.)
4. **실시간:** SSE 미도입. 3초 폴링 유지 + "완료 시 재조회". `logged_run`에 향후 SSE 훅 지점만 남긴다.

## 아키텍처

세 파이프라인은 반환/호출 형태가 다르다:

| 파이프라인 | 반환 | 실행 | 경로 |
|---|---|---|---|
| collector (`collect`) | `{scraped, inserted}` | 동기 | 수동 라우터 + 스케줄러 |
| worker (`worker_tick`) | `{claimed, done, failed, skipped_tick}` | 동기 | 수동 라우터 + 스케줄러 |
| research (`research_company`/`research_job`) | `"done"\|"cached"\|"failed"` | `bg.add_task` 백그라운드(자체 conn) | 리서치 라우터, 키(기업/공고)별 다중 |

공통분모는 "시작→끝, 정규화된 상태, 원본 결과 페이로드"뿐이므로 원본 반환값은 **JSONB로 그대로 저장**하고, 상태만 `ok/failed/skipped`로 정규화한다.

### 단위(파일) 경계

- `backend/app/run_log.py` (신규) — 테이블 접근 + `logged_run` 공통 래퍼 + 상태 정규화 + 조건부 디스코드 알림. 단일 책임: "실행 하나를 감싸 결과를 기록/알림".
- `backend/migrations/versions/0004_run_log.py` (신규) — 스키마.
- `backend/app/routers/runs.py` (신규) — `GET /api/runs` 조회 엔드포인트.
- 기존 수정: `routers/collect.py`, `collect_scheduler.py`(수집기·워커를 `logged_run` 경유), `routers/research.py`(bg 타깃을 로깅 래퍼로), `main.py`(runs 라우터 include).
- `frontend/src/runsApi.ts` (신규) — `/api/runs` 클라이언트 + 타입.
- `frontend/src/pages/Ops.tsx` (수정) — 풋터에 "실행 로그" 카드.
- `frontend/src/index.css` (수정) — 로그 리스트 스타일(기존 Liquid Glass 토큰 재사용).

## 데이터 모델 — `run_log`

```sql
CREATE TABLE run_log (
  id          bigserial PRIMARY KEY,
  pipeline    text        NOT NULL,               -- 'collector' | 'worker' | 'research'
  ref         text        NOT NULL DEFAULT '',    -- research: 'company' 또는 'source:job_id'; 그 외 ''
  label       text        NOT NULL DEFAULT '',    -- 사람이 읽는 이름(기업/공고 제목)
  trigger     text        NOT NULL,               -- 'manual' | 'scheduled'
  status      text        NOT NULL,               -- 'ok' | 'failed' | 'skipped'
  result      jsonb       NOT NULL DEFAULT '{}'::jsonb,  -- 원본 반환값 그대로
  error       text        NOT NULL DEFAULT '',
  started_at  timestamptz NOT NULL,
  finished_at timestamptz NOT NULL DEFAULT now(),
  duration_ms int         NOT NULL DEFAULT 0
);
CREATE INDEX run_log_finished_idx ON run_log (finished_at DESC);
```

**보존 정책:** insert 시 30일 초과 행 정리(`DELETE FROM run_log WHERE finished_at < now() - interval '30 days'`). worker 5분 간격이어도 3만 행 이하 수준 — 인덱스가 있어 무해.

## 기록 방식 — `logged_run`

```python
# backend/app/run_log.py (의사코드)
async def logged_run(conn, *, pipeline, trigger, ref="", label="", clear, run):
    started = datetime.now(timezone.utc)
    try:
        result = await run()                       # 파이프라인 원본 반환
        status = _classify(pipeline, result)       # ok/failed/skipped 정규화
        await _insert(conn, pipeline, ref, label, trigger, status, result, "", started)
        return result
    except Exception as e:
        await _insert(conn, pipeline, ref, label, trigger, "failed", {}, str(e), started)
        raise
    finally:
        clear()                                    # activity.clear(...) 위임
    # (알림) trigger=='scheduled' and 최종 status=='failed' → await push(msg)
```

- **완료된 실행만** 기록(진행 중은 기존 라이브 모니터가 담당). 부분 행 없음.
- `_classify`: collector → `ok`(예외만 `failed`); worker → `skipped_tick` True면 `skipped`, 아니면 `ok`(부분 `failed` 건수는 result에 보존); research → `"done"→ok`, `"cached"→skipped`, `"failed"→failed`.
- **디스코드:** `trigger=='scheduled'` 이고 정규화 status가 `failed`일 때만 `push(...)`. 예: `⚠️ 스케줄 수집 실패 · <error 첫 줄>`. `push`는 웹훅 미설정/실패에 조용히 무시(비차단).

### 붙는 지점

- **collector/worker:** 수동 라우터(`trigger='manual'`)와 스케줄러(`trigger='scheduled'`) 둘 다 `collect()`/`worker_tick()` 호출을 `logged_run`으로 감싼다. `on_stage`(activity.set_stage) 배선과 `clear`는 그대로 유지되고, `clear`를 `logged_run`에 위임한다.
- **research:** `bg.add_task` 타깃을 얇은 로깅 래퍼(`logged_research`)로 교체. 래퍼가 풀에서 conn을 취득하고 `logged_run(pipeline='research', trigger='manual', ref=..., label=...)`으로 `runner.research_*`를 감싼다. **러너 자체는 순수하게 유지**(반환/알림 로직 불변).

## 조회 API — `GET /api/runs`

- 쿼리: `limit`(기본 30, 최대 100), `pipeline`(옵션 필터), `status`(옵션 필터).
- 정렬: `finished_at DESC`.
- 응답: `{ items: RunLogItem[] }`, 각 항목 `{ id, pipeline, ref, label, trigger, status, result, error, started_at, finished_at, duration_ms }`.

## 프론트 — Ops 풋터 "실행 로그" 카드

- 위치: 기존 알림 풋터 영역에 카드 추가(단일 스크롤 대시보드 유지).
- 행 구성: 상대시간 · 파이프라인 라벨(수집기/요약/리서치) · 트리거 뱃지(수동/자동) · 결과 요약 · 소요시간 · 상태 색점.
  - 결과 요약: collector `스크레이핑 N·적재 M` / worker `요약 D건`(+`·실패 F` when failed>0) / worker skipped `건너뜀·LLM 대기` / research `<label> 완료`(cached→`캐시`, failed→`실패`).
  - 상태 색: ok=초록 / skipped=회색 / failed=빨강 — 기존 토큰(`--ok`/무채색/`--danger` 등) 재사용.
- 갱신 트리거(3초 폴링에 매번 붙이지 않음):
  1. 마운트 시 1회.
  2. 수동 실행(`doRun`) 완료 직후.
  3. 라이브 모니터가 **active→idle**로 전환될 때(방금 끝난 실행 반영) — 기존 status 폴링 상태에서 collector/worker 슬롯이 non-null→null이 되는 시점을 감지.

## 테스트

**백엔드**
- `run_log` insert/조회 repo (필드 왕복, 정렬, limit/필터).
- `logged_run`: 성공(ok 기록) / 예외(failed 기록 후 재-raise) / worker skipped_tick(skipped) / research 문자열 매핑.
- 디스코드: `trigger='scheduled'` + failed → push 호출; manual 또는 success → push 미호출(monkeypatch로 검증).
- `GET /api/runs`: 기본/필터/limit.

**프론트**
- 로그 카드 렌더링(세 파이프라인 각 요약 문구), 상태 색 매핑, 빈 상태.
- 갱신 트리거: 수동 실행 후 재조회, active→idle 전환 시 재조회.

## YAGNI (범위 밖)

- SSE / 실시간 스트림(폴링 + 이벤트 재조회로 충분, 훅 지점만 남김).
- 페이지네이션(30건 고정, `limit`만).
- 성공/수동 디스코드 알림, 일일 요약(실패만).
- run_log 화면 내 필터 UI(API는 지원, UI는 v1 제외).
```
