import pytest
from pydantic import ValidationError
from app.settings_repo import Settings, SETTINGS_DEFAULTS, build_upsert


def _valid(**over):
    base = dict(
        keywords=["백엔드", "데이터 엔지니어"], allowed_wanted_categories=[518, 507],
        max_career_years=2, max_pages=9999, collect_hour=9, batch_size=20,
        model="kanana-1.5-8b-instruct-2505-mlx", summary_backend="local",
        max_attempts=5, worker_interval_min=5, enabled=False, discord_webhook_url="",
    )
    base.update(over)
    return base


def test_defaults_are_valid():
    Settings(**SETTINGS_DEFAULTS)  # 검증 통과


def test_keywords_trimmed_and_nonempty():
    s = Settings(**_valid(keywords=["  백엔드 ", "", "  "]))
    assert s.keywords == ["백엔드"]


def test_keywords_all_empty_rejected():
    with pytest.raises(ValidationError):
        Settings(**_valid(keywords=["", "   "]))


def test_collect_hour_range():
    with pytest.raises(ValidationError):
        Settings(**_valid(collect_hour=24))


def test_summary_backend_enum():
    with pytest.raises(ValidationError):
        Settings(**_valid(summary_backend="gpt"))


def test_batch_size_bounds():
    with pytest.raises(ValidationError):
        Settings(**_valid(batch_size=0))
    with pytest.raises(ValidationError):
        Settings(**_valid(batch_size=101))


def test_build_upsert_is_singleton_and_parameterized():
    sql, params = build_upsert(Settings(**_valid(keywords=["x"])))
    assert "INSERT INTO app_settings" in sql
    assert "id" in sql and "ON CONFLICT (id) DO UPDATE SET" in sql
    assert "$1" in sql and "$12" in sql  # 12개 편집 컬럼
    assert params[0] == ["x"]            # keywords 배열 그대로(asyncpg text[])
    assert params[1] == [518, 507]
