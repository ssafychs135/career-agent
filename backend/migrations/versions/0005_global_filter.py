"""전역 필터 — allowed_regions / hidden_companies

Revision ID: 0005_global_filter
Revises: 0004_run_log
Create Date: 2026-07-23
"""
from alembic import op

revision = "0005_global_filter"
down_revision = "0004_run_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE app_settings
          ADD COLUMN IF NOT EXISTS allowed_regions  text[] NOT NULL DEFAULT '{}'::text[],
          ADD COLUMN IF NOT EXISTS hidden_companies text[] NOT NULL DEFAULT '{}'::text[];
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE app_settings
          DROP COLUMN IF EXISTS allowed_regions,
          DROP COLUMN IF EXISTS hidden_companies;
        """
    )
