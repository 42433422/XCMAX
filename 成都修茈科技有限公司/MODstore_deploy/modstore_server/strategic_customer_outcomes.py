"""Bind strategy to existing customer agreements, delivered bytes and real acceptance.

SQLAlchemy and CustomerValueReceipt remain the evidence store. No strategy actor
can manufacture customer consent, payment or measured business outcomes here.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from modstore_server.db.customer_value import CustomerValueReceipt

VERIFIED_DELIVERY_ATTRIBUTION = "approved_customer_goal_order_completed_artifact_and_verified_acceptance_not_incremental_causality"
KNOWN_DELIVERY_ATTRIBUTIONS = frozenset(
    {
        VERIFIED_DELIVERY_ATTRIBUTION,
        "same_owner_completed_task_artifact_and_verified_acceptance_with_order_outcome_not_incremental_causality",
    }
)


class CustomerGoalBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    customer_goal_id: str = Field(min_length=1, max_length=128)
    customer_ref: str = Field(pattern=r"^paid-user:[1-9][0-9]*$")
    order_no: str = Field(min_length=1, max_length=96)
    receipt_id: str = Field(min_length=1, max_length=96)
    goal_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def load_customer_goal_bindings(
    customer_user_id: int, order_no: str, goal_ids: list[str]
) -> list[dict[str, str]]:
    """Select original customer-confirmed agreements, never the operator's account."""
    from modstore_server.db.db_base import get_session_factory
    from modstore_server.strategic_portfolio import PortfolioError

    now = datetime.now(UTC)
    customer = f"paid-user:{customer_user_id}"
    with get_session_factory()() as session:
        refunds = session.scalar(
            select(CustomerValueReceipt.id)
            .where(
                CustomerValueReceipt.customer_ref == customer,
                CustomerValueReceipt.order_no == order_no,
                CustomerValueReceipt.receipt_kind == "refund",
                CustomerValueReceipt.verification_status == "verified",
                CustomerValueReceipt.environment.in_(("production", "prod")),
                CustomerValueReceipt.occurred_at <= now,
            )
            .limit(1)
        )
        rows = session.scalars(
            select(CustomerValueReceipt)
            .where(
                CustomerValueReceipt.customer_ref == customer,
                CustomerValueReceipt.order_no == order_no,
                CustomerValueReceipt.customer_goal_id.in_(goal_ids),
                CustomerValueReceipt.receipt_kind == "goal",
                CustomerValueReceipt.verification_status == "verified",
                CustomerValueReceipt.environment.in_(("production", "prod")),
                CustomerValueReceipt.occurred_at <= now,
            )
            .order_by(CustomerValueReceipt.occurred_at.desc(), CustomerValueReceipt.id.desc())
        ).all()
        selected: dict[str, dict[str, str]] = {}
        for row in rows:
            selected.setdefault(
                str(row.customer_goal_id),
                {
                    "customer_goal_id": str(row.customer_goal_id),
                    "customer_ref": str(row.customer_ref),
                    "order_no": str(row.order_no),
                    "receipt_id": str(row.receipt_id),
                    "goal_evidence_sha256": str(row.evidence_digest),
                },
            )
    if refunds or set(selected) != set(goal_ids) or len(goal_ids) != len(set(goal_ids)):
        raise PortfolioError("customer agreement missing, refunded or ambiguous")
    return [selected[key] for key in goal_ids]


def validate_customer_goal_bindings(opportunity: dict[str, Any]) -> None:
    """Re-resolve exact agreed identities before the immutable proposal is approved."""
    from modstore_server.strategic_portfolio import PortfolioError

    bindings = opportunity.get("customer_goal_bindings") or []
    if not bindings:
        return
    if {row["customer_goal_id"] for row in bindings} != set(opportunity["customer_goal_ids"]):
        raise PortfolioError("customer agreement bindings must cover the approved goals")
    for raw in bindings:
        row = CustomerGoalBinding.model_validate(raw).model_dump()
        current = load_customer_goal_bindings(
            int(row["customer_ref"].split(":")[1]), row["order_no"], [row["customer_goal_id"]]
        )
        if current != [row]:
            raise PortfolioError("customer agreement changed; rediscover before approval")


def execution_artifacts(value: Any, depth: int = 0) -> set[tuple[str, str]]:
    if depth > 10:
        return set()
    found: set[tuple[str, str]] = set()
    if isinstance(value, dict):
        artifact, evidence = value.get("artifact_id"), value.get("evidence")
        sha = value.get("artifact_sha256") or (
            evidence.get("artifact_sha256") if isinstance(evidence, dict) else None
        )
        if (
            isinstance(artifact, str)
            and artifact
            and isinstance(sha, str)
            and re.fullmatch(r"[0-9a-fA-F]{64}", sha)
        ):
            found.add((artifact, sha.lower()))
        for item in value.values():
            found.update(execution_artifacts(item, depth + 1))
    elif isinstance(value, list):
        for item in value[:100]:
            found.update(execution_artifacts(item, depth + 1))
    return found


def attach_local_delivery_artifacts(task: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Hash actual native file outputs inside the frozen tenant workspace at completion."""
    from modstore_server.employee_path_guard import _extract_changed_files_from_output
    from modstore_server.integrations.vibe_adapter import ensure_within_workspace
    from modstore_server.strategic_execution_receipts import evaluate_execution_receipt
    from modstore_server.strategic_portfolio import digest

    if (
        not task.get("customer_goal_ids")
        or evaluate_execution_receipt(result).status != "completed"
    ):
        return result
    inner = result.get("result") or {}
    if not isinstance(inner, dict):
        return result
    outputs = inner.get("outputs") or []
    paths: set[str] = set()

    for output in outputs if isinstance(outputs, list) else []:
        if (
            isinstance(output, dict)
            and output.get("handler") == "direct_python"
            and output.get("ok") is True
        ):
            paths.update(_extract_changed_files_from_output(output))
    if not paths:
        return result
    artifacts: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    root = Path(task["input_data"]["workspace_root"]).resolve()
    for raw in sorted(paths):
        if len(artifacts) >= 32:
            break
        try:
            path = ensure_within_workspace(
                str(Path(raw) if Path(raw).is_absolute() else root / raw),
                user_id=task["owner_user_id"],
            )
            relative = path.relative_to(root).as_posix()
            # Native receipts may contain both the original absolute output and
            # the verified relative files_changed entry for those same bytes.
            if relative in seen:
                continue
            if not path.is_file() or path.stat().st_size > 64_000_000:
                raise ValueError("output file missing or exceeds artifact hashing limit")
            with path.open("rb") as stream:
                sha = hashlib.file_digest(stream, "sha256").hexdigest()
            seen.add(relative)
            artifacts.append(
                {
                    "artifact_id": "strategy-file-"
                    + digest([task["decision_id"], task["opportunity_id"], relative])[:40],
                    "artifact_sha256": sha,
                    "output_path": relative,
                    "source": "native_direct_python_tenant_output",
                }
            )
        except (OSError, ValueError) as exc:
            errors.append(type(exc).__name__)
    return {**result, "delivered_artifacts": artifacts, "delivery_artifact_errors": errors}


def customer_delivery_evidence(
    status: dict[str, Any], *, start: datetime, end: datetime, currency: str | None = "CNY"
) -> dict[str, Any]:
    """Match a completed artifact to the exact approved customer, goal and order."""
    from modstore_server.customer_value_lifecycle import _receipt_evidence
    from modstore_server.db.db_base import get_session_factory
    from modstore_server.strategic_portfolio import _date, digest
    from modstore_server.strategy_bets import _number, judge

    # None order preserves previously approved, same-owner portfolios only.
    delivered: dict[tuple[str, str, str | None], dict[tuple[str, str], datetime]] = {}
    targets: set[tuple[str, str, str | None]] = set()
    agreements: dict[tuple[str, str, str | None], str] = {}
    agreement_digests: dict[tuple[str, str, str | None], str] = {}
    missing = False
    for item in status["opportunities"]:
        agreements.update(
            {
                (row["customer_goal_id"], row["customer_ref"], row["order_no"]): row["receipt_id"]
                for row in item.get("customer_goal_bindings") or []
            }
        )
        for row in item.get("customer_goal_bindings") or []:
            identity = (row["customer_goal_id"], row["customer_ref"], row["order_no"])
            prior = agreement_digests.get(identity)
            if prior is not None and prior != row["goal_evidence_sha256"]:
                missing = True
            agreement_digests[identity] = row["goal_evidence_sha256"]
        identities = [
            (row["customer_goal_id"], row["customer_ref"], row["order_no"])
            for row in item.get("customer_goal_bindings") or []
        ] or [
            (goal, f"paid-user:{status['owner_user_id']}", None)
            for goal in item["customer_goal_ids"]
        ]
        targets.update(identities)
        task = status.get("tasks", {}).get(item["opportunity_id"], {})
        if task.get("status") != "completed":
            continue
        artifacts = execution_artifacts(task.get("execution_receipt"))
        if identities and (not artifacts or not task.get("completed_at")):
            missing = True
            continue
        for identity in identities:
            bucket = delivered.setdefault(identity, {})
            for artifact in artifacts:
                moment = _date(task["completed_at"])
                bucket[artifact] = min(bucket.get(artifact, moment), moment)
    pairs: dict[tuple[str, str, str, str, str], set[str]] = {}
    evidence = []
    with get_session_factory()() as session:
        goal_evidence = {}
        verified_agreements = set()
        for row in session.scalars(
            select(CustomerValueReceipt).where(
                CustomerValueReceipt.receipt_id.in_(agreements.values()),
                CustomerValueReceipt.receipt_kind == "goal",
                CustomerValueReceipt.verification_status == "verified",
                CustomerValueReceipt.environment.in_(("production", "prod")),
                CustomerValueReceipt.occurred_at <= start,
            )
        ):
            identity = (str(row.customer_goal_id), str(row.customer_ref), str(row.order_no))
            if (
                agreements.get(identity) == str(row.receipt_id)
                and agreement_digests.get(identity) == str(row.evidence_digest)
            ):
                verified_agreements.add(identity)
                goal_evidence[str(row.receipt_id)] = _receipt_evidence(row)
                evidence.append((str(row.receipt_id), str(row.evidence_digest)))
        if set(agreements) != verified_agreements:
            missing = True
        receipts = session.scalars(
            select(CustomerValueReceipt).where(
                CustomerValueReceipt.verification_status == "verified",
                CustomerValueReceipt.customer_ref.in_({row[1] for row in targets}),
                CustomerValueReceipt.customer_goal_id.in_({row[0] for row in targets}),
                CustomerValueReceipt.receipt_kind.in_(("outcome", "acceptance")),
                CustomerValueReceipt.environment.in_(("production", "prod")),
                CustomerValueReceipt.occurred_at >= start,
                CustomerValueReceipt.occurred_at <= end,
            )
        ).all()
        for receipt in receipts:
            if currency and receipt.currency != currency:
                continue
            try:
                body = json.loads(str(receipt.evidence_json) or "{}")
            except (ValueError, TypeError):
                continue
            if not isinstance(body, dict):
                continue
            artifact = (str(receipt.artifact_id), str(body.get("artifact_sha256") or "").lower())
            exact = (
                str(receipt.customer_goal_id),
                str(receipt.customer_ref),
                str(receipt.order_no),
            )
            identity = exact if exact in delivered else (*exact[:2], None)
            completed = delivered.get(identity, {}).get(artifact)
            occurred = receipt.occurred_at.replace(tzinfo=UTC)
            if completed is None or occurred < max(start, completed):
                continue
            if identity in agreements:
                if identity not in verified_agreements:
                    continue
                if receipt.receipt_kind == "outcome":
                    agreed = goal_evidence.get(agreements[identity], {})
                    fields = ("baseline", "target", "comparison", "unit", "measurement_window")
                    if not agreed or any(body.get(key) != agreed.get(key) for key in fields):
                        continue
                    direction = {"ge": "max", "le": "min"}.get(str(agreed.get("comparison")), "")
                    threshold = _number(agreed.get("target"))
                    if (
                        threshold is None
                        or judge("customer_goal", body.get("measured_value"), threshold, direction)
                        != "hit"
                    ):
                        continue
                elif body.get("customer_confirmed") is not True and not re.fullmatch(
                    r"[0-9a-fA-F]{64}", str(body.get("signed_document_sha256") or "")
                ):
                    continue
            pairs.setdefault((*exact, *artifact), set()).add(str(receipt.receipt_kind))
            evidence.append((str(receipt.receipt_id), str(receipt.evidence_digest)))
        refunds = session.scalars(
            select(CustomerValueReceipt).where(
                CustomerValueReceipt.verification_status == "verified",
                CustomerValueReceipt.receipt_kind == "refund",
                CustomerValueReceipt.customer_ref.in_({row[1] for row in targets}),
                CustomerValueReceipt.order_no.in_({row[2] for row in pairs if row[2]}),
                CustomerValueReceipt.environment.in_(("production", "prod")),
                CustomerValueReceipt.occurred_at <= end,
            )
        ).all()
        refunded = {
            (str(row.customer_ref), str(row.order_no))
            for row in refunds
            if not currency or row.currency == currency
        }
        evidence.extend((str(row.receipt_id), str(row.evidence_digest)) for row in refunds)
    accepted = {
        key[:3]
        for key, kinds in pairs.items()
        if kinds == {"outcome", "acceptance"} and (key[1], key[2]) not in refunded
    }
    accepted_targets = {exact if exact in targets else (*exact[:2], None) for exact in accepted}
    return {
        "missing_attribution": missing,
        "target_count": len(targets),
        "delivered_count": sum(bool(delivered.get(key)) for key in targets),
        "accepted_count": len(accepted_targets),
        "accepted_orders": {(key[1], key[2]) for key in accepted},
        "evidence_sha256": digest(
            {
                "receipts": sorted(evidence),
                "targets": sorted(targets),
                "deliveries": sorted((str(key), sorted(value)) for key, value in delivered.items()),
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
            }
        ),
    }


def customer_acceptance_outcome(
    status: dict[str, Any], *, window_start: datetime, window_end: datetime
) -> dict[str, Any]:
    evidence = customer_delivery_evidence(status, start=window_start, end=window_end, currency=None)
    count = evidence["target_count"]
    known = (
        bool(count) and not evidence["missing_attribution"] and evidence["delivered_count"] == count
    )
    return {
        "status": "verified" if known else "unknown",
        "reason": "" if known else "executed_customer_delivery_attribution_missing",
        "source": "CustomerValueReceipt:verified_outcome_and_customer_acceptance",
        "acceptance_ratio": evidence["accepted_count"] / count if known else None,
        "accepted_goals": evidence["accepted_count"],
        "target_goals": count,
        "evidence_sha256": evidence["evidence_sha256"],
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "attribution": "approved_customer_goal_order_and_completed_artifact_not_causal_uplift",
    }
