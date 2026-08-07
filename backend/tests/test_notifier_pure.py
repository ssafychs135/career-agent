from app.notify.notifier import (
    EMBED_COLOR, build_embed, passes_filter, summary_to_description,
)


# claude 백엔드로 바꾼 뒤 요약이 완전한 마크다운 문서로 바뀌었다 — 제목(#), 볼드,
# 번호·불릿 목록, 다중 섹션. 로컬 모델 시절의 평문 3줄을 전제한 임베드 설명이
# 문서 제목만 보여주고 잘리게 됐다.
CLAUDE_SUMMARY = """# [인턴] AI Engineer @ 딥오토

**업무 요약**
1. 비정형 데이터를 정제하여 파이프라인을 구축


## 핵심 자격요건
- Python, PyTorch 능숙

기술스택: Python, PyTorch"""


def test_description_drops_leading_title_heading():
    # 첫 제목 줄은 임베드 title("딥오토 — [인턴] AI Engineer")과 중복이라 자리 낭비다.
    out = summary_to_description(CLAUDE_SUMMARY)
    assert not out.startswith("#")
    assert "AI Engineer @ 딥오토" not in out
    assert out.startswith("**업무 요약**")


def test_description_converts_headings_to_bold():
    # 디스코드는 #을 큰 제목으로 렌더링해 카드가 망가진다. 볼드로 낮춘다.
    out = summary_to_description(CLAUDE_SUMMARY)
    assert "## 핵심 자격요건" not in out
    assert "**핵심 자격요건**" in out


def test_description_keeps_list_markers_and_drops_stack_line():
    out = summary_to_description(CLAUDE_SUMMARY)
    assert "1. 비정형 데이터를 정제하여 파이프라인을 구축" in out
    assert "- Python, PyTorch 능숙" in out
    assert "기술스택" not in out


def test_description_collapses_excess_blank_lines():
    out = summary_to_description(CLAUDE_SUMMARY)
    assert "\n\n\n" not in out


def test_description_leaves_plain_summaries_untouched():
    """로컬 모델의 평문 요약은 그대로여야 한다 — 회귀 방지."""
    assert summary_to_description("좋은 회사\n기술스택: python") == "좋은 회사"
    assert summary_to_description("A\n\nB") == "A\n\nB"


def test_description_handles_empty_and_heading_only():
    assert summary_to_description("") == ""
    assert summary_to_description("# 제목뿐") == ""


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


def test_build_embed_strips_markdown_wrapped_stack_line():
    # 스택은 별도 필드로 이미 보여주므로 설명에 중복 노출되면 안 된다.
    # claude가 라벨을 볼드로 감싸면 기존 정규식이 못 잡아 그대로 남았다.
    e = build_embed(_row(summary="좋은 회사\n**기술스택**: python, fastapi"))
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


def test_notifier_select_excludes_dead_postings():
    from app.notify.notifier import SELECT_SQL
    # 마감된 공고를 디스코드로 보내는 것은 명백한 오동작.
    assert "posting_state = 'open'" in SELECT_SQL
