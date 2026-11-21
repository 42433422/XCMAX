"""Keep incomplete evidence delivery distinct from the observed browser outcome."""


def mark_delivery_incomplete(result: dict, error_code: str) -> None:
    if "execution_outcome" not in result:
        result["execution_outcome"] = result.get("outcome", "unknown")
        if result.get("error_code"):
            result["execution_error_code"] = result["error_code"]
    result.update(
        success=False,
        outcome="unknown",
        retryable=False,
        reconciliation_required=True,
        delivery_status="incomplete",
        error_code=error_code,
        message="浏览器证据未完整保存；请核对原执行和核验记录，勿重复提交原操作。",
    )
