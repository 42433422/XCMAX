"""Bounded, source-backed perception health on the existing enterprise projection.

This is a read-only diagnostic, not a business aggregator or a new source of truth.
An empty sample never establishes zero revenue, zero complaints or a healthy system.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

# Only existing, actor-authorized ERP authorities may be sampled here.
# External systems must remain unconnected until their own source adapters are proven.
_DOMAIN_SOURCES = {
    "B01": ("fund", "journal_entry"),
    "B02": ("customer",),
    "B03": ("order",),
    "B04": (),
    "B05": (),
    "B06": (),
    "B07": ("employee", "task"),
    "B08": (),
}
_UNVERIFIED = {
    "B01": ("revenue", "costs", "cash_flow"),
    "B02": ("customer_requirements", "complaints", "churn_risk"),
    "B03": ("opportunities", "conversion_rate"),
    "B04": ("github_pr", "ci", "defects"),
    "B05": ("crashes", "incidents", "performance"),
    "B06": ("cpu", "memory", "compute", "resource_cost"),
    "B07": ("organization_capacity", "organization_task_coverage"),
    "B08": ("support_tickets", "delivery_sla", "customer_acceptance"),
}


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return at.astimezone(UTC) if at.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def _snapshot_health(snapshot: dict, scope: dict, now: datetime) -> str:
    """Never trust an expired, unscoped or evidence-free projection as a fact."""
    if (
        snapshot.get("knowledge_kind") != "fact"
        or snapshot.get("freshness") != "fresh"
        or snapshot.get("read_only") is not True
        or any(snapshot.get(key) != value for key, value in scope.items())
    ):
        return "unknown"
    version = snapshot.get("source_version")
    if (
        not isinstance(version, str)
        or not version.startswith("sha256:")
        or len(version) != 71
        or any(c not in "0123456789abcdef" for c in version[7:])
        or not isinstance(snapshot.get("state"), dict)
    ):
        return "unknown"
    evidence = snapshot.get("evidence")
    if not isinstance(evidence, list) or not evidence or not all(
        isinstance(item, dict)
        and item.get("tenant_id") == scope["tenant_id"]
        and item.get("actor_id") == scope["actor_id"]
        and item.get("mod_id") == scope["mod_id"]
        and item.get("source") == snapshot.get("source")
        and item.get("row_id") == snapshot.get("entity_id")
        and item.get("content_sha256") == version[7:]
        for item in evidence
    ):
        return "unknown"
    observed, expires = _time(snapshot.get("observed_at")), _time(snapshot.get("expires_at"))
    if observed is None or expires is None or not observed < expires or now < observed:
        return "unknown"
    return "stale" if now >= expires else "fresh"


def _journal_anomaly(snapshot: dict) -> dict | None:
    """A posted journal with inconsistent raw totals is a review candidate only."""
    if snapshot.get("entity_type") != "journal_entry":
        return None
    state = snapshot["state"]
    if state.get("status") != "posted":
        return None
    try:
        debit = Decimal(str(state["debit_total"]))
        credit = Decimal(str(state["credit_total"]))
    except (KeyError, TypeError, InvalidOperation):
        return None
    if not debit.is_finite() or not credit.is_finite() or debit == credit:
        return None
    fingerprint = hashlib.sha256(
        (
            "journal_unbalanced:"
            + snapshot["tenant_id"]
            + ":"
            + snapshot["entity_id"]
            + ":"
            + snapshot["source_version"]
        ).encode("utf-8")
    ).hexdigest()
    return {
        "candidate_id": "erp-integrity:" + fingerprint,
        "kind": "journal_unbalanced",
        "knowledge_kind": "inference",
        "derivation": "posted_journal_debit_credit_comparison",
        "entity_type": "journal_entry",
        "entity_id": snapshot["entity_id"],
        "debit_total": str(debit),
        "credit_total": str(credit),
        "source_version": snapshot["source_version"],
        "observed_at": snapshot["observed_at"],
        "evidence": snapshot["evidence"],
        "requires_human_review": True,
        "execution_authorized": False,
        "delivery_status": "not_attempted",
    }


def observe_enterprise(
    projections,
    *,
    tenant_id: str,
    actor_id: str,
    mod_id: str,
    limit_per_source: int = 3,
    force_refresh: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Sample only the caller's authorized authoritative records, never invent KPIs."""
    if (
        not str(tenant_id).isdigit()
        or int(tenant_id) <= 0
        or not str(actor_id).isdigit()
        or int(actor_id) <= 0
        or not isinstance(mod_id, str)
        or type(limit_per_source) is not int
        or not 1 <= limit_per_source <= 5
    ):
        raise ValueError("invalid_enterprise_perception_scope")
    live_clock = now is None
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("enterprise_perception_clock_timezone_required")
    now = now.astimezone(UTC)
    scope = {"tenant_id": str(tenant_id), "actor_id": str(actor_id), "mod_id": mod_id}
    domains: dict[str, dict[str, Any]] = {}
    alerts: list[dict] = []
    observed = 0
    source_statuses: dict[str, str] = {}

    for code, entities in _DOMAIN_SOURCES.items():
        sources = []
        for entity_type in entities:
            name = entity_type
            try:
                refs = projections.list_refs(
                    entity_type, limit=limit_per_source, **scope
                )
            except PermissionError:
                sources.append({"source": name, "status": "permission_denied", "samples": []})
                source_statuses[name] = "permission_denied"
                continue
            except (ConnectionError, TimeoutError):
                sources.append(
                    {
                        "source": name,
                        "status": "unavailable",
                        "samples": [],
                        "reason_code": "authority_unavailable",
                    }
                )
                source_statuses[name] = "unavailable"
                continue
            if (
                not isinstance(refs, dict)
                or refs.get("freshness") != "fresh"
                or not isinstance(refs.get("refs"), list)
                or type(refs.get("has_more")) is not bool
            ):
                sources.append({
                    "source": name,
                    "status": "unavailable",
                    "reason_code": (
                        refs.get("reason_code")
                        if isinstance(refs, dict)
                        else "invalid_source_response"
                    ),
                    "samples": [],
                })
                source_statuses[name] = "unavailable"
                continue
            samples = []
            source_observed = 0
            source_alerts = []
            for ref in refs["refs"][:limit_per_source]:
                if (
                    not isinstance(ref, dict)
                    or ref.get("entity_type") != entity_type
                    or not isinstance(ref.get("entity_id"), str)
                    or not ref["entity_id"]
                ):
                    samples.append({"status": "unknown", "reason_code": "invalid_source_reference"})
                    continue
                entity_id = ref["entity_id"]
                try:
                    snapshot = projections.get(
                        entity_type, entity_id, force_refresh=force_refresh, **scope
                    )
                except PermissionError:
                    samples.append({"status": "permission_denied"})
                    break
                except (ConnectionError, TimeoutError):
                    samples.append({"status": "unavailable"})
                    break
                if (
                    not isinstance(snapshot, dict)
                    or snapshot.get("entity_id") != entity_id
                    or snapshot.get("entity_type") != entity_type
                ):
                    samples.append({"status": "unknown", "reason_code": "source_identity_mismatch"})
                    continue
                if snapshot.get("reason_code") in {
                    "authority_unavailable",
                    "authority_or_projection_unavailable",
                }:
                    samples.append({"status": "unavailable"})
                    break
                health = _snapshot_health(
                    snapshot, scope, datetime.now(UTC) if live_clock else now
                )
                if health != "fresh":
                    samples.append({
                        "entity_id": entity_id,
                        "status": health,
                        "reason_code": snapshot.get("reason_code") or "observation_not_current",
                    })
                    continue
                source_observed += 1
                samples.append({
                    "entity_id": entity_id,
                    "status": "fresh",
                    "snapshot": snapshot,
                })
                if candidate := _journal_anomaly(snapshot):
                    source_alerts.append(candidate)
            flags = {item["status"] for item in samples}
            if "permission_denied" in flags:
                status = "permission_denied"
                samples = []  # Never return partial records after a permission reversal.
            elif "unavailable" in flags:
                status = "unavailable"
                samples = []  # Discard an incomplete authority read.
            else:
                observed += source_observed
                alerts.extend(source_alerts)
                if "unknown" in flags:
                    status = "unknown"
                elif "stale" in flags:
                    status = "stale"
                elif not samples:
                    status = "no_visible_records"
                elif refs["has_more"] or len(refs["refs"]) > limit_per_source:
                    status = "partial_sample"
                else:
                    status = "fresh_sample"
            source_result = {"source": name, "status": status, "samples": samples}
            if status not in {"permission_denied", "unavailable"}:
                source_result["sampled_count"] = len(samples)
                source_result["has_more"] = refs["has_more"]
            elif status == "unavailable":
                source_result["reason_code"] = "authority_unavailable"
            sources.append(source_result)
            source_statuses[name] = status
        domains[code] = {
            "status": "partially_observed" if any(
                source["status"] in {"fresh_sample", "partial_sample"} for source in sources
            ) else ("not_connected" if not sources else "unknown"),
            "sources": sources,
            "required_metrics": {
                metric: {"knowledge_kind": "unknown", "reason_code": "source_not_verified"}
                for metric in _UNVERIFIED[code]
            },
        }

    domains["B09"] = {
        "status": "on_demand_only",
        "anomaly_candidates": alerts,
        "proactive_detection_verified": False,
        "candidate_delivery_verified": False,
        "business_outcome_verified": False,
    }
    domains["B10"] = {
        "status": "on_demand_checked",
        "source_statuses": source_statuses,
        "continuous_freshness_monitoring_verified": False,
    }
    return {
        "observed_at": (datetime.now(UTC) if live_clock else now).isoformat(),
        "scope": "current_actor_visible_recent_samples_not_enterprise_wide",
        "limit_per_source": limit_per_source,
        "force_refresh": force_refresh,
        "domains": domains,
        "anomaly_candidates": alerts,
        "observed_fact_count": observed,
        "observation_verified": observed > 0,
        "enterprise_wide_verified": False,
        "business_metrics_verified": False,
        "source_checks_completed": True,
        "read_only": True,
        "business_data_written": False,
    }
