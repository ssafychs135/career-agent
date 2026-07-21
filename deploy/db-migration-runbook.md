# DB 소유권 이전 런북 (2026-07-21)

n8n 소유 Postgres(jobs DB, pgvector) → **career-agent 소유 Postgres**로 이전 + n8n 재연결. 단일 소스 확정.

## 방식
- **pg_dump 논리 복원(data-only)** — 원본 무손상, 즉시 롤백. 스키마는 Alembic(0001 베이스라인 + 0002 리서치)이 소유.

## 수행 결과
| 항목 | 값 |
|---|---|
| 이전 jobs | 429 (원본=이전본 일치) |
| 이전 applications | 47 |
| 임베딩 보존 | 429/429 (벡터쿼리 `<=>` 정상) |
| 백업 파일 | `/home/ubuntu/jobs-backup-2026-07-21-1105.dump` (2.3MB, pg_dump -Fc) |
| career-agent DB | `career-agent-postgres-1` (pgvector/pgvector:pg16), jobs_shared 별칭 `postgres` |
| n8n 재연결 | n8n을 jobs_shared에 연결, 구 postgres는 `legacy` 프로파일로 게이트(정지·볼륨 보존) |
| 검증 | n8n→career-agent DB 실접속 jobs=429 확인, /api/db/health `{"ok":true,"jobs_count":429}` |

## 재연결 구조
- n8n 워크플로우 Postgres 자격증명 host=`postgres` → jobs_shared의 career-agent postgres로 해석.
- 자격증명 무변경(career-agent postgres를 n8n과 동일 user/pw로 생성).
- 구 로컬 postgres: `deploy/a1/docker-compose.override.yml`에서 `profiles: ["legacy"]`로 게이트 → `docker compose up -d`가 안 살림(durable). 데이터 볼륨 `./data/postgres` 보존.

## 롤백 (실패 시)
1. 구 postgres 재기동: `cd /home/ubuntu/n8n-pjt && docker compose --profile legacy up -d postgres`
2. n8n override의 jobs_shared 연결·postgres profile 제거(git revert ffb5449) → `cp` override → `docker compose up -d n8n`
3. n8n이 default 네트워크의 구 postgres로 복귀(무손상). 데이터 유실 없음.
4. 최악: 백업 복원 `docker exec -i n8n-pjt-postgres-1 pg_restore -U n8n -d jobs -c /home/ubuntu/jobs-backup-2026-07-21-1105.dump`

## 사후
- career-agent가 jobs DB 소유. 다음 수집 주기에 신규 공고가 career-agent DB로 유입되는지 확인(단일 소스).
- 안정 후 구 postgres 완전 은퇴 판단(정지 유지가 기본, 가역).
