#!/bin/bash
# career-agent Postgres 최초 기동 시 읽기전용 롤 생성(스키마는 Alembic이 소유).
# n8n-pjt/db/roles.sh 재현. 비밀번호는 env(JOBS_RO_PASSWORD), 하드코딩 금지.
set -e
: "${JOBS_RO_PASSWORD:?JOBS_RO_PASSWORD is required}"
psql -v ON_ERROR_STOP=1 -v ro_pw="${JOBS_RO_PASSWORD}" \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-'EOSQL'
  DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='jobs_ro') THEN
      CREATE ROLE jobs_ro LOGIN;
    END IF;
  END $$;
  ALTER ROLE jobs_ro WITH PASSWORD :'ro_pw';
EOSQL
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -c "GRANT CONNECT ON DATABASE \"$POSTGRES_DB\" TO jobs_ro;" \
  -c "GRANT USAGE ON SCHEMA public TO jobs_ro;"
