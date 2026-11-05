"""Preview candidate claims must release on definite provider 404/config failures."""

from __future__ import annotations

from app.application.elt.errors import ReviewedExcelError, is_definite_provider_failure
from app.application.reviewed_excel_review_store import _model_processing_failure


def test_definite_404_is_release_eligible():
    exc = ReviewedExcelError("当前模型或模型服务入口不可用", provider_status=404)
    assert is_definite_provider_failure(exc)
    error = _model_processing_failure(exc)
    assert error.detail["code"] == "model_configuration_error"
    assert error.detail["retryable"] is True


def test_platform_error_message_is_release_eligible():
    exc = ValueError("平台错误(404): upstream missing")
    assert is_definite_provider_failure(exc)


def test_unknown_failure_not_release_eligible():
    exc = ReviewedExcelError("模型调用失败或结果不完整，可能已产生费用；未自动重试")
    assert not is_definite_provider_failure(exc)
