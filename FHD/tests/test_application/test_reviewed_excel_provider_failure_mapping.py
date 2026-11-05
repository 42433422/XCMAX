"""Map platform-default 404 to retryable config failure and claim release policy."""

from __future__ import annotations

from app.application.elt.errors import (
    ReviewedExcelError,
    is_definite_provider_failure,
    provider_http_status,
)
from app.application.reviewed_excel_audit import ModelRequestNotSent
from app.application.reviewed_excel_review_store import _model_processing_failure
from app.infrastructure.modstore_transport import MarketModelError


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


def test_generic_model_failure_message_keeps_public_reason():
    from app.middleware.error_handler import _elt_model_error

    mapped = _elt_model_error(
        {
            "code": "model_processing_failed",
            "message": "模型处理未完成。模型边界未完整覆盖本批主体，不能自动补齐",
            "retryable": False,
            "outcome_unknown": True,
        }
    )
    assert mapped["outcome_unknown"] is True
    assert "模型边界未完整覆盖本批主体" in mapped["message"]


def test_platform_error_valueerror_status_extracted():
    exc = ValueError("平台错误(404): 模型供应商请求失败，请检查密钥、模型、额度或服务状态")
    assert provider_http_status(exc) == 404
    assert is_definite_provider_failure(exc)


def test_market_model_error_404_maps_configuration():
    exc = MarketModelError({"status": 404, "route_metadata": {}})
    wrapped = ReviewedExcelError(str(exc), provider_status=exc.status_code)
    error = _model_processing_failure(wrapped)
    assert error.detail["code"] == "model_configuration_error"
    assert error.detail["retryable"] is True


def test_cause_chain_preserves_404():
    root = MarketModelError({"status": 404})
    wrapped = ReviewedExcelError("模型调用失败或结果不完整，可能已产生费用；未自动重试")
    wrapped.__cause__ = root
    assert provider_http_status(wrapped) == 404
    assert is_definite_provider_failure(wrapped)
