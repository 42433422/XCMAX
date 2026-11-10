"""Domain errors for model admission limits."""


class ModelRateLimitError(RuntimeError):
    """A model request was refused before contacting the configured provider."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("当前账户模型请求过于频繁，请稍后重试。")
        self.code = "model_rate_limited"
        self.retry_after = max(1, int(retry_after))


class ModelConcurrencyLimitError(RuntimeError):
    """The process-wide model concurrency budget is full."""

    def __init__(self, retry_after: int = 1) -> None:
        super().__init__("模型并发请求已达上限，请稍后重试。")
        self.code = "model_concurrency_limited"
        self.retry_after = max(1, int(retry_after))


class ModelCircuitOpenError(RuntimeError):
    """Repeated provider failures temporarily opened its circuit."""

    def __init__(self, retry_after: int = 30) -> None:
        super().__init__("模型服务连续失败，已暂时熔断，请稍后重试。")
        self.code = "model_circuit_open"
        self.retry_after = max(1, int(retry_after))
