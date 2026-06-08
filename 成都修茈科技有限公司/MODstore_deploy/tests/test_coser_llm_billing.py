from __future__ import annotations

import json
import uuid
from pathlib import Path

from modstore_server.llm_api import _membership_meta
from modstore_server.llm_billing import UsageMeter, calculate_charge, usage_from_response
from modstore_server.models import AiModelPrice


def test_fallback_catalog_contains_domestic_providers():
    data_path = (
        Path(__file__).resolve().parent.parent
        / "modstore_server"
        / "data"
        / "llm_fallback_models.json"
    )
    data = json.loads(data_path.read_text(encoding="utf-8"))

    for provider in ("doubao", "dashscope", "wenxin", "hunyuan", "zhipu", "xunfei"):
        assert provider in data
        assert data[provider]


def test_usage_normalizes_vendor_token_shapes():
    usage = usage_from_response(
        {"promptTokenCount": 10, "candidatesTokenCount": 7, "totalTokenCount": 17},
        [{"role": "user", "content": "你好"}],
        "你好",
    )

    assert usage == UsageMeter(
        prompt_tokens=10, completion_tokens=7, total_tokens=17, estimated=False
    )


def test_calculate_charge_uses_model_price_with_service_fee_multiplier(client):
    from modstore_server.models import get_session_factory

    provider = f"pytest-provider-{uuid.uuid4().hex[:8]}"
    model = "pytest-model"
    sf = get_session_factory()
    with sf() as session:
        session.add(
            AiModelPrice(
                provider=provider,
                model=model,
                input_price_per_1k=0.01,
                output_price_per_1k=0.03,
                min_charge=0.01,
                enabled=True,
            )
        )
        session.commit()
        amount = calculate_charge(
            session,
            provider,
            model,
            UsageMeter(prompt_tokens=1000, completion_tokens=1000, total_tokens=2000),
        )

    assert str(amount) == "0.06"


def test_membership_meta_marks_byok_tiers():
    assert _membership_meta(None) == {
        "tier": "free",
        "label": "普通用户",
        "is_member": False,
        "can_byok": False,
    }
    assert _membership_meta("plan_basic")["is_member"] is True
    assert _membership_meta("plan_basic")["can_byok"] is False
    assert _membership_meta("plan_pro")["can_byok"] is True
    assert _membership_meta("plan_enterprise")["can_byok"] is True
