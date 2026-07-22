def detail_url(source: str, job_id: str) -> str:
    if source == "jumpit":
        return f"https://jumpit-api.saramin.co.kr/api/position/{job_id}"
    return f"https://www.wanted.co.kr/api/chaos/jobs/v4/{job_id}/details?country=kr"


def _fmt(resp: str, qual: str, pref: str) -> str:
    return f"[주요업무]\n{resp}\n\n[자격요건]\n{qual}\n\n[우대사항]\n{pref}"


def parse_detail(source: str, payload: dict) -> str | None:
    """상세 응답 → 요약 프롬프트 본문. 파싱 실패 시 None(→ fail)."""
    if (payload or {}).get("result"):
        r = payload["result"]
        return _fmt(r.get("responsibility") or "", r.get("qualifications") or "",
                    r.get("preferredRequirements") or "")
    det = (((payload or {}).get("data") or {}).get("job") or {}).get("detail")
    if det:
        return _fmt(det.get("main_tasks") or det.get("intro") or "",
                    det.get("requirements") or "", det.get("preferred_points") or "")
    return None
