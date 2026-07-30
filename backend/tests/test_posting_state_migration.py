from pathlib import Path

DDL = (Path(__file__).resolve().parents[1]
       / "migrations" / "versions" / "0008_posting_state.py").read_text()


def test_columns_and_default():
    # 기본값 'open'이라야 배포 직후 기존 공고가 전부 그대로 보인다(동작 불변).
    assert "posting_state text NOT NULL DEFAULT 'open'" in DDL
    assert "state_checked_at timestamptz" in DDL


def test_index_present():
    assert "idx_jobs_posting_state" in DDL


def test_revision_chain():
    assert 'revision = "0008_posting_state"' in DDL
    assert 'down_revision = "0007_task_models"' in DDL


def test_downgrade_drops_both_columns():
    down = DDL.split("def downgrade")[1]
    assert "posting_state" in down and "state_checked_at" in down
