import pytest
from app.research.parse import parse_research_json


def test_parses_plain_json():
    assert parse_research_json('{"a": 1}') == {"a": 1}


def test_parses_fenced_json():
    text = '```json\n{"overview": "x", "sources": ["u"]}\n```'
    assert parse_research_json(text) == {"overview": "x", "sources": ["u"]}


def test_parses_json_with_prose_prefix():
    text = '아래는 결과입니다:\n{"role_detail": "y"}\n감사합니다'
    assert parse_research_json(text) == {"role_detail": "y"}


def test_raises_when_no_object():
    with pytest.raises(ValueError):
        parse_research_json("no json here")
