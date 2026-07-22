from app.collect.detail import detail_url, parse_detail


def test_detail_url_by_source():
    assert detail_url("jumpit", "5") == "https://jumpit-api.saramin.co.kr/api/position/5"
    assert "wanted.co.kr/api/chaos/jobs/v4/9/details" in detail_url("wanted", "9")


def test_parse_detail_jumpit():
    payload = {"result": {"responsibility": "일", "qualifications": "요건", "preferredRequirements": "우대"}}
    text = parse_detail("jumpit", payload)
    assert "[주요업무]" in text and "일" in text and "요건" in text and "우대" in text


def test_parse_detail_wanted():
    payload = {"data": {"job": {"detail": {"main_tasks": "업무", "requirements": "자격", "preferred_points": "가점"}}}}
    text = parse_detail("wanted", payload)
    assert "업무" in text and "자격" in text and "가점" in text


def test_parse_detail_failure_returns_none():
    assert parse_detail("wanted", {"nope": 1}) is None
