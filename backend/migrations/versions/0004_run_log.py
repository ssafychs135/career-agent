"""run_log 실행 이력

Revision ID: 0004_run_log
Revises: 0003_app_settings
Create Date: 2026-07-23
"""
from alembic import op

revision = "0004_run_log"
down_revision = "0003_app_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS run_log (
          id          bigserial   PRIMARY KEY,
          pipeline    text        NOT NULL,
          ref         text        NOT NULL DEFAULT '',
          label       text        NOT NULL DEFAULT '',
          trigger     text        NOT NULL,
          status      text        NOT NULL,
          result      jsonb       NOT NULL DEFAULT '{}'::jsonb,
          error       text        NOT NULL DEFAULT '',
          started_at  timestamptz NOT NULL,
          finished_at timestamptz NOT NULL DEFAULT now(),
          duration_ms int         NOT NULL DEFAULT 0
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS run_log_finished_idx ON run_log (finished_at DESC);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS run_log;")
