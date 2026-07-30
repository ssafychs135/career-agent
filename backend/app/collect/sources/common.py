import math
import re

_TAG = re.compile(r"<[^>]*>")


def strip_tags(s) -> str:
    return _TAG.sub("", s or "").strip()


def title_hit(title: str, keywords) -> bool:
    t = title or ""
    for kw in keywords:
        pat = r"(^|[^A-Za-z0-9])" + re.escape(kw) + r"([^A-Za-z0-9]|$)"
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
    """스택 태그 → 사람이 읽는 이름. 이름을 못 얻으면 빈 문자열.

    원티드는 일부 공고의 skill_tags를 [1464, 1698] 같은 정수 ID 배열로 준다.
    예전엔 int에 .get()을 불러 AttributeError가 났고, 그게 수집기의
    페이지네이션까지 끊었다(카테고리 전체 유실). 모르는 타입은 조용히 버린다.
    """
    if isinstance(t, str):
        return strip_tags(t)
    if isinstance(t, dict):
        return strip_tags(t.get("stack") or t.get("name") or t.get("title") or "")
    return ""  # 정수 ID 등 이름을 알 수 없는 형태
