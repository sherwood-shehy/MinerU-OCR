class MinerUOCRError(RuntimeError):
    """Base error for user-actionable OCR failures."""


class MinerUAPIError(MinerUOCRError):
    def __init__(self, message: str, *, code: int | str | None = None, trace_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.trace_id = trace_id


class PlanningError(MinerUOCRError):
    pass


class MergeError(MinerUOCRError):
    pass

