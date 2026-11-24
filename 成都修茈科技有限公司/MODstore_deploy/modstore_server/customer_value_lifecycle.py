"""Six-stage customer value lifecycle aggregation."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from modstore_server.customer_value_classification import parse_datetime as _parse_datetime
from modstore_server.customer_value_classification import text as _text
from modstore_server.customer_value_release import desktop_publications, published_installation
from modstore_server.models import CustomerValueReceipt, UpdateInstallationReceipt
from modstore_server.standard_delivery_api import configured_internal_installation_ids

UTC = timezone.utc  # noqa: UP017 - MODstore CI and production still support Python 3.10
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STAGES = ("payment", "installation", "first_use", "outcome", "acceptance", "reuse")


def _receipt_evidence(row: CustomerValueReceipt | None) -> dict[str, Any]:
    if row is None:
        return {}
    try:
        parsed = json.loads(str(row.evidence_json or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _delivery_identity(row: CustomerValueReceipt | None) -> tuple[str, str] | None:
    if row is None or not row.artifact_id:
        return None
    digest = str(_receipt_evidence(row).get("artifact_sha256") or "").lower()
    return (str(row.artifact_id), digest) if _SHA256.fullmatch(digest) else None


def _same_delivery(*rows: CustomerValueReceipt | None) -> bool:
    identities = {_delivery_identity(row) for row in rows}
    return None not in identities and len(identities) == 1


def _kpi_achieved(evidence: dict[str, Any]) -> bool:
    measured, target = evidence.get("measured_value"), evidence.get("target")
    if measured is None or target is None:
        return False
    if not all(
        type(value) is int or (type(value) is float and math.isfinite(value))
        for value in (measured, target, evidence.get("baseline"))
    ):
        return False
    comparison = _text(evidence.get("comparison"), 8).lower()
    return bool(
        comparison == "ge" and measured >= target or comparison == "le" and measured <= target
    )


def build_customer_lifecycle(
    *,
    eligible_orders: dict[str, dict[str, Any]],
    verified_receipts: list[CustomerValueReceipt],
    installation_receipts: list[UpdateInstallationReceipt],
) -> dict[str, Any]:
    """Build the ordered payment-to-reuse proof without exposing identifiers."""

    publications = desktop_publications()
    latest_install_by_device: dict[tuple[int, str], UpdateInstallationReceipt] = {}
    internal_installation_ids = {
        value.casefold() for value in configured_internal_installation_ids()
    }
    for installation_row in installation_receipts:
        key = (
            int(installation_row.user_id),
            _text(installation_row.installation_id, 64),
        )
        if key[1]:
            latest_install_by_device.setdefault(key, installation_row)

    receipts_by_order: dict[str, list[CustomerValueReceipt]] = {}
    for verified_row in verified_receipts:
        if verified_row.order_no:
            receipts_by_order.setdefault(str(verified_row.order_no), []).append(verified_row)

    lifecycle_rows: list[dict[str, Any]] = []
    stage_counts: Counter[str] = Counter()
    complete_entities: set[str] = set()
    lifecycle_gaps: Counter[str] = Counter()
    for order_no, order in eligible_orders.items():
        try:
            user_id = int(order.get("user_id") or 0)
        except (TypeError, ValueError):
            user_id = 0
        entity_ref = _text(
            order.get("enterprise_subject_id")
            or order.get("business_entity_id")
            or order.get("company_tax_id"),
            256,
        )
        customer_alias = (
            "customer-" + hashlib.sha256(entity_ref.encode()).hexdigest()[:12] if entity_ref else ""
        )
        order_receipts = receipts_by_order.get(order_no, [])
        receipts_by_goal: dict[str, list[CustomerValueReceipt]] = {}
        for order_receipt in order_receipts:
            if order_receipt.customer_goal_id:
                receipts_by_goal.setdefault(str(order_receipt.customer_goal_id), []).append(
                    order_receipt
                )

        def goal_rank(rows: list[CustomerValueReceipt]) -> tuple[bool, int, datetime]:
            kinds: dict[str, CustomerValueReceipt] = {}
            for candidate in sorted(rows, key=lambda item: item.occurred_at):
                kinds.setdefault(str(candidate.receipt_kind), candidate)
            first = kinds.get("first_use")
            measured_outcome = kinds.get("outcome")
            accepted = kinds.get("acceptance")
            reused = kinds.get("reuse")
            sequence_valid = bool(
                first
                and measured_outcome
                and accepted
                and reused
                and _same_delivery(first, measured_outcome, accepted)
                and _kpi_achieved(_receipt_evidence(measured_outcome))
                and first.occurred_at <= measured_outcome.occurred_at <= accepted.occurred_at
                and accepted.occurred_at + timedelta(hours=24) <= reused.occurred_at
            )
            latest = max(
                (cast(datetime, lifecycle_row.occurred_at) for lifecycle_row in rows),
                default=datetime.min,
            )
            return sequence_valid, len(kinds), latest

        delivery_groups: list[list[CustomerValueReceipt]] = []
        for goal_rows in receipts_by_goal.values():
            shared: dict[str, CustomerValueReceipt] = {}
            by_artifact: dict[tuple[str, str], list[CustomerValueReceipt]] = {}
            for row in sorted(goal_rows, key=lambda item: item.occurred_at):
                kind = str(row.receipt_kind)
                if kind in {"first_use", "outcome", "acceptance"}:
                    identity = _delivery_identity(row)
                    if identity is not None:
                        by_artifact.setdefault(identity, []).append(row)
                elif kind in {"goal", "reuse"}:
                    shared.setdefault(kind, row)
            common = list(shared.values())
            delivery_groups.extend(common + artifact for artifact in by_artifact.values())
            if not by_artifact:
                delivery_groups.append(common)
        selected_rows = max(delivery_groups, key=goal_rank, default=[])
        by_kind: dict[str, CustomerValueReceipt] = {}
        for selected_row in sorted(selected_rows, key=lambda item: item.occurred_at):
            by_kind.setdefault(str(selected_row.receipt_kind), selected_row)

        matching_installs = [
            installation_row
            for (
                receipt_user_id,
                installation_id,
            ), installation_row in latest_install_by_device.items()
            if receipt_user_id == user_id
            and installation_id.casefold() not in internal_installation_ids
            and published_installation(installation_row, publications)
        ]
        first_use = by_kind.get("first_use")
        goal = by_kind.get("goal")
        outcome = by_kind.get("outcome")
        acceptance = by_kind.get("acceptance")
        reuse = by_kind.get("reuse")
        first_evidence = _receipt_evidence(first_use)
        outcome_evidence = _receipt_evidence(outcome)
        acceptance_evidence = _receipt_evidence(acceptance)
        reuse_evidence = _receipt_evidence(reuse)
        stages = {
            "payment": True,
            "installation": bool(user_id and matching_installs),
            "first_use": bool(
                first_use
                and first_evidence.get("success") is True
                and first_evidence.get("business_output") is True
                and _text(first_evidence.get("run_id"), 192)
                and _text(first_evidence.get("task_type"), 128).lower()
                not in {"", "login", "auth", "authentication", "session"}
            ),
            "outcome": bool(
                outcome
                and all(
                    outcome_evidence.get(key) not in (None, "")
                    for key in (
                        "baseline",
                        "target",
                        "measured_value",
                        "comparison",
                        "unit",
                        "measurement_window",
                        "source_material_summary",
                        "source_material_sha256",
                    )
                )
                and _same_delivery(first_use, outcome)
                and _kpi_achieved(outcome_evidence)
            ),
            "acceptance": bool(
                acceptance
                and _same_delivery(first_use, outcome, acceptance)
                and (
                    acceptance_evidence.get("customer_confirmed") is True
                    or _SHA256.fullmatch(
                        _text(acceptance_evidence.get("signed_document_sha256"), 64).lower()
                    )
                )
            ),
            "reuse": False,
        }
        if reuse and acceptance and first_use:
            accepted_at = acceptance.occurred_at.replace(tzinfo=UTC)
            reused_at = reuse.occurred_at.replace(tzinfo=UTC)
            stages["reuse"] = bool(
                reuse_evidence.get("success") is True
                and reuse_evidence.get("business_output") is True
                and _text(reuse_evidence.get("run_id"), 192)
                and _text(reuse_evidence.get("task_type"), 128).lower()
                not in {"", "login", "auth", "authentication", "session"}
                and _text(reuse_evidence.get("run_id"), 192)
                != _text(first_evidence.get("run_id"), 192)
                and reused_at >= accepted_at + timedelta(hours=24)
            )
        for stage, passed in stages.items():
            if passed:
                stage_counts[stage] += 1
            else:
                lifecycle_gaps[stage] += 1
        paid_at = _parse_datetime(order.get("paid_at"))
        install_times = [
            installation_row.reported_at.replace(tzinfo=UTC)
            for installation_row in matching_installs
            if installation_row.reported_at
        ]
        same_goal = bool(
            first_use
            and outcome
            and acceptance
            and reuse
            and len(
                {
                    first_use.customer_goal_id,
                    outcome.customer_goal_id,
                    acceptance.customer_goal_id,
                    reuse.customer_goal_id,
                }
            )
            == 1
        )
        ordered = bool(
            paid_at
            and install_times
            and first_use
            and goal
            and outcome
            and acceptance
            and reuse
            and same_goal
            and _same_delivery(first_use, outcome, acceptance)
            and goal.occurred_at <= first_use.occurred_at
            and any(
                paid_at <= installed_at <= first_use.occurred_at.replace(tzinfo=UTC)
                for installed_at in install_times
            )
            and first_use.occurred_at <= outcome.occurred_at <= acceptance.occurred_at
            and acceptance.occurred_at + timedelta(hours=24) <= reuse.occurred_at
        )
        if not ordered:
            lifecycle_gaps["sequence"] += 1
        complete = bool(entity_ref and ordered and all(stages.values()))
        if complete:
            complete_entities.add(entity_ref)
        lifecycle_rows.append(
            {
                "customer_alias": customer_alias or "unverified-enterprise-subject",
                "stages": stages,
                "ordered": ordered,
                "complete": complete,
                "gaps": [stage for stage, passed in stages.items() if not passed]
                + ([] if ordered else ["sequence"])
                + ([] if entity_ref else ["enterprise_subject"]),
            }
        )

    return {
        "lifecycle_schema": "customer_value_lifecycle/v3",
        "desktop_release_source": publications["source"],
        "desktop_release_source_available": publications["available"],
        "six_stage_counts": {stage: int(stage_counts.get(stage, 0)) for stage in _STAGES},
        "complete_customer_count": len(complete_entities),
        "complete_customer_target": 3,
        "three_customer_loop_verified": len(complete_entities) >= 3,
        "lifecycle_gaps": dict(sorted(lifecycle_gaps.items())),
        "customers": lifecycle_rows,
    }
