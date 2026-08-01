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


def configure_logging(level: int = logging.INFO) -> None:
    """멱등 — 여러 번 불러도 같은 줄이 두 번 찍히지 않는다."""
    root = logging.getLogger()
    root.setLevel(level)
    if any(getattr(h, HANDLER_MARK, False) for h in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(FORMAT, DATEFMT))
    setattr(handler, HANDLER_MARK, True)
    root.addHandler(handler)
