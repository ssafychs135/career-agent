"""baseline: 기존 n8n jobs·applications 스키마 흡수 (init.sql 1:1)

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-21
"""
from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN EXECUTE format("
        "'ALTER DATABASE %I SET timezone TO ''Asia/Seoul''', current_database()); END $$;"
    )
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
          id            BIGSERIAL PRIMARY KEY,
          source        TEXT        NOT NULL,
          job_id        TEXT        NOT NULL,
          company       TEXT,
          title         TEXT,
          url           TEXT,
          min_career    INT,
          max_career    INT,
          tech_stacks   TEXT[],
          locations     TEXT,
          summary       TEXT,
          status        TEXT        NOT NULL DEFAULT 'pending',
          attempts      INT         NOT NULL DEFAULT 0,
          notified_at   TIMESTAMPTZ,
          closed_at     TIMESTAMPTZ,
          collected_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
          embedding     vector(1024),
          UNIQUE (source, job_id)
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status       ON jobs (status);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_jobs_collected_at ON jobs (collected_at);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_jobs_source       ON jobs (source);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_jobs_notify       ON jobs (status, notified_at);")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_embedding "
        "ON jobs USING hnsw (embedding vector_cosine_ops);"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS applications (
          id            BIGSERIAL PRIMARY KEY,
          message_id    TEXT UNIQUE,
          company       TEXT,
          status        TEXT,
          email_subject TEXT,
          email_from    TEXT,
          summary       TEXT,
          received_at   TIMESTAMPTZ,
          notified_at   TIMESTAMPTZ,
          created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);")
    # jobs_ro 롤은 initdb(db/01-roles.sh)가 먼저 생성 → 존재할 때만 grant(로컬 단독 테스트 안전).
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='jobs_ro') THEN "
        "GRANT SELECT ON jobs TO jobs_ro; GRANT SELECT ON applications TO jobs_ro; END IF; END $$;"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS applications;")
    op.execute("DROP TABLE IF EXISTS jobs;")
