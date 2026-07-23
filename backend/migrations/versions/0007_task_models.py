"""작업별 claude 모델 티어 오버라이드

Revision ID: 0007_task_models
Revises: 0006_notify_enabled
Create Date: 2026-07-24
"""
from alembic import op

revision = "0007_task_models"
down_revision = "0006_notify_enabled"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE app_settings "
        "ADD COLUMN IF NOT EXISTS summary_model text NOT NULL DEFAULT '', "
        "ADD COLUMN IF NOT EXISTS research_model text NOT NULL DEFAULT '';"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE app_settings "
        "DROP COLUMN IF EXISTS summary_model, "
        "DROP COLUMN IF EXISTS research_model;"
    )
