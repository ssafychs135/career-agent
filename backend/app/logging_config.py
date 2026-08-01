"""앱 로거를 컨테이너 stdout으로 내보내는 설정.

uvicorn 기본 로깅 설정은 `uvicorn`·`uvicorn.access` 로거만 구성하고 root는
그대로 둔다. 그래서 운영에서 root 레벨이 WARNING·핸들러 0인 상태가 됐고,
앱의 log.info는 통째로 버려지고(수집 로그가 컨테이너 전 생애 0건이던 원인)
log.warning만 lastResort 폴백으로 형식 없이 찍혔다.
"""
import logging

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"
HANDLER_MARK = "_career_agent_log_handler"

# root를 INFO로 내리면 서드파티 INFO까지 함께 열린다. httpx는 요청 한 건당 한 줄을
# 남기는데, Ops 화면의 3초 폴링이 LLM 헬스체크를 태워 하루 2만 줄이 쌓인다.
# 실패(WARNING 이상)는 그대로 두고 정상 요청만 잠재운다.
QUIET_LOGGERS = ("httpx", "httpcore")


def configure_logging(level: int = logging.INFO) -> None:
    """멱등 — 여러 번 불러도 같은 줄이 두 번 찍히지 않는다."""
    root = logging.getLogger()
    root.setLevel(level)
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    if any(getattr(h, HANDLER_MARK, False) for h in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(FORMAT, DATEFMT))
    setattr(handler, HANDLER_MARK, True)
    root.addHandler(handler)
