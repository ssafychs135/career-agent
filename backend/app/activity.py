class Activity:
    """인메모리 실행 상태. 단일 프로세스(APScheduler in-process)이므로 잠금 불필요.

    collector/worker: 단일 슬롯(dict|None). research: key→dict 다중(동시 여러 건).
    """

    def __init__(self) -> None:
        self._slots: dict[str, dict | None] = {"collector": None, "worker": None}
        self._research: dict[str, dict] = {}

    def set_stage(self, pipeline: str, stage: str, detail: str = "", progress: str = "") -> None:
        self._slots[pipeline] = {"stage": stage, "detail": detail, "progress": progress}

    def clear(self, pipeline: str) -> None:
        self._slots[pipeline] = None

    def add_research(self, key: str, stage: str, detail: str = "") -> None:
        self._research[key] = {"detail_key": key, "stage": stage, "detail": detail}

    def clear_research(self, key: str) -> None:
        self._research.pop(key, None)

    def snapshot(self) -> dict:
        return {
            "collector": self._slots["collector"],
            "worker": self._slots["worker"],
            "research": list(self._research.values()),
        }
