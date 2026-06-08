"""LLM 全局计费设置、目录定价合并与 admin 批量登记。"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modstore_server.db.base import Base
from modstore_server.llm_billing import (
    UsageMeter,
    billing_settings_dict,
    calculate_charge,
    get_or_create_billing_settings,
    merge_catalog_pricing,
    model_price,
)
from modstore_server.llm_model_gates import merge_catalog_capabilities
from modstore_server.models import AiModelPrice, LlmBillingSettings


@pytest.fixture
def mem_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_billing_settings_override_env_defaults(mem_db):
    row = get_or_create_billing_settings(mem_db)
    row.service_fee_multiplier = Decimal("2")
    row.default_input_price_per_1k = Decimal("0.01")
    row.default_output_price_per_1k = Decimal("0.02")
    row.default_min_charge = Decimal("0.03")
    mem_db.commit()
    s = billing_settings_dict(mem_db)
    assert s["service_fee_multiplier"] == 2.0
    assert s["default_input_price_per_1k"] == 0.01
    in_p, out_p, min_c = model_price(mem_db, "openai", "unknown-model")
    assert in_p == Decimal("0.01")
    assert out_p == Decimal("0.02")
    assert min_c == Decimal("0.03")


def test_merge_catalog_pricing_attaches_pricing(mem_db):
    mem_db.add(
        AiModelPrice(
            provider="openai",
            model="gpt-test",
            input_price_per_1k=0.01,
            output_price_per_1k=0.02,
            min_charge=0.01,
            enabled=True,
        )
    )
    mem_db.commit()
    providers_out = [
        {
            "provider": "openai",
            "models": ["gpt-test", "gpt-other"],
            "models_detailed": [
                {"id": "gpt-test", "category": "llm"},
                {"id": "gpt-other", "category": "llm"},
            ],
        }
    ]
    merge_catalog_capabilities(mem_db, providers_out)
    merge_catalog_pricing(mem_db, providers_out)
    p0 = providers_out[0]["models_detailed"][0]["pricing"]
    p1 = providers_out[0]["models_detailed"][1]["pricing"]
    assert p0["source"] == "db"
    assert p0["input_price_per_1k"] == 0.01
    assert p1["source"] == "default"
    assert "effective_input_per_1k" in p1


def test_calculate_charge_uses_db_service_fee(mem_db):
    row = get_or_create_billing_settings(mem_db)
    row.service_fee_multiplier = Decimal("2")
    mem_db.commit()
    mem_db.add(
        AiModelPrice(
            provider="openai",
            model="fee-test",
            input_price_per_1k=0.01,
            output_price_per_1k=0,
            min_charge=0,
            enabled=True,
        )
    )
    mem_db.commit()
    usage = UsageMeter(prompt_tokens=1000, completion_tokens=0, total_tokens=1000)
    charge = calculate_charge(mem_db, "openai", "fee-test", usage)
    assert charge == Decimal("0.02")
