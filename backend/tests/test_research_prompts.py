from app.research.prompts import (
    RESEARCH_TOOLS,
    build_company_prompt,
    build_job_prompt,
)


def test_tools_are_web_only():
    assert RESEARCH_TOOLS == "WebSearch,WebFetch"


def test_company_prompt_contains_name_and_json_directive():
    p = build_company_prompt("토스", "https://x/y")
    assert "토스" in p
    assert "https://x/y" in p
    assert '"overview"' in p and '"stability"' in p and '"sources"' in p
    assert "JSON 객체 하나만" in p  # 단일 JSON 강제 지시


def test_job_prompt_injects_company_overview():
    p = build_job_prompt("핀테크 스타트업", "백엔드", "Java,Spring", "요약", "https://z")
    assert "핀테크 스타트업" in p
    assert '"tech_detail"' in p and '"role_detail"' in p
    assert "백엔드" in p and "Java,Spring" in p
