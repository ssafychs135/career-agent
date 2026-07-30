"""공고 생존 판정 — 소스별 신호가 완전히 달라 함수를 나눈다.

안전 기본값은 항상 OPEN이다. 타임아웃·5xx·페이로드 이상 등 판정 불가 상황에서
공고를 숨기면, 사용자는 그 공고의 존재조차 모르므로 복구를 요청할 수 없다.
잘못 숨기는 쪽이 잘못 보여주는 쪽보다 나쁘다.
"""
from datetime import datetime, timezone

from app.collect.collector import parse_dt

OPEN, CLOSED, DELETED = "open", "closed", "deleted"


def wanted_state(http_status: int, payload: dict) -> str:
    """원티드 상세 응답 → 생존 상태.

    실측 신호: 404(error_code 11001) = 삭제, status "close"/"draft" 또는
    hidden = 마감. due_time은 항상 null이라 쓰지 않는다.
    """
    if http_status == 404:
        return DELETED
    if http_status != 200 or not isinstance(payload, dict):
        return OPEN
    job = ((payload.get("data") or {}) if isinstance(payload.get("data"), dict) else {}).get("job")
    if not isinstance(job, dict) or not job:
        return OPEN
    status = job.get("status")
    if status is not None and status != "active":
        return CLOSED
    if job.get("hidden"):
        return CLOSED
    return OPEN


def jumpit_state(http_status: int, payload: dict, now: datetime) -> str:
    """점핏 상세 응답 → 생존 상태.

    실측: 없는 ID는 HTTP 400. 마감돼도 status=0·positionStatus="CHECKED"로
    살아있는 공고와 같으므로, closedAt 경과만이 유일한 마감 신호다.
    """
    if http_status == 400:
        return DELETED
    if http_status != 200 or not isinstance(payload, dict):
        return OPEN
    result = payload.get("result")
    if not isinstance(result, dict):
        return OPEN
    closed_at = parse_dt(result.get("closedAt"))
    if closed_at is None:
        return OPEN
    # closed_at·now의 tz 유무가 서로 다르면 비교 시 TypeError가 난다. 어느 조합이
    # 와도 예외가 새지 않도록, aware 값은 UTC로 변환한 뒤 naive로 맞춰 비교한다.
    if closed_at.tzinfo is not None:
        closed_at = closed_at.astimezone(timezone.utc).replace(tzinfo=None)
    if now.tzinfo is not None:
        now = now.astimezone(timezone.utc).replace(tzinfo=None)
    return CLOSED if closed_at < now else OPEN
