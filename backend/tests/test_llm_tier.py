import pytest
from app.llm_tier import LADDER, TASK_MODEL, escalate, resolve


def test_ladder_is_ordered_cheap_to_capable():
    assert LADDER == ("haiku", "sonnet", "opus")


def test_task_defaults():
    assert TASK_MODEL == {"summary": "haiku", "research": "sonnet"}


def test_escalate_steps_up_one_rung():
    assert escalate("haiku") == "sonnet"
    assert escalate("sonnet") == "opus"


def test_escalate_caps_at_top():
    """상한에서 예외를 던지면 opus로 고정한 사용자의 재시도가 크래시한다."""
    assert escalate("opus") == "opus"


def test_escalate_passes_through_values_off_the_ladder():
    assert escalate("gpt-4") == "gpt-4"
    assert escalate("") == ""


def test_resolve_uses_task_default_when_no_override():
    assert resolve("summary") == "haiku"
    assert resolve("research") == "sonnet"


def test_resolve_override_wins():
    assert resolve("summary", "opus") == "opus"


def test_resolve_blank_override_falls_back_to_default():
    assert resolve("summary", "   ") == "haiku"
    assert resolve("research", "") == "sonnet"


def test_resolve_escalated_steps_up_from_the_resolved_value():
    assert resolve("summary", escalated=True) == "sonnet"
    assert resolve("research", escalated=True) == "opus"
    assert resolve("summary", "sonnet", escalated=True) == "opus"
    assert resolve("research", "opus", escalated=True) == "opus"


def test_resolve_unknown_task_raises():
    """오타난 작업명을 조용히 기본 티어로 넘기지 않는다."""
    with pytest.raises(KeyError):
        resolve("mailcheck")
