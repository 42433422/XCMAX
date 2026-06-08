"""官网价同步与倍率应用。"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modstore_server.db.base import Base
from modstore_server.llm_billing import (
    billing_settings_dict,
    get_or_create_billing_settings,
    official_markup_multiplier,
)
from modstore_server.llm_official_price_sync import (
    apply_official_markup_to_rows,
    lookup_curated_quote,
    resolve_official_quote,
    sync_official_prices_for_provider,
)
from modstore_server.models import AiModelPrice


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


def test_lookup_curated_deepseek():
    q = lookup_curated_quote("deepseek", "deepseek-chat")
    assert q is not None
    assert q.input_per_1k > 0
    assert q.source.startswith("curated:")


def test_lookup_curated_pattern_prefix():
    q = lookup_curated_quote("openai", "gpt-4o-2024-08-06")
    assert q is not None
    assert float(q.input_per_1k) > 0


@pytest.mark.asyncio
async def test_sync_official_writes_rows(mem_db, monkeypatch):
    async def _empty_or():
        return {}

    monkeypatch.setattr(
        "modstore_server.llm_official_price_sync.fetch_openrouter_quotes",
        _empty_or,
    )
    result = await sync_official_prices_for_provider(
        mem_db, "deepseek", ["deepseek-chat", "unknown-model-xyz"]
    )
    assert result["updated"] >= 1
    row = (
        mem_db.query(AiModelPrice)
        .filter(AiModelPrice.provider == "deepseek", AiModelPrice.model == "deepseek-chat")
        .first()
    )
    assert row is not None
    assert row.official_input_price_per_1k is not None
    mem_db.commit()


def test_apply_official_markup(mem_db):
    row = AiModelPrice(
        provider="deepseek",
        model="deepseek-chat",
        official_input_price_per_1k=0.001,
        official_output_price_per_1k=0.002,
        official_min_charge=0.01,
        enabled=True,
    )
    mem_db.add(row)
    mem_db.commit()
    result = apply_official_markup_to_rows(mem_db, "deepseek", ["deepseek-chat"], Decimal("1.5"))
    assert result["applied"] == 1
    mem_db.commit()
    mem_db.refresh(row)
    assert float(row.input_price_per_1k) == pytest.approx(0.0015, rel=1e-6)
    assert float(row.output_price_per_1k) == pytest.approx(0.003, rel=1e-6)


def test_official_markup_multiplier_setting(mem_db):
    s = get_or_create_billing_settings(mem_db)
    s.official_markup_multiplier = Decimal("2.2")
    s.service_fee_multiplier = Decimal("1.5")
    mem_db.commit()
    assert float(official_markup_multiplier(mem_db)) == 2.2
    d = billing_settings_dict(mem_db)
    assert d["official_markup_multiplier"] == 2.2
