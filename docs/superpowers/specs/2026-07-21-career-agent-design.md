# career-agent — 설계 문서 (Design Spec)

**작성일:** 2026-07-21
**상태:** 승인 대기(사용자 리뷰)

## 북극성 (North Star)

n8n으로 운영 중인 취업 자동화 시스템을, **독립 프론트엔드 + 백엔드로 분리된 웹서비스** `career-agent`로 점진적으로 이관한다. 최종적으로 n8n의 모든 기능을 웹서비스가 흡수한다.

- **이관 방식:** Strangler Fig 패턴 — 새 웹서비스를 n8n **옆에** 세우고 기능을 하나씩 이관. 이관된 n8n 워크플로우는 **비활성화(active=false)만** 하고 삭제하지 않는다(가역적). 마지막 기능까지 이관돼도 n8n 인스턴스 자체는 존치.
- **인프라 공유:** 코드는 새 레포로 완전 분리하되, A1 서버·Postgres(jobs DB)·Cloudflare 터널·Discord 웹훅은 **공유**한다. 전환기 동안 새 백엔드와 n8n이 같은 `jobs` DB를 공유하는 것이 통합 지점.

## 이 스펙의 범위 (Scope of THIS spec)

**기반 아키텍처(독립 프론트+백엔드) + 첫 기능 슬라이스: 공고 조회 + 기업/공고 리서치.**
이 슬라이스는 n8n의 **09 DB 뷰어를 대체**한다(09는 비활성화).

**범위 밖(이후 별도 스펙):** 검색(04)·알림(03)·수집/요약(01·02)·메일(07)·리포트(08)의 이관. 이번엔 기반을 깔고 리서치 기능으로 검증만 한다.

## 용어

- **기업 리서치(①):** 회사 단위. 개요 + 안정성. `company` 키로 1회 캐시.
- **공고 리서치(②):** 공고 단위. 기술스택·개발문화 상세 + 직무 상세. `(source, job_id)` 키로 1회 캐시. ①(기업 개요)을 컨텍스트로 재사용.
- 두 리서치 모두 DB 캐시. 같은 키는 재리서치 스킵, **명시적 강제(force)** 재리서치 가능.

## 아키텍처

```
              Cloudflare (agent.chs135.com, Google Access)
                            │
                     a1-cloudflared 터널 → localhost:80
                            │
   ┌──────────── career-agent docker compose (Jenkins CI/CD) ──────────┐
   │  nginx :80 ─ /   → frontend(정적, 컨테이너)                        │
   │            ─ /api → backend (FastAPI + claude, uvicorn :8000)      │
   │                     │  └ ~/.claude 마운트(구독인증)                 │
   │                     ▼                                              │
   │              Postgres (pgvector, **career-agent 소유**)  ◄─────────┼── n8n(재연결)
   └─────────────────────┼──────────────────────────────────────────────┘
                  ┌───────┴──────┐
             claude -p        Discord 웹훅
          (컨테이너 내부)
```

**DB는 career-agent가 소유하고 n8n은 여기에 재연결**한다(공유 → 소유권 이전). 기존 jobs 데이터를 career-agent의 Postgres로 이전하고, n8n의 DB 접속을 이 Postgres로 바꿔 **단일 소스**를 유지한다(전환기 갈라짐 방지). 상세는 아래 "DB 마이그레이션".

**리버스 프록시 = nginx.** 두 트리거(백그라운드 워커 등 **다중 백엔드 서비스** + **프론트 독립 배포**)가 곧 오므로 기반부터 nginx를 둔다. cloudflared 터널이 `localhost:80`(nginx)로 들어오고, nginx가 `/`=프론트 정적, `/api/*`=백엔드로 경로 라우팅. 이관으로 서비스가 늘면 `/api/search`→search 서비스처럼 nginx에 라우트만 추가. (TLS·WAF·레이트리밋은 Cloudflare 엣지가 처리하므로 nginx는 순수 라우팅/정적 서빙 담당. nginx는 취준 시장가치도 고려한 선택.)

**컴포넌트 (전부 A1, n8n 밖):**

| 컴포넌트 | 형태 | 책임 | 의존 |
|---|---|---|---|
| nginx (RP) | **컨테이너** | cloudflared 진입점(:80), `/`→프론트 정적·`/api/*`→백엔드 경로 라우팅 | frontend dist, backend |
| backend | **컨테이너** FastAPI + claude-code(uvicorn :8000) | API 제공, 리서치 오케스트레이션(claude -p 호출), DB 접근, Discord 푸시 | Postgres, claude(구독인증), Discord |
| frontend | **컨테이너**(또는 nginx가 서빙할 정적 dist) React + Vite + TS | 공고 조회·필터·리서치 열람/트리거 UI | backend API(HTTP) |
| research runner | 백엔드 내부 모듈(비동기 BackgroundTask) | claude -p 서브프로세스 호출·파싱·저장 | claude, DB |
| DB | **career-agent 소유** Postgres(pgvector) 컨테이너 | jobs·research 전체 스키마·마이그레이션 소유. n8n도 여기 재연결 | — |

**전면 컨테이너화 + Jenkins/Docker 배포:** A1엔 이미 Jenkins + Docker 스택이 있으므로(n8n·postgres 컨테이너, Jenkins `docker compose up -d` CI/CD), career-agent도 **docker compose로 통일**한다. 호스트 systemd 예외를 두지 않아 스택이 일관되고, **기존 Jenkins 파이프라인을 재사용**한다(빌드·테스트·배포 자동화, 포트폴리오 가치).

**claude 인증 = 구독(과금 0), 컨테이너에서 마운트로 사용:** 유료 API를 쓸 수 없으므로 구독 인증을 쓴다. 백엔드 이미지에 `npm i -g @anthropic-ai/claude-code`로 claude를 설치하고, 호스트의 `~/.claude`(+`~/.claude.json`)를 **rw로 마운트**하며 컨테이너를 **ubuntu와 동일 uid**로 실행한다. 이러면 컨테이너 안 claude가 토큰을 갱신해도 호스트 원본에 반영돼 동기화가 유지된다. 유일한 제약: 토큰 완전 만료 시 **대화형 재로그인은 호스트에서 `claude login` 1회**(공유 마운트라 전파). 별도 워커·큐로 분리하지 않고 백엔드가 직접 claude -p를 비동기 호출한다.

**프론트·백 독립 배포:** 프론트(정적 빌드)와 백엔드(컨테이너)는 각각 독립 빌드·배포되고 nginx가 앞에서 합친다. 프론트만 재배포해도 백엔드 무중단, 반대도 동일. 향후 백엔드가 여러 서비스로 쪼개지면 nginx 라우트만 추가.

## 데이터 모델

career-agent가 **전체 스키마를 소유**한다(마이그레이션 = career-agent 레포). 이전 시점의 기존 `jobs` 스키마를 **그대로 채택**(n8n 워크플로우가 계속 의존하므로 컬럼·제약 보존)하고, 그 위에 리서치 2테이블을 추가한다. `jobs`의 `UNIQUE(source, job_id)`를 FK로 활용.

```sql
-- ① 기업 리서치 (회사당 1회)
CREATE TABLE company_research (
  company        text PRIMARY KEY,        -- jobs.company와 조인
  overview       text,                    -- 기업 개요(사업·제품·규모)
  stability      text,                    -- 안정성(투자단계·재무·업력 서술)
  data           jsonb,                   -- claude 구조화 출력 원본(확장 필드용)
  sources        jsonb,                   -- 인용 URL 배열
  model          text,                    -- 사용 모델(claude-...)
  status         text DEFAULT 'done',     -- running / done / failed
  researched_at  timestamptz DEFAULT now()
);

-- ② 공고+기업 리서치 (공고당 1회)
CREATE TABLE job_research (
  source         text,
  job_id         text,
  company        text,                    -- 조인·표시 편의
  tech_detail    text,                    -- 기술스택·개발문화 상세
  role_detail    text,                    -- 직무 상세·기대수준
  data           jsonb,
  sources        jsonb,
  model          text,
  status         text DEFAULT 'done',     -- running / done / failed
  researched_at  timestamptz DEFAULT now(),
  PRIMARY KEY (source, job_id),
  FOREIGN KEY (source, job_id) REFERENCES jobs(source, job_id) ON DELETE CASCADE
);
```

- **테이블 존재 = 캐시 = 큐 상태.** 러너는 `LEFT JOIN`으로 "리서치 없는 done 공고/기업"을 찾는다. 별도 큐 컬럼 불필요.
- `data jsonb`에 claude 전체 구조화 출력 보관 → 나중 필드 추가(평판·면접대비)에도 스키마 변경 없이 흡수.
- `sources`로 인용 출처 저장 → 뷰어/Discord "근거 링크" 표시, 환각 검증.
- `status='failed'` 저장 → 실패분 재시도(성공분 스킵). 트리거 직후 `running` 표기로 프론트 폴링.
- 스키마는 career-agent 마이그레이션(예: `backend/migrations/`, Alembic 등)이 소유. 기존 jobs 스키마를 베이스라인으로 흡수 + research 테이블을 신규 마이그레이션으로 추가. 읽기전용 롤(`jobs_ro`)에 두 테이블 SELECT 부여.

## DB 마이그레이션 (공유 → career-agent 소유, n8n 재연결)

목표: 기존 n8n Postgres(`jobs` DB, pgvector)를 **career-agent 소유 Postgres로 이전**하고 n8n을 재연결해 단일 소스 유지. 이전 대상은 **도메인 데이터(Postgres)**뿐 — n8n 내부 상태(SQLite: 워크플로우·자격증명·실행이력)는 n8n에 그대로 둔다.

**절차(짧은 컷오버 창):**
1. **쓰기 정지:** n8n 수집·요약(01·02) 등 쓰기 워크플로우 잠시 비활성화(정합성 확보).
2. **데이터 이전:** 기존 Postgres → career-agent Postgres. 두 방식 중 택1(구현 계획에서 확정):
   - (a) **볼륨 이관**: 기존 `data/postgres` 볼륨을 career-agent Postgres가 사용(최소 변경·무손실).
   - (b) **pg_dump/restore**: 논리 덤프 후 새 인스턴스에 복원(깨끗한 분리). *pgvector 확장·`vector` 컬럼·HNSW 인덱스, 읽기전용 롤(roles.sh)까지 재현할 것.*
3. **n8n 재연결:** n8n의 `DB_POSTGRESDB_HOST`(및 네트워크)를 career-agent Postgres로 변경 후 재시작. 네트워킹은 공유 external 도커 네트워크 또는 `host:5432`(구현 계획에서 확정).
4. **검증:** 행 수·주요 테이블 카운트 일치, n8n 워크플로우 정상, career-agent 조회 정상, 임베딩/벡터쿼리 정상.
5. **재개:** n8n 워크플로우 재활성화. 신규 수집이 새 DB에 들어오는지 확인.
6. **정리:** 기존 Postgres 컨테이너 은퇴(볼륨 이관 방식이면 정의만 제거).

**롤백:** 컷오버 실패 시 n8n `DB_POSTGRESDB_HOST`를 원복하고 워크플로우 재활성화. (b) 방식이면 원본 무손상이라 즉시 복귀 가능. 백업(pg_dump)을 컷오버 전 필수 확보.

## 리서치 실행 (claude -p)

**방식:** 백엔드 **컨테이너 안에서** `claude -p`를 서브프로세스로 호출. claude-code는 이미지에 설치(`npm i -g @anthropic-ai/claude-code`), 구독 인증은 마운트된 `~/.claude`로 사용(호스트에서 이미 인증됨: v2.1.216). 비동기 BackgroundTask로 실행.

```bash
claude -p "<프롬프트>" \
  --output-format json \
  --allowedTools "WebSearch,WebFetch"
```

- `--output-format json`: JSON 엔벨로프로 응답(result 필드에 모델 출력)
- `--allowedTools WebSearch,WebFetch`: 웹검색·페치만 허용(비대화형 권한 프롬프트 없이). 파일쓰기·bash 등 불허 → A1 안전
- 프롬프트에서 **"오직 JSON 객체만 출력"** 지시 → result를 파싱해 DB 저장. 파싱 실패 시 1회 재시도 후 `failed`.

**① 기업 리서치 프롬프트(개요·안정성):**
```
너는 취업 리서처다. 아래 회사를 웹검색으로 조사해 JSON만 출력하라.
회사명: {company}   (참고 공고 URL: {url})
{
  "overview":  "사업·주력제품·규모 4~6문장",
  "stability": "설립연도·투자단계/누적투자·매출/흑자여부·최근 동향 등 재무·안정성 근거 4~6문장. 불확실하면 '확인 안 됨' 명시",
  "sources":   ["실제 참고한 URL", ...]
}
근거 없는 추측 금지. 한국 스타트업은 정보가 적을 수 있으니 모르면 모른다고 하라.
```

**② 공고+기업 리서치 프롬프트(기술·직무):** ①결과를 컨텍스트로 주입
```
회사 개요(기존 리서치): {company_overview}
공고: {title} / 기술스택(수집): {tech_stacks} / 요약: {summary} / URL: {url}
위 공고를 조사해 JSON만 출력하라.
{
  "tech_detail": "실제 사용 기술스택·아키텍처·개발문화 근거와 함께 4~6문장",
  "role_detail": "담당 업무·기대 경력/역량·성장경로 4~6문장",
  "sources": [...]
}
```

- **웹검색 필수:** 소형 한국 스타트업은 학습데이터에 거의 없어 웹검색이 리서치 품질의 핵심. claude -p(에이전트+웹)를 쓰는 이유.
- **비용/레이트리밋 통제:** 구독 인증이므로 배치 `--limit N`·동시성 상한으로 보호. 캐싱(회사/공고당 1회)이 1차 방어.

## 백엔드 API (첫 슬라이스)

- `GET /api/jobs` — 필터(status·source·location·tech·keyword) + 페이지네이션. 각 공고에 리서치 존재/상태 플래그 포함.
- `GET /api/jobs/{source}/{job_id}` — 공고 + `job_research` + `company_research` 합본.
- `POST /api/research/company` — 기업 리서치 트리거(비동기). body: `{company, force?}`.
- `POST /api/research/job` — 공고 리서치 트리거(비동기, 기업 리서치 자동 선행). body: `{source, job_id, force?}`.

**비동기 실행:** 리서치는 10~60초 소요. 트리거 시 리서치행을 `status='running'`으로 insert/upsert → FastAPI BackgroundTask 시작 → 즉시 202 응답. 프론트가 `GET /api/jobs/...`로 폴링해 `running→done` 확인. 완료 시 Discord 푸시.

**관리용 CLI(선택, 잔존):** `python -m app.research --company X | --job source:id | --pending-companies | --pending-jobs [--limit N] [--force]`. 동일 러너 모듈 재사용. 자동모드 없이 수동만.

**자동모드(비활성):** APScheduler 잡(미리서치 대상 주기 처리) 구현하되 **설정 플래그로 꺼둠**. 지금은 프론트 버튼/CLI 수동만.

## 프론트엔드 (React/Vite/TS)

- **공고 리스트:** 카드/테이블, 필터(상태·소스·지역·기술·keyword — 09 뷰어 기능 계승), 페이지네이션, "리서치 완료만" 토글.
- **공고 상세:** 공고 정보 + 🔍 기업 리서치(개요·안정성) + 공고 리서치(기술·직무) + 근거 링크. 리서치 없으면 **"리서치" 버튼** → `POST /api/research/job` → "리서치 중…" 스피너(폴링) → 완료 시 표시.
- API 클라이언트만 백엔드와 통신(완전 분리). 정적 빌드(dist) → **nginx가 서빙, 독립 배포**.

## 배포 토폴로지

**전면 docker compose, Jenkins CI/CD로 배포**(기존 A1 Jenkins+Docker 스택 재사용).

- **호스트네임:** `agent.chs135.com` (Cloudflare 터널 라우트 추가, **Google Access** 뒤). cloudflared → `localhost:80`(nginx 컨테이너). `/api`도 Access 뒤.
- **nginx(컨테이너):** cloudflared 진입점(:80). `/`=프론트 정적 서빙, `/api/*`=`proxy_pass` → backend:8000. 서비스 추가 시 `location /api/<svc>` 블록만 추가.
- **backend(컨테이너):** FastAPI+claude-code(uvicorn :8000). 이미지에 `npm i -g @anthropic-ai/claude-code`. **마운트:** 호스트 `~/.claude`·`~/.claude.json`를 `rw`로, **컨테이너 uid=ubuntu(예: 1000)**로 실행 → 구독 인증·토큰갱신 동기화. Postgres·Discord 접근. 독립 배포.
- **frontend(컨테이너/정적):** Vite 빌드(dist) → nginx가 서빙. 독립 배포(빌드 산출물만 교체, 백엔드 무중단). *터널 구조상 프론트는 A1 nginx가 서빙; 향후 Cloudflare Pages로 옮기려면 `/api` 라우팅 재구성 필요(지금 안 함).*
- **Postgres(career-agent 소유):** career-agent compose가 pgvector Postgres를 소유. 기존 데이터 이전 후 n8n을 여기로 재연결(위 "DB 마이그레이션"). n8n은 공유 external 도커 네트워크 또는 host:5432로 접속.
- **CI/CD (Jenkins):** career-agent용 파이프라인 — 이미지 빌드 → 테스트(백/프론트) → `docker compose up -d` 배포 → 스모크. 기존 n8n 파이프라인과 동일 패턴(docker.sock, 경로동일 마운트) 재사용. 상세 파이프라인 구성은 구현 계획에서.

## 보안 · 에러 · 테스트

- **보안:** Cloudflare 터널 + Google Access(기존 패턴 재사용). 리서치 트리거는 인증 사용자만. claude는 `--allowedTools`로 웹툴만 허용 → 파일·시스템 접근 차단.
- **에러:** claude -p 실패/타임아웃 → 리서치행 `status='failed'`, 다른 건 안 막음, 재시도(수동/자동). JSON 파싱 실패 1회 재시도 후 failed. 배치 `--limit`·동시성 상한으로 구독 레이트리밋 보호.
- **테스트:** 백엔드 — DB 접근·캐시스킵·claude 출력 파싱·API 라우트(claude mock). 프론트 — 컴포넌트·API 클라이언트. 통합 — A1에서 실제 1건 E2E.

## n8n 공존/이관

- 이 프론트가 **09 DB 뷰어를 대체** → n8n **09 워크플로우 비활성화**(active=false, 삭제 아님).
- **DB 소유권이 career-agent로 이전**되고 n8n은 career-agent Postgres에 재연결됨(위 마이그레이션). 나머지 n8n 워크플로우(01~08)는 그 DB를 쓰며 계속 운영.
- 이후 스펙에서 검색·알림·수집 등을 백엔드로 하나씩 이관하며 해당 WF 비활성화. 모두 이관되면 n8n은 DB를 안 쓰고 인스턴스만 존치.

## 미해결/이후 결정

- Jenkins 파이프라인 세부 구성(단계·스모크·기존 n8n job과의 공존) — 구현 계획에서 확정.
- 자동모드 활성화 시점·주기.
- 리서치 확장 필드(평판·뉴스·면접대비) — `data jsonb`로 무중단 흡수 가능.
- 다중 백엔드 서비스 분리(수집·검색 등 이관) 시점 — 이후 스펙.
