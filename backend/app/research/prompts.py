RESEARCH_TOOLS = "WebSearch,WebFetch"


def build_company_prompt(company: str, url: str = "") -> str:
    return f"""너는 취업 리서처다. 아래 회사를 웹검색으로 조사해 JSON만 출력하라.
회사명: {company}   (참고 공고 URL: {url})
{{
  "overview":  "사업·주력제품·규모 4~6문장",
  "stability": "설립연도·투자단계/누적투자·매출/흑자여부·최근 동향 등 재무·안정성 근거 4~6문장. 불확실하면 '확인 안 됨' 명시",
  "sources":   ["실제 참고한 URL"]
}}
근거 없는 추측 금지. 한국 스타트업은 정보가 적을 수 있으니 모르면 모른다고 하라.
오직 위 JSON 객체 하나만 출력하라. 설명·머리말·코드펜스 금지."""


def build_job_prompt(
    company_overview: str,
    title: str,
    tech_stacks: str,
    summary: str,
    url: str,
) -> str:
    return f"""회사 개요(기존 리서치): {company_overview}
공고: {title} / 기술스택(수집): {tech_stacks} / 요약: {summary} / URL: {url}
위 공고를 웹검색으로 조사해 JSON만 출력하라.
{{
  "tech_detail": "실제 사용 기술스택·아키텍처·개발문화 근거와 함께 4~6문장",
  "role_detail": "담당 업무·기대 경력/역량·성장경로 4~6문장",
  "sources": ["실제 참고한 URL"]
}}
근거 없는 추측 금지. 오직 위 JSON 객체 하나만 출력하라. 설명·머리말·코드펜스 금지."""
