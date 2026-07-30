"""平台计费 / 模型传递单元测试。"""

from __future__ import annotations


def test_billing_meta_from_headers_and_body():
    from app.infrastructure.llm.platform_billing_pass import (
        attach_billing_meta,
        billing_meta_from_headers,
        billing_meta_from_response,
    )

    headers = {
        "X-Xiuci-Provider": "deepseek",
        "X-Xiuci-Resolved-Model": "deepseek-chat",
        "X-Xiuci-Billed": "1",
        "X-Xiuci-Charge-CNY": "0.03",
        "X-Xiuci-Request-Id": "req-1",
    }
    meta = billing_meta_from_headers(headers)
    assert meta["provider"] == "deepseek"
    assert meta["model"] == "deepseek-chat"
    assert meta["billed"] is True
    assert meta["charge_amount_cny"] == 0.03

    result = {
        "model": "old",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        "xcagi": {
            "provider": "deepseek",
            "model": "deepseek-chat",
            "resolved_model": "deepseek/deepseek-chat",
            "billed": True,
            "charge_amount_cny": 0.03,
        },
    }
    attach_billing_meta(result, headers=headers)
    assert result["model"] == "deepseek/deepseek-chat"
    assert result["_xcagi_billing"]["billed"] is True
    assert billing_meta_from_response(result)["resolved_model"] == "deepseek/deepseek-chat"


def test_record_platform_billing(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "ledger.json"))
    from app.infrastructure.llm.platform_billing_pass import record_platform_billing

    entry = record_platform_billing(
        {
            "model": "deepseek/deepseek-chat",
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            "_xcagi_billing": {
                "provider": "deepseek",
                "model": "deepseek-chat",
                "resolved_model": "deepseek/deepseek-chat",
                "billed": True,
                "charge_amount_cny": 0.12,
                "request_id": "abc",
                "category": "llm",
            },
        },
        source="test",
        user_id="u1",
    )
    assert entry is not None
    assert entry["model"] == "deepseek/deepseek-chat"
    assert entry["billing_source"] == "platform_xcagi"
    assert entry["metadata"]["charge_amount_cny"] == 0.12
