"""从官网价表 / OpenRouter 公开 API 同步模型官方价（元/1k tokens）。"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy.orm import Session

from modstore_server.models import AiModelPrice

logger = logging.getLogger(__name__)

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


@dataclass
class OfficialQuote:
    input_per_1k: Decimal
    output_per_1k: Decimal
    min_charge: Decimal
    source: str


def _data_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "llm_official_prices.json"


def _usd_to_cny() -> Decimal:
    raw = os.environ.get("LLM_USD_TO_CNY_RATE", "").strip()
    if raw:
        try:
            return Decimal(raw)
        except Exception:
            pass
    try:
        data = json.loads(_data_path().read_text(encoding="utf-8"))
        return Decimal(str(data.get("meta", {}).get("usd_to_cny", 7.2)))
    except Exception:
        return Decimal("7.2")


def _per_1m_to_per_1k_cny(amount_per_1m: float, currency: str) -> Decimal:
    per_1k = Decimal(str(amount_per_1m)) / Decimal(1000)
    if (currency or "").upper() == "USD":
        per_1k *= _usd_to_cny()
    return per_1k.quantize(Decimal("0.000001"))


def _quote_from_entry(entry: Dict[str, Any], currency: str, source: str) -> OfficialQuote:
    in_p = _per_1m_to_per_1k_cny(float(entry.get("input_per_1m") or 0), currency)
    out_p = _per_1m_to_per_1k_cny(float(entry.get("output_per_1m") or 0), currency)
    min_c = Decimal(str(entry.get("min_charge") or 0.01))
    return OfficialQuote(input_per_1k=in_p, output_per_1k=out_p, min_charge=min_c, source=source)


def load_curated_catalog() -> Dict[str, Any]:
    path = _data_path()
    if not path.is_file():
        return {"providers": {}, "openrouter_provider_map": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def lookup_curated_quote(
    provider: str, model_id: str, catalog: Optional[Dict[str, Any]] = None
) -> Optional[OfficialQuote]:
    data = catalog or load_curated_catalog()
    block = (data.get("providers") or {}).get(provider)
    if not block:
        return None
    currency = str(block.get("currency") or "CNY")
    source_url = str(block.get("source_url") or "")
    models = block.get("models") or {}
    if model_id in models:
        return _quote_from_entry(models[model_id], currency, f"curated:{source_url}")
    mid = model_id.lower()
    for key, entry in models.items():
        if key.lower() == mid:
            return _quote_from_entry(entry, currency, f"curated:{source_url}")
    for pat in block.get("patterns") or []:
        prefix = str(pat.get("prefix") or "")
        if prefix and mid.startswith(prefix.lower()):
            return _quote_from_entry(pat, currency, f"curated:{source_url}")
    return None


async def fetch_openrouter_quotes() -> Dict[Tuple[str, str], OfficialQuote]:
    """provider, model_id -> quote（model_id 为 OpenRouter 后缀，不含厂商前缀）。"""
    out: Dict[Tuple[str, str], OfficialQuote] = {}
    catalog = load_curated_catalog()
    prov_map: Dict[str, str] = dict(catalog.get("openrouter_provider_map") or {})
    try:
        from modstore_server.infrastructure.http_clients import get_http_client

        client = get_http_client()
        resp = await client.get(OPENROUTER_MODELS_URL, timeout=30.0)
    except Exception:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(OPENROUTER_MODELS_URL)
    if resp.status_code >= 400:
        logger.warning("openrouter models fetch failed: %s", resp.status_code)
        return out
    payload = resp.json()
    for item in payload.get("data") or []:
        oid = str(item.get("id") or "")
        if "/" not in oid:
            continue
        or_prov, model_id = oid.split("/", 1)
        our_prov = prov_map.get(or_prov) or prov_map.get(or_prov.lower())
        if not our_prov:
            continue
        pricing = item.get("pricing") or {}
        try:
            pin = float(pricing.get("prompt") or 0)
            pout = float(pricing.get("completion") or 0)
        except (TypeError, ValueError):
            continue
        if pin <= 0 and pout <= 0:
            continue
        in_per_1k = Decimal(str(pin)) * Decimal(1000) * _usd_to_cny()
        out_per_1k = Decimal(str(pout)) * Decimal(1000) * _usd_to_cny()
        out[(our_prov, model_id)] = OfficialQuote(
            input_per_1k=in_per_1k.quantize(Decimal("0.000001")),
            output_per_1k=out_per_1k.quantize(Decimal("0.000001")),
            min_charge=Decimal("0.01"),
            source=f"openrouter:live:{oid}",
        )
    return out


def resolve_official_quote(
    provider: str,
    model_id: str,
    *,
    openrouter_index: Optional[Dict[Tuple[str, str], OfficialQuote]] = None,
    curated: Optional[Dict[str, Any]] = None,
    prefer: str = "openrouter",
) -> Optional[OfficialQuote]:
    """prefer: openrouter | curated | openrouter_first"""
    or_q = None
    if openrouter_index is not None:
        or_q = openrouter_index.get((provider, model_id))
        if or_q is None:
            mid = model_id.lower()
            for (p, m), q in openrouter_index.items():
                if p == provider and (m == model_id or mid.startswith(m.lower())):
                    or_q = q
                    break
    cur_q = lookup_curated_quote(provider, model_id, curated)
    if prefer == "curated":
        return cur_q or or_q
    if prefer == "openrouter":
        return or_q or cur_q
    return or_q or cur_q


def _get_or_create_price_row(session: Session, provider: str, model_id: str) -> AiModelPrice:
    row = (
        session.query(AiModelPrice)
        .filter(AiModelPrice.provider == provider, AiModelPrice.model == model_id)
        .first()
    )
    if not row:
        row = AiModelPrice(provider=provider, model=model_id, label=model_id)
        session.add(row)
        session.flush()
    return row


def apply_quote_to_row(
    row: AiModelPrice, quote: OfficialQuote, *, synced_at: Optional[datetime] = None
) -> None:
    row.official_input_price_per_1k = float(quote.input_per_1k)
    row.official_output_price_per_1k = float(quote.output_per_1k)
    row.official_min_charge = float(quote.min_charge)
    row.official_source = quote.source[:500]
    row.official_synced_at = synced_at or datetime.now(timezone.utc)


async def sync_official_prices_for_provider(
    session: Session,
    provider: str,
    model_ids: List[str],
    *,
    sources: Optional[List[str]] = None,
) -> Dict[str, Any]:
    src = [s.strip().lower() for s in (sources or ["curated", "openrouter"]) if s]
    openrouter_index: Dict[Tuple[str, str], OfficialQuote] = {}
    if "openrouter" in src:
        openrouter_index = await fetch_openrouter_quotes()
    curated = load_curated_catalog()
    now = datetime.now(timezone.utc)
    updated = 0
    skipped = 0
    samples: List[Dict[str, Any]] = []
    for mid in model_ids:
        mid = (mid or "").strip()
        if not mid:
            continue
        prefer = "openrouter_first"
        if src == ["curated"]:
            prefer = "curated"
        elif src == ["openrouter"]:
            prefer = "openrouter"
        quote = resolve_official_quote(
            provider, mid, openrouter_index=openrouter_index, curated=curated, prefer=prefer
        )
        if not quote:
            skipped += 1
            continue
        row = _get_or_create_price_row(session, provider, mid)
        apply_quote_to_row(row, quote, synced_at=now)
        updated += 1
        if len(samples) < 8:
            samples.append(
                {
                    "model": mid,
                    "official_input_per_1k": float(quote.input_per_1k),
                    "official_output_per_1k": float(quote.output_per_1k),
                    "source": quote.source,
                }
            )
    return {
        "provider": provider,
        "updated": updated,
        "skipped": skipped,
        "total": len(model_ids),
        "sync_at": now.isoformat(),
        "sources": src,
        "samples": samples,
    }


def apply_official_markup_to_rows(
    session: Session,
    provider: str,
    model_ids: List[str],
    markup: Decimal,
) -> Dict[str, Any]:
    if markup < Decimal("1"):
        raise ValueError("官网价倍率不能小于 1")
    applied = 0
    skipped = 0
    for mid in model_ids:
        mid = (mid or "").strip()
        if not mid:
            continue
        row = (
            session.query(AiModelPrice)
            .filter(AiModelPrice.provider == provider, AiModelPrice.model == mid)
            .first()
        )
        if not row or row.official_input_price_per_1k is None:
            skipped += 1
            continue
        oin = Decimal(str(row.official_input_price_per_1k))
        oout = Decimal(str(row.official_output_price_per_1k or 0))
        omin = Decimal(str(row.official_min_charge or 0.01))
        row.input_price_per_1k = float((oin * markup).quantize(Decimal("0.000001")))
        row.output_price_per_1k = float((oout * markup).quantize(Decimal("0.000001")))
        row.min_charge = float(money_max(omin * markup, Decimal("0.01")))
        if not row.enabled:
            row.enabled = True
        applied += 1
    return {"provider": provider, "applied": applied, "skipped": skipped, "markup": float(markup)}


def money_max(a: Decimal, b: Decimal) -> Decimal:
    return a if a >= b else b


def list_official_sources_for_provider(provider: str) -> Dict[str, Any]:
    data = load_curated_catalog()
    block = (data.get("providers") or {}).get(provider) or {}
    return {
        "provider": provider,
        "source_url": block.get("source_url") or "",
        "currency": block.get("currency") or "CNY",
        "openrouter_supported": provider in (data.get("openrouter_provider_map") or {}).values()
        or provider in (data.get("openrouter_provider_map") or {}),
    }
