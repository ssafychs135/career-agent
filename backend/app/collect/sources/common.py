import math
import re

_TAG = re.compile(r"<[^>]*>")


def strip_tags(s) -> str:
    return _TAG.sub("", s or "").strip()


def title_hit(title: str, keywords) -> bool:
    t = title or ""
    for kw in keywords:
        pat = r"\b" + re.escape(kw) + r"\b"
        if re.search(pat, t, re.IGNORECASE):
            return True
    return False


def career_ok(min_career, max_years) -> bool:
    if max_years is None or (isinstance(max_years, float) and math.isnan(max_years)):
        return True
    if min_career is None:
        return True
    return min_career <= max_years


def _stack_name(t) -> str:
    if isinstance(t, str):
        return strip_tags(t)
    return strip_tags(t.get("stack") or t.get("name") or t.get("title") or "")
