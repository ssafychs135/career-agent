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
    assert "$1" in sql and "$14" in sql  # 14개 편집 컬럼
    assert params[0] == ["x"]            # keywords 배열 그대로(asyncpg text[])
    assert params[1] == [518, 507]


def test_settings_defaults_include_empty_global_filters():
    from app.settings_repo import Settings, SETTINGS_DEFAULTS
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"]))
    assert s.allowed_regions == []
    assert s.hidden_companies == []


def test_upsert_includes_global_filter_columns():
    from app.settings_repo import Settings, SETTINGS_DEFAULTS, build_upsert
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"],
                        allowed_regions=["서울", "경기"], hidden_companies=["미스릴"]))
    sql, params = build_upsert(s)
    assert "allowed_regions" in sql and "hidden_companies" in sql
    assert ["서울", "경기"] in params
    assert ["미스릴"] in params


def test_notify_enabled_defaults_false_and_is_persisted():
    from app.settings_repo import Settings, SETTINGS_DEFAULTS, build_upsert
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"]))
    assert s.notify_enabled is False
    sql, params = build_upsert(Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], notify_enabled=True)))
    assert "notify_enabled" in sql
    assert True in params


def test_task_models_default_to_empty():
    from app.settings_repo import Settings, SETTINGS_DEFAULTS
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"]))
    assert s.summary_model == ""
    assert s.research_model == ""


def test_task_models_accept_ladder_aliases():
    from app.settings_repo import Settings, SETTINGS_DEFAULTS
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"],
                        summary_model="haiku", research_model="opus"))
    assert s.summary_model == "haiku"
    assert s.research_model == "opus"


def test_task_models_reject_unknown_alias():
    """오타를 저장 시점에 막는다 — 안 막으면 배포 후 첫 실행에서 프로세스 실패로 드러난다."""
    from app.settings_repo import Settings, SETTINGS_DEFAULTS
    with pytest.raises(ValidationError):
        Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], summary_model="gpt-4"))
    with pytest.raises(ValidationError):
        Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], research_model="claude-opus-4-8"))


def test_task_models_normalize_blank_to_empty():
    from app.settings_repo import Settings, SETTINGS_DEFAULTS
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], research_model="   "))
    assert s.research_model == ""


def test_upsert_includes_task_model_columns():
    from app.settings_repo import Settings, SETTINGS_DEFAULTS, build_upsert
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"],
                        summary_model="sonnet", research_model="opus"))
    sql, params = build_upsert(s)
    assert "summary_model" in sql and "research_model" in sql
    assert params[-2] == "sonnet"
    assert params[-1] == "opus"


def test_migration_defaults_match_settings_defaults():
    """DDL의 DEFAULT와 SETTINGS_DEFAULTS가 어긋나면 배포 직후 동작이 조용히 바뀐다."""
    from pathlib import Path
    from app.settings_repo import SETTINGS_DEFAULTS
    ddl = (Path(__file__).resolve().parents[1]
           / "migrations" / "versions" / "0007_task_models.py").read_text()
    assert "summary_model text NOT NULL DEFAULT ''" in ddl
    assert "research_model text NOT NULL DEFAULT ''" in ddl
    assert SETTINGS_DEFAULTS["summary_model"] == ""
    assert SETTINGS_DEFAULTS["research_model"] == ""
