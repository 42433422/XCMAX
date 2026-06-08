"""llm_model_gates：L2 定价闸门、目录能力合并占位。"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modstore_server.llm_model_gates import (
    ensure_capability_stubs,
    l2_platform_billing_allowed,
    merge_catalog_capabilities,
    preauth_multiplier_for_model,
)
from modstore_server.models import AiModelPrice, Base, LlmModelCapability


@pytest.fixture()
def mem_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()


def test_l2_default_allows_without_price_row(monkeypatch, mem_db):
    monkeypatch.setenv("MODSTORE_LLM_PLATFORM_REQUIRE_PRICED", "0")
    ok, _ = l2_platform_billing_allowed(mem_db, "openai", "unknown-model-xyz")
    assert ok is True


def test_preauth_mult_byok(mem_db):
    assert preauth_multiplier_for_model(mem_db, "openai", "any", is_byok=True) == 1.0


def test_preauth_mult_platform_unpriced(monkeypatch, mem_db):
    monkeypatch.setenv("MODSTORE_LLM_NEW_MODEL_PREAUTH_MULT", "2")
    m = preauth_multiplier_for_model(mem_db, "openai", "unpriced-model", is_byok=False)
    assert m == 2.0


def test_l2_require_priced_blocks_without_row(monkeypatch, mem_db):
    monkeypatch.setenv("MODSTORE_LLM_PLATFORM_REQUIRE_PRICED", "1")
    ok, msg = l2_platform_billing_allowed(mem_db, "openai", "no-row")
    assert ok is False
    assert "定价" in msg or "L3" in msg


def test_l2_require_priced_allows_enabled_row(monkeypatch, mem_db):
    monkeypatch.setenv("MODSTORE_LLM_PLATFORM_REQUIRE_PRICED", "1")
    mem_db.add(
        AiModelPrice(
            provider="openai",
            model="priced-m",
            label="t",
            input_price_per_1k=0.001,
            output_price_per_1k=0.002,
            min_charge=0.01,
            enabled=True,
        )
    )
    mem_db.commit()
    ok, _ = l2_platform_billing_allowed(mem_db, "openai", "priced-m")
    assert ok is True


def test_l2_l3_approved_without_price(monkeypatch, mem_db):
    monkeypatch.setenv("MODSTORE_LLM_PLATFORM_REQUIRE_PRICED", "1")
    mem_db.add(
        LlmModelCapability(
            provider="openai",
            model="l3-only",
            l1_status="pending",
            l3_status="approved",
            effective_category="llm",
        )
    )
    mem_db.commit()
    ok, _ = l2_platform_billing_allowed(mem_db, "openai", "l3-only")
    assert ok is True


def test_merge_inserts_capability_on_detailed(mem_db):
    providers_out = [
        {
            "provider": "openai",
            "models": ["gpt-test-mini"],
            "models_detailed": [{"id": "gpt-test-mini", "category": "llm"}],
        }
    ]
    merge_catalog_capabilities(mem_db, providers_out)
    mem_db.commit()
    row = (
        mem_db.query(LlmModelCapability).filter_by(provider="openai", model="gpt-test-mini").first()
    )
    assert row is not None
    assert row.l1_status == "pending"
    assert providers_out[0]["models_detailed"][0].get("capability")


def test_ensure_stubs_idempotent(mem_db):
    n1 = ensure_capability_stubs(mem_db, "deepseek", ["a", "b"])
    mem_db.commit()
    n2 = ensure_capability_stubs(mem_db, "deepseek", ["a", "b"])
    mem_db.commit()
    assert n1 == 2
    assert n2 == 0
