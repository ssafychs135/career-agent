from datetime import datetime, timezone

from app.collect.liveness import CLOSED, DELETED, OPEN, jumpit_state, wanted_state

NOW = datetime(2026, 7, 30, 12, 0, 0)


def test_wanted_active_is_open():
    p = {"data": {"job": {"status": "active", "hidden": False}}}
    assert wanted_state(200, p) == OPEN


def test_wanted_404_is_deleted():
    # 실측: {"error_code": 11001, "message": "job not found exception", "data": None}
    assert wanted_state(404, {"error_code": 11001, "data": None}) == DELETED


def test_wanted_close_and_draft_are_closed():
    assert wanted_state(200, {"data": {"job": {"status": "close", "hidden": True}}}) == CLOSED
    assert wanted_state(200, {"data": {"job": {"status": "draft", "hidden": True}}}) == CLOSED


def test_wanted_hidden_alone_is_closed():
    assert wanted_state(200, {"data": {"job": {"status": "active", "hidden": True}}}) == CLOSED


def test_wanted_is_private_alone_is_open():
    """is_private는 검증되지 않은 필드 — hidden이 아니면 마감 신호로 쓰지 않는다."""
    p = {"data": {"job": {"status": "active", "hidden": False, "is_private": True}}}
    assert wanted_state(200, p) == OPEN


def test_wanted_unknown_response_stays_open():
    """판정 불가는 open — 인프라 장애로 공고를 숨기면 안 된다."""
    assert wanted_state(500, {}) == OPEN
    assert wanted_state(200, {}) == OPEN                      # 페이로드 비정상
    assert wanted_state(200, {"data": None}) == OPEN
    assert wanted_state(200, {"data": {"job": {}}}) == OPEN   # status 키 없음
    assert wanted_state(429, {"message": "rate limited"}) == OPEN


def test_jumpit_400_is_deleted():
    assert jumpit_state(400, {}, NOW) == DELETED


def test_jumpit_expired_closedat_is_closed():
    # 실측: 만료돼도 status=0·positionStatus=CHECKED로 살아있는 공고와 동일 —
    # closedAt만이 유일한 신호다.
    p = {"result": {"status": 0, "positionStatus": "CHECKED",
                    "closedAt": "2026-07-12 23:59:59"}}
    assert jumpit_state(200, p, NOW) == CLOSED


def test_jumpit_future_closedat_is_open():
    p = {"result": {"status": 0, "positionStatus": "CHECKED",
                    "closedAt": "2026-08-28 23:59:59"}}
    assert jumpit_state(200, p, NOW) == OPEN


def test_jumpit_status_fields_never_decide():
    """status=0·CHECKED는 생사와 무관하므로 이것만으로 closed 판정하면 안 된다."""
    p = {"result": {"status": 0, "positionStatus": "CHECKED"}}  # closedAt 없음
    assert jumpit_state(200, p, NOW) == OPEN


def test_jumpit_unknown_response_stays_open():
    assert jumpit_state(500, {}, NOW) == OPEN
    assert jumpit_state(200, {}, NOW) == OPEN
    assert jumpit_state(200, {"result": None}, NOW) == OPEN
    assert jumpit_state(200, {"result": {"closedAt": "not-a-date"}}, NOW) == OPEN


def test_jumpit_aware_closedat_with_naive_now_does_not_crash():
    p = {"result": {"closedAt": "2026-07-12T23:59:59+09:00"}}
    assert jumpit_state(200, p, NOW) == CLOSED


def test_jumpit_naive_closedat_with_aware_now_does_not_crash():
    p = {"result": {"closedAt": "2026-07-12 23:59:59"}}
    aware_now = datetime.now(timezone.utc)
    # tz 조합과 무관하게 예외 없이 판정만 되면 된다(어느 결과든 허용).
    assert jumpit_state(200, p, aware_now) in (OPEN, CLOSED)
