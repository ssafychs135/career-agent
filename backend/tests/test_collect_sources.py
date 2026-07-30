from app.collect.sources.common import title_hit, career_ok, strip_tags
from app.collect.sources.jumpit import parse_jumpit_positions
from app.collect.sources.wanted import parse_wanted_results, wanted_list_url


def test_title_hit_word_boundary():
    assert title_hit("백엔드 개발자", ["백엔드"]) is True
    assert title_hit("백엔드개발자", ["백엔드"]) is True   # 한글은 인접문자가 경계 → n8n 원본 동작(포함)
    assert title_hit("Backend Engineer", ["backend"]) is True  # 대소문자 무시
    assert title_hit("backends", ["backend"]) is False         # 영문은 단어경계 유지(붙으면 제외)


def test_career_ok():
    assert career_ok(1, 2) is True
    assert career_ok(3, 2) is False
    assert career_ok(None, 2) is True          # min 없음 → 통과
    assert career_ok(5, float("nan")) is True   # max 없음 → 통과


def test_strip_tags():
    assert strip_tags("<b>Py</b>thon ") == "Python"


def test_parse_jumpit_filters_and_normalizes():
    payload = {"result": {"positions": [
        {"id": 1, "title": "백엔드 개발자", "companyName": "A", "minCareer": 1,
         "maxCareer": 3, "techStacks": ["Python", {"stack": "Django"}], "locations": ["서울"]},
        {"id": 2, "title": "프론트 개발자", "companyName": "B", "minCareer": 0},  # 키워드 불일치
        {"id": 3, "title": "백엔드 시니어", "companyName": "C", "minCareer": 5},  # 연차 초과
    ]}}
    out = parse_jumpit_positions(payload, ["백엔드"], 2)
    assert len(out) == 1
    r = out[0]
    assert r["source"] == "jumpit" and r["job_id"] == "1" and r["company"] == "A"
    assert r["url"] == "https://jumpit.saramin.co.kr/position/1"
    assert r["tech_stacks"] == ["Python", "Django"]
    assert r["locations"] == "서울"


def test_parse_wanted_filters_by_category_and_title():
    payload = {"data": [
        {"id": 10, "position": "백엔드 엔지니어", "company": {"name": "W"},
         "annual_from": 1, "annual_to": 3, "skill_tags": [{"title": "Go"}],
         "category_tag": {"parent_id": 518},
         "address": {"location": "서울", "district": "강남구"}, "due_time": None},
        {"id": 11, "position": "백엔드 엔지니어", "company": {"name": "X"},
         "annual_from": 0, "category_tag": {"parent_id": 999}},  # 카테고리 제외
    ]}
    out = parse_wanted_results(payload, [518, 507], ["백엔드"], 2)
    assert len(out) == 1
    r = out[0]
    assert r["source"] == "wanted" and r["job_id"] == "10"
    assert r["url"] == "https://www.wanted.co.kr/wd/10"
    assert r["tech_stacks"] == ["Go"]
    assert r["locations"] == "서울 강남구"


def test_wanted_list_url_offset():
    url = wanted_list_url(518, 40)
    assert "job_group_id=518" in url and "offset=40" in url and "limit=20" in url


def test_stack_name_survives_non_string_non_dict():
    # 원티드가 skill_tags를 [1464, 1698] 같은 정수 ID 배열로 주는 공고가 실재한다.
    # int에 .get()을 부르면 AttributeError → 파싱이 죽고 페이지네이션까지 끊겼다.
    from app.collect.sources.common import _stack_name
    assert _stack_name(1464) == ""
    assert _stack_name(None) == ""
    assert _stack_name(["Go"]) == ""
    assert _stack_name({"title": "Go"}) == "Go"   # 기존 동작 유지
    assert _stack_name("Python") == "Python"


def test_parse_wanted_survives_integer_skill_tags():
    # 실제 공고 178246의 형태: skill_tags가 정수 ID 배열.
    payload = {"data": [
        {"id": 178246, "position": "AI/ML Engineer", "company": {"name": "Z"},
         "annual_from": 1, "skill_tags": [1464, 1698, 1554],
         "category_tag": {"parent_id": 518}, "address": {"location": "서울"}},
    ]}
    out = parse_wanted_results(payload, [518, 507], ["AI"], 2)  # 예외 없이 반환되어야 함
    assert len(out) == 1
    assert out[0]["job_id"] == "178246"
    assert out[0]["tech_stacks"] == []   # 정수 ID는 스택 이름이 아니므로 버린다


def test_parse_jumpit_drops_unusable_stack_entries():
    payload = {"result": {"positions": [
        {"id": 1, "title": "AI 엔지니어", "companyName": "A", "minCareer": 1,
         "techStacks": ["Python", 99, {"stack": "Go"}, {}]},
    ]}}
    out = parse_jumpit_positions(payload, ["AI"], 2)
    assert out[0]["tech_stacks"] == ["Python", "Go"]   # 빈 이름은 저장하지 않는다
