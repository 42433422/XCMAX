"""Read the pinned LiteLLM accounting ledger without issuing model requests.

SpendLogs can contain estimated streaming usage. Only the upstream durable
accounting envelope explicitly marked ``measured`` can discharge an unknown
reservation. SQLAlchemy/psycopg2 own the read-only database transport.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from modstore_server.strategic_portfolio import PortfolioError, _date, digest

_MASTER_IDENTITY_SCHEME = "litellm_master_alias_v1"


def ledger_source() -> tuple[str, str]:
    raw = os.environ.get("MODSTORE_LITELLM_ACCOUNTING_DATABASE_URL", "").strip()
    if not raw:
        return "", ""
    url = make_url(raw)
    if url.drivername not in {"postgresql", "postgresql+psycopg2"} or not url.host:
        raise PortfolioError("usage readback requires a configured PostgreSQL accounting source")
    # Neither a password nor the inference credential is persisted in a receipt.
    identity = digest([url.host, url.port or 5432, url.database, url.username])
    return raw, identity


def transport_identity(provider: str) -> dict[str, str]:
    from litellm.constants import LITELLM_PROXY_MASTER_KEY_ALIAS

    from modstore_server.llm_chat_proxy import _normalize_openai_base
    from modstore_server.llm_key_resolver import platform_api_key, platform_base_url
    from modstore_server.platform_model_config import PlatformApiKey

    key = platform_api_key(provider)
    if not key:
        raise PortfolioError("model transport credential is unavailable")
    if (
        provider != "litellm"
        or not isinstance(key, PlatformApiKey)
        or key.configuration.get("provider") != "litellm"
        or key.configuration.get("source") != "environment"
    ):
        raise PortfolioError("usage readback requires the configured LiteLLM master transport")
    endpoint = _normalize_openai_base(provider, platform_base_url(provider), key)
    _, source = ledger_source()
    return {
        "endpoint_sha256": digest(endpoint.rstrip("/")),
        # The upstream master-key authenticator logs this non-secret alias.
        "accounting_identity_scheme": _MASTER_IDENTITY_SCHEME,
        "accounting_identity": LITELLM_PROXY_MASTER_KEY_ALIAS,
        "ledger_source_sha256": source,
    }


def _accounting_engine(url: str):
    return create_engine(
        url,
        poolclass=NullPool,
        connect_args={"connect_timeout": 3, "options": "-c statement_timeout=3000"},
        execution_options={"postgresql_readonly": True},
    )


def _events(binding: dict[str, Any]) -> list[dict[str, Any]]:
    url, source = ledger_source()
    if not url or source != binding.get("ledger_source_sha256"):
        return []
    engine = _accounting_engine(url)
    try:
        with engine.connect() as connection:
            # Exact request identity, bounded results, no access to prompts or
            # responses. More than one outbound attempt remains unresolved.
            rows = connection.execute(
                text(
                    "SELECT event_id, kind, schema_version, payload "
                    'FROM "LiteLLM_AccountingEvent" '
                    "WHERE kind IN ('inbound_usage', 'outbound_usage') "
                    "AND payload -> 'event' ->> 'request_id' = :request_id LIMIT 3"
                ),
                {"request_id": binding["request_id"]},
            ).mappings()
            return [dict(row) for row in rows]
    finally:
        engine.dispose()


def read_usage(binding: dict[str, Any]) -> dict[str, Any] | None:
    """A terminal caller and its one measured original attempt must agree."""
    from litellm.accounting import InboundUsageEvent, OutboundUsageEvent
    from litellm.constants import LITELLM_PROXY_MASTER_KEY_ALIAS

    if binding.get("provider") != "litellm":
        return None
    if "accounting_identity_scheme" in binding or "accounting_identity" in binding:
        identity = binding.get("accounting_identity")
        if (
            binding.get("accounting_identity_scheme") != _MASTER_IDENTITY_SCHEME
            or identity != LITELLM_PROXY_MASTER_KEY_ALIAS
            or "credential_sha256" in binding
        ):
            return None
    else:
        # Historical bindings retain their exact original identity and digest.
        # A master alias cannot retroactively prove an old hash-bound call.
        identity = binding.get("credential_sha256")
        if not isinstance(identity, str) or re.fullmatch(r"[0-9a-f]{64}", identity) is None:
            return None
    current = transport_identity("litellm")
    if current["endpoint_sha256"] != binding.get("endpoint_sha256"):
        return None
    rows = _events(binding)
    if len(rows) != 2 or {row["kind"] for row in rows} != {
        "inbound_usage",
        "outbound_usage",
    }:
        return None
    envelopes = {}
    for row in rows:
        payload = row["payload"]
        payload = json.loads(payload) if isinstance(payload, str) else payload
        if not isinstance(payload, dict) or row["schema_version"] != 1:
            return None
        model = InboundUsageEvent if row["kind"] == "inbound_usage" else OutboundUsageEvent
        event = model.model_validate_json(json.dumps(payload.get("event"), allow_nan=False))
        if event.event_id != row["event_id"] or event.request_id != binding["request_id"]:
            return None
        dimensions = {item.name.value: item.value for item in event.dimensions}
        if (
            dimensions.get("key") != identity
            or dimensions.get("model_group") != binding["model"]
            or event.call_type.value not in {"acompletion", "completion", "aresponses", "responses"}
            or event.started_at < _date(binding["started_at"])
            or event.ended_at > datetime.now(UTC)
        ):
            return None
        envelopes[row["kind"]] = (payload, event)
    envelope, outbound = envelopes["outbound_usage"]
    _, inbound = envelopes["inbound_usage"]
    if not isinstance(outbound, OutboundUsageEvent) or not isinstance(inbound, InboundUsageEvent):
        return None
    if (
        inbound.event_id != f"{binding['request_id']}:inbound"
        or outbound.event_id != outbound.attempt_id
        or inbound.started_at != outbound.started_at
        or inbound.ended_at != outbound.ended_at
        or inbound.outcome != outbound.outcome
        or inbound.dimensions != outbound.dimensions
        or inbound.call_type != outbound.call_type
        or outbound.retry_of_attempt_id is not None
        or envelope.get("usage_source") != "measured"
        or envelope.get("ownership") != "attempt"
        or envelope.get("phase") != "execution"
        or envelope.get("charge_eligible") is not True
        or envelope.get("request_count_eligible") is not True
        or envelope.get("parent_request_id") is not None
        or envelope.get("job_id") is not None
        or envelope.get("included_attempt_ids") != []
        or envelope.get("related_attempt_ids") != []
    ):
        return None
    values = envelope.get("usage")
    if not isinstance(values, dict) or any(
        type(values.get(key)) is not int or not 0 <= values[key] < 2**63
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    ):
        return None
    if values["total_tokens"] != values["prompt_tokens"] + values["completion_tokens"]:
        return None
    metrics = {item.name.value: item.value for item in outbound.metrics or ()}
    if any(
        metrics.get(key) != values[key]
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    ):
        return None
    return {
        "provider": "litellm",
        "model": binding["model"],
        "usage": values,
        "gateway_attempts_verified": True,
        "response_id": outbound.attempt_id,
        "readback": {
            "source": "litellm_accounting_v1",
            "binding_sha256": digest(binding),
            "event_ids": [inbound.event_id, outbound.event_id],
            "envelope_sha256": digest(envelope),
            "completed_at": outbound.ended_at.isoformat(),
        },
    }
