"""research: company_research·job_research + jobs_ro SELECT

Revision ID: 0002_research
Revises: 0001_baseline
Create Date: 2026-07-21
"""
from alembic import op

revision = "0002_research"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS company_research (
          company        text PRIMARY KEY,
          overview       text,
          stability      text,
          data           jsonb,
          sources        jsonb,
          model          text,
          status         text DEFAULT 'done',
          researched_at  timestamptz DEFAULT now()
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS job_research (
          source         text,
          job_id         text,
          company        text,
          tech_detail    text,
          role_detail    text,
          data           jsonb,
          sources        jsonb,
          model          text,
          status         text DEFAULT 'done',
          researched_at  timestamptz DEFAULT now(),
          PRIMARY KEY (source, job_id),
          FOREIGN KEY (source, job_id) REFERENCES jobs(source, job_id) ON DELETE CASCADE
        );
        """
    )
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='jobs_ro') THEN "
        "GRANT SELECT ON company_research TO jobs_ro; "
        "GRANT SELECT ON job_research TO jobs_ro; END IF; END $$;"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS job_research;")
    op.execute("DROP TABLE IF EXISTS company_research;")
