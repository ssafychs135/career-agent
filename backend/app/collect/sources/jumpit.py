from app.collect.sources.common import _stack_name, career_ok, strip_tags, title_hit


def parse_jumpit_positions(payload: dict, keywords, max_years) -> list[dict]:
    positions = (payload or {}).get("result", {}).get("positions", []) or []
    out = []
    for p in positions:
        title = strip_tags(p.get("title"))
        min_career = p.get("minCareer")
        if not title_hit(title, keywords) or not career_ok(min_career, max_years):
            continue
        locs = p.get("locations") or []
        out.append({
            "source": "jumpit", "job_id": str(p.get("id") or ""),
            "company": p.get("companyName") or "", "title": title,
            "url": f"https://jumpit.saramin.co.kr/position/{p.get('id')}",
            "min_career": min_career, "max_career": p.get("maxCareer"),
            "tech_stacks": [_stack_name(t) for t in (p.get("techStacks") or [])],
            "locations": ", ".join(locs) if isinstance(locs, list) else str(locs or ""),
            "closed_at": p.get("closedAt"),
        })
    return out
