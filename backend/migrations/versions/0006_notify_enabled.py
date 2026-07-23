"""알림 발송 마스터 스위치

Revision ID: 0006_notify_enabled
Revises: 0005_global_filter
Create Date: 2026-07-23
"""
from alembic import op

revision = "0006_notify_enabled"
down_revision = "0005_global_filter"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE app_settings "
        "ADD COLUMN IF NOT EXISTS notify_enabled boolean NOT NULL DEFAULT false;"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE app_settings DROP COLUMN IF EXISTS notify_enabled;")
