from app.notify.notifier import (
    EMBED_COLOR, build_embed, chunk, passes_filter,
)


def _row(**kw):
    base = dict(id=1, source="wanted", job_id="1", company="미스릴", title="백엔드",
                url="https://x/1", locations="서울 강남구", min_career=1, max_career=3,
                tech_stacks=["python", "fastapi"], summary="좋은 회사\n기술스택: python, fastapi")
    base.update(kw)
    return base


def test_build_embed_strips_stack_line_from_description():
    e = build_embed(_row())
    assert "기술스택" not in e["description"]
    assert e["description"] == "좋은 회사"


def test_build_embed_strips_only_first_stack_line_like_original_js():
    # 원본 JS는 /g 없는 replace라 첫 매치만 제거한다 — 포팅 충실도(디스코드 출력 동일성).
    e = build_embed(_row(summary="기술스택: A\n본문\n기술스택: B"))
    assert "기술스택: B" in e["description"]
    assert "기술스택: A" not in e["description"]


def test_build_embed_fields_and_shape():
    e = build_embed(_row())
    assert e["title"] == "미스릴 — 백엔드"
    assert e["url"] == "https://x/1" and e["color"] == EMBED_COLOR
    names = [f["name"] for f in e["fields"]]
    assert names == ["경력", "기술스택", "출처"]
    assert e["fields"][0]["value"] == "1~3"
    assert e["fields"][1]["value"] == "python, fastapi"
    assert e["fields"][2]["value"] == "wanted"


def test_build_embed_career_unknown_and_empty_summary():
    e = build_embed(_row(min_career=None, max_career=None, summary=""))
    assert e["fields"][0]["value"] == "무관"
    assert e["description"] == "(요약 없음)"


def test_build_embed_truncates_long_description_and_title():
    e = build_embed(_row(summary="가" * 500, company="회" * 200, title="사" * 200))
    assert len(e["description"]) == 401 and e["description"].endswith("…")
    assert len(e["title"]) == 250


def test_passes_filter_hidden_company_excluded():
    assert passes_filter(_row(), [], ["미스릴"]) is False
    assert passes_filter(_row(), [], ["다른곳"]) is True


def test_passes_filter_region_allowlist():
    assert passes_filter(_row(), ["서울"], []) is True
    assert passes_filter(_row(), ["부산"], []) is False


def test_passes_filter_empty_arrays_pass_everything():
    assert passes_filter(_row(), [], []) is True


def test_chunk_splits_on_boundary():
    assert chunk(list(range(25)), 10) == [list(range(10)), list(range(10, 20)), [20, 21, 22, 23, 24]]
    assert chunk([], 10) == []
