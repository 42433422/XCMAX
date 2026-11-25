"""Read-only self metrics from the existing lifecycle and billing journals.

Cost denotes verified tariff accrual, never an invoice. A cycle finishing is
not proof of business success or independently evaluated model capability.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any, Callable

from modstore_server.xiaoc_life_policy import parse_time


def _partition_cycle_receipts(
    events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[str]]:
    """Quarantine conflicting originals instead of picking a convenient duplicate."""
    originals: dict[str, dict[str, Any]] = {}
    conflicts: set[str] = set()
    for event in events:
        if not isinstance(event, dict):
            continue
        key = event.get("id")
        if not isinstance(key, str) or not key.startswith("cycle:"):
            continue
        previous = originals.setdefault(key, event)
        if previous != event:
            conflicts.add(key)
    return [row for key, row in originals.items() if key not in conflicts], conflicts


def consistent_cycle_receipts(
    events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    rows, conflicts = _partition_cycle_receipts(events)
    return rows, len(conflicts)


def completion_review(scope: str | None, events: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare disjoint samples for the SAME scope, model and lifecycle domain."""
    groups: dict[tuple[str, str], list[tuple[Any, str, bool]]] = defaultdict(list)
    excluded = 0
    consistent, conflicting = consistent_cycle_receipts(events)
    for event in consistent:
        key = event["id"]
        if not scope or event.get("details", {}).get("execution_scope") != scope:
            continue
        model, domain = event.get("model"), event.get("kind")
        if (
            not model
            or not isinstance(model, str)
            or not isinstance(domain, str)
            or event.get("status") not in {"completed", "failed"}
            or type(event.get("actual_tokens")) is not int
            or event["actual_tokens"] < 0
        ):
            excluded += 1
            continue
        try:
            timestamp = parse_time(event["created_at"])
        except (KeyError, TypeError, ValueError, AttributeError):
            excluded += 1
            continue
        groups[domain, model].append((timestamp, key, event["status"] == "completed"))
    samples = []
    for (domain, model), rows in sorted(groups.items()):
        rows.sort(reverse=True)
        item: dict[str, Any] = {
            "domain": domain,
            "model": model,
            "sample_count": len(rows),
            "status": "insufficient_evidence",
        }
        if len(rows) >= 20:
            recent, baseline = rows[:10], rows[10:20]
            recent_rate = sum(row[2] for row in recent) / 10
            baseline_rate = sum(row[2] for row in baseline) / 10
            item.update(
                status=(
                    "observed_completion_drop"
                    if recent_rate <= baseline_rate - 0.2 + 1e-9
                    else "no_threshold_drop_observed"
                ),
                recent_completion_rate=recent_rate,
                baseline_completion_rate=baseline_rate,
                recent_refs=[row[1] for row in recent],
                baseline_refs=[row[1] for row in baseline],
            )
        samples.append(item)
    return {
        "measurement": "cycle_completion_observation_not_capability_test",
        "threshold": 0.2,
        "samples_per_window": 10,
        "excluded_unmeasured": excluded,
        "conflicting_cycle_receipts": conflicting,
        "groups": samples,
        "status": (
            "review_recommended"
            if conflicting or any(row["status"] == "observed_completion_drop" for row in samples)
            else (
                "no_drop_observed"
                if any(row["status"] == "no_threshold_drop_observed" for row in samples)
                else "insufficient_evidence"
            )
        ),
    }


def _call_key(step: dict[str, Any], owner: int) -> tuple[int, str, str, str] | None:
    request = step.get("request_id")
    decision, opportunity = step.get("decision_id", ""), step.get("opportunity_id", "")
    if (
        not isinstance(request, str)
        or not request
        or not isinstance(decision, str)
        or not isinstance(opportunity, str)
        or bool(decision) != bool(opportunity)
        or type(step.get("owner_user_id", owner)) is not int
        or step.get("owner_user_id", owner) != owner
    ):
        return None
    return owner, decision, opportunity, request


def accrual_projection(
    scope: str | None,
    events: list[dict[str, Any]],
    read_call: Callable[[tuple[int, str, str, str]], dict[str, Any] | None],
) -> dict[str, Any]:
    """Require exact original requests and a complete token reconciliation.

    A request appearing in two cycle journals is ambiguous for both cycles.
    Never substitute a reservation, portfolio total, or estimate for accrual.
    """
    cycles: dict[str, tuple[list[tuple[int, str, str, str]], int] | None] = {}
    owners: dict[tuple[int, str, str, str], set[str]] = defaultdict(set)
    consistent, conflicts = _partition_cycle_receipts(events)
    # Check ownership collisions even in historical or incomplete journals.
    for event in events:
        if not isinstance(event, dict):
            continue
        cycle_id = event.get("id")
        details = event.get("details") or {}
        if not isinstance(details, dict):
            continue
        if (
            scope
            and isinstance(cycle_id, str)
            and cycle_id in conflicts
            and details.get("execution_scope") == scope
        ):
            cycles[cycle_id] = None
        owner = details.get("owner_user_id")
        if (
            not isinstance(cycle_id, str)
            or not cycle_id.startswith("cycle:")
            or type(owner) is not int
            or owner <= 0
            or not isinstance(details.get("steps"), list)
        ):
            continue
        for step in details["steps"]:
            if isinstance(step, dict) and step.get("kind") == "model":
                call_key = _call_key(step, owner)
                if call_key is not None:
                    owners[call_key].add(cycle_id)
    for event in consistent:
        key = event.get("id")
        if not isinstance(key, str) or not key.startswith("cycle:") or key in cycles:
            continue
        details = event.get("details") or {}
        if not scope or details.get("execution_scope") != scope:
            continue
        actual, owner = event.get("actual_tokens"), details.get("owner_user_id")
        steps = details.get("steps")
        if (
            type(actual) is not int
            or actual < 0
            or type(owner) is not int
            or owner <= 0
            or details.get("outbound_journal_version") != 1
            or not isinstance(steps, list)
        ):
            cycles[key] = None
            continue
        keys: list[tuple[int, str, str, str]] = []
        valid = True
        for step in steps:
            if not isinstance(step, dict) or step.get("kind") not in {"model", "portfolio"}:
                valid = False
                break
            if step["kind"] == "portfolio":
                continue
            call_key = _call_key(step, owner)
            if call_key is None:
                valid = False
                break
            if call_key not in keys:
                keys.append(call_key)
        # A portfolio journal without model IDs cannot prove its usage or cost.
        if not valid or (not keys and (actual != 0 or steps)):
            cycles[key] = None
        else:
            cycles[key] = (keys, actual)

    known: dict[str, int] = {}
    unknown = []
    for cycle_id, entry in cycles.items():
        if entry is None:
            unknown.append(cycle_id)
            continue
        keys, actual = entry
        if any(len(owners[key]) != 1 for key in keys):
            unknown.append(cycle_id)
            continue
        calls = [read_call(key) for key in keys]
        if any(
            not isinstance(row, dict)
            or row.get("status") != "settled"
            or type(row.get("actual_tokens")) is not int
            or row["actual_tokens"] < 0
            or type(row.get("accrued_cost_cents")) is not int
            or row["accrued_cost_cents"] < 0
            or row.get("cost_basis")
            not in {"approved_company_tariff_accrual", "approved_tariff_accrual"}
            for row in calls
        ):
            unknown.append(cycle_id)
            continue
        settled = [row for row in calls if row is not None]
        if sum(row["actual_tokens"] for row in settled) != actual:
            unknown.append(cycle_id)
            continue
        known[cycle_id] = sum(row["accrued_cost_cents"] for row in settled)
    return {
        "basis": "approved_tariff_accrual_not_supplier_invoice",
        "known_accrued_cents": sum(known.values()) if known else None,
        "cost_cents": sum(known.values()) if known and not unknown else None,
        "known_cycle_count": len(known),
        "unknown_cycle_count": len(unknown),
        "known_cycle_refs": list(known),
        "unknown_cycle_refs": unknown,
        "supplier_cost_cents": None,
        "supplier_cost_status": "unknown_no_supplier_invoice",
        "conflicting_cycle_count": sum(key in conflicts for key in cycles),
        "status": "partial" if known and unknown else "measured" if known else "unknown",
    }


def with_cycle_receipts(state: dict[str, Any]) -> dict[str, Any]:
    """Bounded original cycle-only history; omit raw prompt and customer text."""
    from sqlalchemy import select
    from sqlalchemy.exc import SQLAlchemyError

    from modstore_server.db.db_base import get_session_factory
    from modstore_server.db.xiaoc_life import XiaoCLifeEvent
    from modstore_server.xiaoc_life_policy import IDENTITY_ID
    from modstore_server.xiaoc_self_model import execution_scope

    if execution_scope(state) is None:
        return {**state, "self_metrics_source": "current_scope_unverified"}
    try:
        with get_session_factory()() as session:
            rows = session.scalars(
                select(XiaoCLifeEvent)
                .where(
                    XiaoCLifeEvent.identity_id == IDENTITY_ID,
                    XiaoCLifeEvent.id.startswith("cycle:"),
                )
                .order_by(XiaoCLifeEvent.created_at.desc(), XiaoCLifeEvent.id.desc())
                .limit(80)
            ).all()
            events = []
            for row in rows:
                details = json.loads(row.details_json)
                steps = details.get("steps")
                sanitized_steps = (
                    [
                        (
                            {
                                key: step[key]
                                for key in (
                                    "kind",
                                    "request_id",
                                    "owner_user_id",
                                    "decision_id",
                                    "opportunity_id",
                                )
                                if key in step
                            }
                            if isinstance(step, dict)
                            else {}
                        )
                        for step in steps
                    ]
                    if isinstance(steps, list)
                    else None
                )
                events.append(
                    {
                        "id": row.id,
                        "kind": row.kind,
                        "status": row.status,
                        "model": row.model,
                        "actual_tokens": row.actual_tokens,
                        "created_at": (
                            row.created_at.isoformat()
                            if row.created_at.tzinfo
                            else row.created_at.isoformat() + "+00:00"
                        ),
                        "details": {
                            "execution_scope": details.get("execution_scope"),
                            "owner_user_id": details.get("owner_user_id"),
                            "outbound_journal_version": details.get("outbound_journal_version"),
                            "reason": details.get("reason"),
                            "steps": sanitized_steps,
                        },
                    }
                )
    except (SQLAlchemyError, OSError, ValueError, TypeError, AttributeError):
        return {
            **state,
            "self_cycle_receipts": [],
            "self_metrics_source": "original_cycle_receipts_unavailable",
        }
    return {
        **state,
        "self_cycle_receipts": events,
        "self_metrics_source": "recent_80_original_cycle_receipts",
    }


def read_accrual(state: dict[str, Any]) -> dict[str, Any]:
    """Re-read original SQL and portfolio call identities, with no model traffic."""
    from sqlalchemy import select
    from sqlalchemy.exc import SQLAlchemyError

    from modstore_server.db.db_base import get_session_factory
    from modstore_server.db.llm_chat import LlmClientRequest
    from modstore_server.strategic_portfolio import PortfolioError, portfolio_status
    from modstore_server.xiaoc_self_model import execution_scope

    events = state.get("self_cycle_receipts", state.get("events", []))
    portfolios: dict[tuple[int, str], dict[str, Any]] = {}

    def read_call(key: tuple[int, str, str, str]) -> dict[str, Any] | None:
        owner, decision, opportunity, request = key
        try:
            if decision:
                cache_key = owner, decision
                if cache_key not in portfolios:
                    portfolios[cache_key] = portfolio_status(decision, owner_user_id=owner)
                record = portfolios[cache_key]
                if record.get("owner_user_id") != owner or record.get("decision_id") != decision:
                    return None
                found = record.get("tasks", {}).get(opportunity, {}).get("calls", {}).get(request)
                return found if isinstance(found, dict) else None
            with get_session_factory()() as session:
                row = session.scalar(
                    select(LlmClientRequest).where(
                        LlmClientRequest.user_id == owner,
                        LlmClientRequest.client_request_id == request,
                    )
                )
                if row is None or row.state != "completed":
                    return None
                parsed = json.loads(row.done_json or "{}")
                if not isinstance(parsed, dict):
                    return None
                if parsed.get("request_id") != request or parsed.get("owner_user_id") != owner:
                    return None
                return parsed
        except (PortfolioError, SQLAlchemyError, ValueError, OSError):
            return None

    return accrual_projection(execution_scope(state), events, read_call)


def audit_projection() -> dict[str, Any]:
    """Use the original 18-domain SSOT. A catalog anchor is not a passing test."""
    from modstore_server import strategy_bets, strategy_planner

    try:
        path = strategy_bets.repo_root() / "FHD/config/audit_benchmark_ssot.json"
        raw = path.read_bytes()
        catalog = json.loads(raw)
        domains = catalog["domains"]
        items = []
        for domain in domains:
            anchors = domain["anchor_60"] + domain["anchor_90"]
            for anchor in anchors:
                items.append(
                    {
                        "domain_id": domain["id"],
                        "anchor_id": anchor["id"],
                        "status": "unverified",
                    }
                )
        if (
            len(domains) != 18
            or len(items) != 108
            or len(domains) != catalog["domain_count"]
            or len({row["id"] for row in domains}) != len(domains)
            or len({row["anchor_id"] for row in items}) != len(items)
        ):
            raise ValueError("invalid_audit_catalog")
        history = strategy_planner._domain_status()
        statuses = {
            row["domain_id"]: {
                "status": row["status"],
                "audited_at": row.get("audited_at"),
                "interpretation": "historical_domain_summary_not_anchor_proof",
            }
            for row in history.get("domains", [])
        }
    except (OSError, ValueError, TypeError, KeyError):
        return {"status": "unknown", "reason": "audit_source_unavailable"}
    return {
        "status": "catalog_only",
        "standard_version": catalog["standard_version"],
        "scoring_version": catalog["scoring_version"],
        "standard_sha256": hashlib.sha256(raw).hexdigest(),
        "checksum_meaning": "catalog_identity_only_not_independent_approval",
        "domain_count": len(domains),
        "anchor_count": len(items),
        "anchors": items,
        "historical_domains": statuses,
    }
