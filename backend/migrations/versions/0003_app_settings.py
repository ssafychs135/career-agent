"""app_settings 싱글턴 + env 시드

Revision ID: 0003_app_settings
Revises: 0002_research
Create Date: 2026-07-22
"""
import os

from alembic import op

revision = "0003_app_settings"
down_revision = "0002_research"
branch_labels = None
depends_on = None


def _pg_text_array(items: list[str]) -> str:
    inner = ", ".join("'" + s.replace("'", "''") + "'" for s in items)
    return "ARRAY[" + inner + "]::text[]" if items else "'{}'::text[]"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
          id                        int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
          keywords                  text[]  NOT NULL,
          allowed_wanted_categories int[]   NOT NULL,
          max_career_years          int     NOT NULL,
          max_pages                 int     NOT NULL,
          collect_hour              int     NOT NULL,
          batch_size                int     NOT NULL,
          model                     text    NOT NULL,
          summary_backend           text    NOT NULL CHECK (summary_backend IN ('local','claude')),
          max_attempts              int     NOT NULL,
          worker_interval_min       int     NOT NULL,
          enabled                   boolean NOT NULL DEFAULT false,
          discord_webhook_url       text    NOT NULL DEFAULT '',
          updated_at                timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    keywords = [k.strip() for k in os.environ.get("SEARCH_KEYWORDS", "").split(",") if k.strip()]
    if not keywords:
        raise RuntimeError("SEARCH_KEYWORDS must be set with at least one keyword to seed app_settings")
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").replace("'", "''")
    op.execute(
        f"""
        INSERT INTO app_settings
          (id, keywords, allowed_wanted_categories, max_career_years, max_pages,
           collect_hour, batch_size, model, summary_backend, max_attempts,
           worker_interval_min, enabled, discord_webhook_url)
        VALUES
          (1, {_pg_text_array(keywords)}, ARRAY[518,507]::int[], 2, 9999,
           9, 20, 'kanana-1.5-8b-instruct-2505-mlx', 'local', 5,
           5, false, '{webhook}')
        ON CONFLICT (id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app_settings;")
