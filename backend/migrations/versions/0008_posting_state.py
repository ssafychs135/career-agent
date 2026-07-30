"""공고 생존 상태(마감·삭제) 기록

Revision ID: 0008_posting_state
Revises: 0007_task_models
Create Date: 2026-07-30
"""
from alembic import op

revision = "0008_posting_state"
down_revision = "0007_task_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 기본값 'open' — 기존 행은 전부 살아있는 것으로 두고, 첫 재검증이 판정한다.
    op.execute(
        "ALTER TABLE jobs "
        "ADD COLUMN IF NOT EXISTS posting_state text NOT NULL DEFAULT 'open', "
        "ADD COLUMN IF NOT EXISTS state_checked_at timestamptz;"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_posting_state "
        "ON jobs (posting_state, state_checked_at);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_jobs_posting_state;")
    op.execute(
        "ALTER TABLE jobs "
        "DROP COLUMN IF EXISTS posting_state, "
        "DROP COLUMN IF EXISTS state_checked_at;"
    )
