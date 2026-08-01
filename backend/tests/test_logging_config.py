import logging

from app.logging_config import DATEFMT, FORMAT, HANDLER_MARK, configure_logging


def _our_handlers():
    return [h for h in logging.getLogger().handlers if getattr(h, HANDLER_MARK, False)]


def test_configure_logging_attaches_handler_and_lowers_root_level():
    # uvicorn 기본 설정은 root를 손대지 않아 레벨이 WARNING·핸들러 0이다.
    # 그 상태로는 앱의 log.info가 통째로 버려진다(운영에서 collect 로그가 0건이던 원인).
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        root.handlers = []
        root.setLevel(logging.WARNING)
        configure_logging()
        assert root.level == logging.INFO
        assert len(_our_handlers()) == 1
        assert logging.getLogger("collect.collector").isEnabledFor(logging.INFO)
    finally:
        root.handlers, root.level = saved_handlers, saved_level


def test_configure_logging_is_idempotent():
    # main.py가 두 번 import되어도 같은 줄이 두 번 찍히면 안 된다.
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        root.handlers = []
        configure_logging()
        configure_logging()
        assert len(_our_handlers()) == 1
    finally:
        root.handlers, root.level = saved_handlers, saved_level


def test_noisy_third_party_loggers_stay_quiet():
    # root를 INFO로 내리면 서드파티 INFO도 같이 열린다. httpx는 요청 한 건당 한 줄을
    # 남기는데, Ops 화면이 3초마다 status를 폴링하며 LLM 헬스체크를 때려 하루 2만 줄이
    # 쌓인다 — 정작 봐야 할 수집 로그가 묻힌다.
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    saved_httpx = logging.getLogger("httpx").level
    try:
        root.handlers = []
        logging.getLogger("httpx").setLevel(logging.NOTSET)
        configure_logging()
        assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)
        assert logging.getLogger("httpx").isEnabledFor(logging.WARNING)  # 실패는 계속 보여야 한다
        assert logging.getLogger("collect.collector").isEnabledFor(logging.INFO)
    finally:
        root.handlers, root.level = saved_handlers, saved_level
        logging.getLogger("httpx").setLevel(saved_httpx)


def test_format_carries_level_and_logger_name():
    # lastResort 폴백은 맨 메시지만 찍어 어느 로거의 무슨 레벨인지 알 수 없었다.
    rec = logging.LogRecord("collect.collector", logging.WARNING, __file__, 1,
                            "수집 실패", None, None)
    out = logging.Formatter(FORMAT, DATEFMT).format(rec)
    assert "WARNING" in out and "collect.collector" in out and "수집 실패" in out
