"""AIOpen 审批桥单元测试：参数指纹与身份前置校验（不依赖数据库）。"""

from __future__ import annotations

from app.application.aiopen import approval_bridge


def _entry():
    return {
        "operation_id": "products.delete",
        "method": "DELETE",
        "path": "/api/products/{product_id}",
        "risk": "danger",
    }


def test_request_digest_is_stable():
    args = {"params": {"product_id": "P-1", "page": 2}, "body": {"note": "x"}}
    first = approval_bridge.request_digest(_entry(), args)
    second = approval_bridge.request_digest(_entry(), dict(args))
    assert first == second
    assert len(first) == 64


def test_request_digest_is_order_insensitive():
    left = {"params": {"a": 1, "b": 2}}
    right = {"params": {"b": 2, "a": 1}}
    assert approval_bridge.request_digest(_entry(), left) == approval_bridge.request_digest(
        _entry(), right
    )


def test_request_digest_changes_with_arguments():
    base = {"params": {"product_id": "P-1"}}
    changed = {"params": {"product_id": "P-2"}}
    assert approval_bridge.request_digest(_entry(), base) != approval_bridge.request_digest(
        _entry(), changed
    )


def test_submit_requires_bound_identity():
    outcome = approval_bridge.submit(_entry(), {"params": {"product_id": "P-1"}}, None)
    assert outcome["status"] == "identity_required"
    assert outcome["code"] == "APPROVAL_IDENTITY_REQUIRED"
