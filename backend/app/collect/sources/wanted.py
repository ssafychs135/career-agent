from app.collect.sources.common import _stack_name, career_ok, title_hit


def wanted_list_url(cat: int, offset: int) -> str:
    return (
        "https://www.wanted.co.kr/api/chaos/navigation/v1/results"
        f"?job_group_id={cat}&country=kr&job_sort=job.latest_order"
        f"&locations=all&years=-1&limit=20&offset={offset}"
    )


def parse_wanted_results(payload: dict, cats, keywords, max_years) -> list[dict]:
    data = (payload or {}).get("data", []) or []
    out = []
    for p in data:
        parent = (p.get("category_tag") or {}).get("parent_id")
        if cats and parent is not None and parent not in cats:
            continue
        title = p.get("position") or ""
        min_career = p.get("annual_from")
        max_career = p.get("annual_to")
        if max_career is not None and max_career > 20:
            max_career = None
        if not title_hit(title, keywords) or not career_ok(min_career, max_years):
            continue
        addr = p.get("address") or {}
        loc = " ".join(x for x in [addr.get("location"), addr.get("district")] if x)
        out.append({
            "source": "wanted", "job_id": str(p.get("id") or ""),
            "company": (p.get("company") or {}).get("name") or "", "title": title,
            "url": f"https://www.wanted.co.kr/wd/{p.get('id')}",
            "min_career": min_career, "max_career": max_career,
            "tech_stacks": [_stack_name(t) for t in (p.get("skill_tags") or [])],
            "locations": loc, "closed_at": p.get("due_time"),
        })
    return out
