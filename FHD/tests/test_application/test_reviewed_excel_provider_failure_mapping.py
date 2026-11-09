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


def test_detached_slice_decision_recovers_only_unchanged_complete_document():
    from app.application.reviewed_excel_template import _recover_detached_slice_decision

    schema = {"type": "object", "required": ["documents", "can_slice"], "additionalProperties": False,
              "properties": {"documents": {"type": "array"}, "can_slice": {"type": "boolean"}}}
    raw = '{"documents":[]}] , "can_slice":false}'
    assert _recover_detached_slice_decision(raw, schema) == {"documents": [], "can_slice": False}
    assert _recover_detached_slice_decision(raw.replace('false}', 'false},{}'), schema) is None
    assert _recover_detached_slice_decision(raw.replace('false}', '"false"}'), schema) is None
    assert _recover_detached_slice_decision('{"documents":[]}, {"documents":[]}] , "can_slice":true}', schema) is None


def test_paused_invalid_answer_reports_repair_without_exposing_answer():
    from app.fastapi_routes.reviewed_excel_template import _checkpoint_view

    checkpoint = {"phase": "paused", "version": "v1", "results": [], "total": 4,
                  "max_calls": 1, "calls_in_round": 1,
                  "repair": {"rounds": 1, "reason": "缺少 can_slice", "answer": "private"}}
    view = _checkpoint_view(checkpoint)
    assert view["completed"] == 0 and view["remaining"] == 4
    assert "格式不符合要求" in view["message"] and "可能产生费用" in view["message"]
    assert "private" not in str(view)


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
            "reason": "模型边界未完整覆盖本批主体，不能自动补齐",
            "outcome": "unknown",
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


def test_insufficient_balance_is_a_definite_rejection():
    wrapped = ReviewedExcelError(
        "余额不足", provider_status=MarketModelError({"status": 402}).status_code
    )
    assert is_definite_provider_failure(wrapped)
    error = _model_processing_failure(wrapped)
    assert error.detail["outcome_unknown"] is False
    assert error.detail["retryable"] is True


def test_cause_chain_preserves_404():
    root = MarketModelError({"status": 404})
    wrapped = ReviewedExcelError("模型调用失败或结果不完整，可能已产生费用；未自动重试")
    wrapped.__cause__ = root
    assert provider_http_status(wrapped) == 404
    assert is_definite_provider_failure(wrapped)


def test_one_outcome_taxonomy_for_every_model_call():
    from app.application.elt.errors import ModelAnswerRejected, model_call_outcome

    lost = ReviewedExcelError("模型调用失败或结果不完整，可能已产生费用；未自动重试")
    cases = [
        (ModelRequestNotSent("未调用模型"), None, "not_sent", 503),
        (ReviewedExcelError("余额不足", provider_status=402), None, "rejected", 503),
        (ReviewedExcelError("答案无效"), 402, "rejected", 503),
        (ReviewedExcelError("模型区域重叠"), 200, "answered_invalid", 422),
        (ModelAnswerRejected("模型答案不是 JSON"), None, "answered_invalid", 422),
        (lost, 502, "unknown", 503),
        (lost, None, "unknown", 503),
    ]
    for exc, stored, outcome, status in cases:
        assert model_call_outcome(exc, stored_status=stored) == outcome
        error = _model_processing_failure(exc, stored_status=stored)
        assert (error.status_code, error.detail["outcome"]) == (status, outcome)
        assert error.detail["outcome_unknown"] is (outcome == "unknown")
        assert error.detail["retryable"] is (outcome != "unknown")
    assert model_call_outcome(ReviewedExcelError("网关错误", provider_status=502)) == "unknown"


def test_repair_rounds_are_bounded_and_never_resend_an_unknown_call():
    import pytest

    from app.application.elt.errors import ModelAnswerRejected
    from app.application.reviewed_excel_audit import REPAIR_ROUNDS, ask_until_valid

    asked = []

    class Answer:
        answer = "{bad}"

    def ask(messages):
        asked.append(messages)
        return Answer()

    def judge(_result):
        raise ReviewedExcelError("模型区域重叠，原分类未改变")

    with pytest.raises(ModelAnswerRejected, match="模型区域重叠"):
        ask_until_valid(ask, [{"role": "user", "content": "q"}], judge)
    assert len(asked) == REPAIR_ROUNDS + 1
    assert asked[1][-2] == {"role": "assistant", "content": "{bad}"}
    assert "模型区域重叠" in asked[1][-1]["content"]

    sends = []

    def lost(messages):
        sends.append(messages)
        raise ReviewedExcelError("模型调用失败或结果不完整，可能已产生费用；未自动重试")

    with pytest.raises(ReviewedExcelError, match="未自动重试"):
        ask_until_valid(lost, [], judge)
    assert len(sends) == 1


def test_settle_call_keeps_the_lock_only_for_an_unknown_outcome():
    from app.application.reviewed_excel_audit import settle_call

    def state(record_state):
        return {"model_audit": [{"request_sha256": "a", "state": record_state}]}

    rejected = state("inflight")
    settle_call(rejected, "a", "rejected", "provider rejected HTTP 402")
    assert rejected["model_audit"][-1]["state"] == "rejected"
    unknown = state("inflight")
    settle_call(unknown, "a", "unknown", "lost")
    assert unknown["model_audit"][-1]["state"] == "unknown"
    answered = state("streaming")
    settle_call(answered, "a", "answered_invalid", "模型区域重叠")
    record = answered["model_audit"][-1]
    assert record["state"] == "answered_invalid" and record["reason"] == "模型区域重叠"
    assert record["transitions"][-1]["from"] == "streaming"


def test_a_claim_reads_in_progress_only_while_its_request_runs():
    from app.application.reviewed_excel_audit import is_live, live_claims, mark_live

    mark_live("outside")
    assert not is_live("outside")
    with live_claims():
        mark_live("claimed")
        assert is_live("claimed")
    assert not is_live("claimed") and not is_live(None)


def test_the_public_error_says_what_happened_to_the_model_call():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.elt.errors import ModelAnswerRejected
    from app.middleware.error_handler import register_exception_handlers
    from app.middleware.request_id import RequestIdMiddleware

    cases = {
        "not_sent": (ModelRequestNotSent("未调用模型"), None, 503, True),
        "rejected": (ReviewedExcelError("余额不足", provider_status=402), None, 503, True),
        "answered_invalid": (ModelAnswerRejected("缺少 sheets"), 200, 422, True),
        "unknown": (ReviewedExcelError("连接中断"), None, 503, False),
    }
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(RequestIdMiddleware)

    @app.post("/api/templates/reviewed-excel/preview")
    def failed(outcome: str):
        exc, stored, _status, _retryable = cases[outcome]
        raise _model_processing_failure(exc, stored_status=stored)

    with TestClient(app) as client:
        for outcome, (exc, _stored, status, retryable) in cases.items():
            data = client.post(f"/api/templates/reviewed-excel/preview?outcome={outcome}").json()
            assert data["outcome"] == outcome and data["retryable"] is retryable, data
            assert data["outcome_unknown"] is (outcome == "unknown")
            assert data["message"].endswith("原因：" + str(exc)), data
            assert ("未调用模型" in data["message"]) is (outcome == "not_sent")
            assert (
                client.post(f"/api/templates/reviewed-excel/preview?outcome={outcome}").status_code
                == status
            )
