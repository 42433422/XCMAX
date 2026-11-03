"""Map platform-default 404 to retryable config failure and claim release policy."""

from __future__ import annotations

from app.application.elt.errors import ReviewedExcelError, is_definite_provider_failure
from app.application.reviewed_excel_audit import ModelRequestNotSent
from app.application.reviewed_excel_review_store import _model_processing_failure


def test_model_processing_failure_maps_404_as_retryable_config():
    exc = ReviewedExcelError("当前模型或模型服务入口不可用", provider_status=404)
    error = _model_processing_failure(exc)
    assert error.status_code == 503
    assert error.detail["code"] == "model_configuration_error"
    assert error.detail["retryable"] is True
    assert error.detail["outcome_unknown"] is False


def test_not_sent_still_configuration_error():
    error = _model_processing_failure(ModelRequestNotSent("未调用模型"))
    assert error.detail["code"] == "model_configuration_error"
    assert error.detail["retryable"] is True


def test_unknown_after_send_keeps_outcome_unknown():
    error = _model_processing_failure(ReviewedExcelError("模型调用失败或结果不完整"))
    assert error.detail["code"] == "model_processing_failed"
    assert error.detail["outcome_unknown"] is True
    assert is_definite_provider_failure(ReviewedExcelError("x", provider_status=404))
