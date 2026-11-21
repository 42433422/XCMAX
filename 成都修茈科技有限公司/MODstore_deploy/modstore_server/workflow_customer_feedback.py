"""Mature actual owned file deliveries against original customer KPI and acceptance.

The original execution/outbox and append-only customer receipts are authoritative.
Each result is frozen once; late refunds stop traffic without rewriting history.
"""

from __future__ import annotations

from datetime import UTC

from fastapi import HTTPException
from sqlalchemy import select, update

from modstore_server.customer_service_tools import json_loads
from modstore_server.customer_value_classification import parse_datetime
from modstore_server.db.customer_value import CustomerValueReceipt
from modstore_server.eventing.db_outbox import enqueue
from modstore_server.models import (
    OutboxEvent,
    RetortEvolutionRun,
    WorkflowExecution,
    get_session_factory,
)
from modstore_server.retort_experiment_surfaces import WORKFLOW_CUSTOMER_MEASUREMENT
from modstore_server.workflow_nl_training import _digest


def _bindings(db, request_id):
    from modstore_server.workflow_execution_feedback import START_EVENT

    with db.scalars(
        select(OutboxEvent)
        .where(
            OutboxEvent.event_name == START_EVENT,
            OutboxEvent.payload_json.contains(request_id, autoescape=True),
        )
        .order_by(OutboxEvent.id)
    ).yield_per(32) as rows:
        for row in rows:
            value = json_loads(row.payload_json, {})
            assignment = value.get("assignment") or {}
            if (
                assignment.get("request_id") == request_id
                and assignment.get("measurement_scope") == WORKFLOW_CUSTOMER_MEASUREMENT
                and value.get("customer_delivery")
            ):
                yield value


def _refunds(db, goal):
    return list(
        db.scalars(
            select(CustomerValueReceipt).where(
                CustomerValueReceipt.customer_ref == goal["customer_ref"],
                CustomerValueReceipt.order_no == goal["order_no"],
                CustomerValueReceipt.receipt_kind == "refund",
                CustomerValueReceipt.verification_status == "verified",
                CustomerValueReceipt.environment.in_(("production", "prod")),
            )
        )
    )


def customer_stop_reason(db, request_id, spec):
    if (spec.get("lifecycle") or {}).get("measurement_scope") != WORKFLOW_CUSTOMER_MEASUREMENT:
        return ""
    from modstore_server import retort_experiment_runtime as runtime

    now = runtime.datetime.now(UTC)
    for binding in _bindings(db, request_id):
        goal = binding["customer_delivery"]["goal"]
        if any(parse_datetime(row.occurred_at) <= now for row in _refunds(db, goal)):
            return "workflow_customer_refunded"
    return ""


def _refund_references(db, request_id):
    from modstore_server import retort_experiment_runtime as runtime

    references = []
    for binding in _bindings(db, request_id):
        contract = binding["customer_delivery"]
        for receipt in _refunds(db, contract["goal"]):
            if parse_datetime(receipt.occurred_at) <= runtime.datetime.now(UTC):
                references.append(
                    {
                        "execution_id": binding["execution_id"],
                        "contract_sha256": contract["contract_sha256"],
                        "refund_receipt_id": receipt.receipt_id,
                        "refund_evidence_sha256": receipt.evidence_digest,
                    }
                )
    return references


def request_customer_refund_rechecks():
    """The original scheduler re-enters only the existing impact/recovery tail."""
    from modstore_server import retort_experiment_runtime as runtime
    from modstore_server.customer_service_tools import json_dumps
    from modstore_server.retort_feedback_experiments import approved_policy

    count = 0
    with get_session_factory()() as db:
        with db.scalars(
            select(RetortEvolutionRun).where(
                RetortEvolutionRun.status == "completed",
                RetortEvolutionRun.effects_json.contains(
                    WORKFLOW_CUSTOMER_MEASUREMENT, autoescape=True
                ),
            )
        ).yield_per(32) as rows:
            for row in rows:
                try:
                    _spec, effects = approved_policy(row)
                except ValueError:
                    continue
                references = _refund_references(db, row.id)
                if not references:
                    continue
                effects["customer_outcome_recheck"] = {
                    "reason": "verified_customer_refund",
                    "references": references,
                    "evidence_sha256": _digest(references),
                }
                changed = db.execute(
                    update(RetortEvolutionRun)
                    .where(
                        RetortEvolutionRun.id == row.id,
                        RetortEvolutionRun.status == "completed",
                        RetortEvolutionRun.effects_json == row.effects_json,
                    )
                    .values(
                        status="impact_recheck",
                        effects_json=json_dumps(effects),
                        updated_at=runtime.datetime.now(UTC),
                    )
                )
                count += int(changed.rowcount == 1)
        db.commit()
    return count


def customer_refund_impact(request_id, state):
    from modstore_server import retort_experiment_runtime as runtime
    from modstore_server.retort_feedback_experiments import approved_policy

    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, request_id)
        effects = json_loads(row.effects_json, {}) if row else {}
        policy = (effects.get("customer_feedback") or effects.get("training_candidate") or {}).get(
            "growthbook"
        ) or {}
        if (policy.get("lifecycle") or {}).get(
            "measurement_scope"
        ) != WORKFLOW_CUSTOMER_MEASUREMENT:
            return None
        spec, _effects = approved_policy(row)
        if not customer_stop_reason(db, request_id, spec):
            return None
        references = _refund_references(db, request_id)
    return {
        "status": "customer_impact_rejected",
        "reason": "verified_customer_refund",
        "source": "original_workflow_customer_refund",
        "evidence_sha256": _digest(references),
        "release_sha": state["delivery"].get("release_sha"),
        "verified_at": runtime.datetime.now(UTC).isoformat(),
    }


def _current_goal(db, contract):
    from modstore_server.customer_value_lifecycle_api import _authoritative_order
    from modstore_server.strategic_customer_outcomes import load_customer_goal_bindings

    goal = contract["goal"]
    _authoritative_order(goal["order_no"], contract["user_id"])
    current = load_customer_goal_bindings(
        contract["user_id"], goal["order_no"], [goal["customer_goal_id"]]
    )
    if current != [goal]:
        raise ValueError("workflow_customer_agreement_changed")
    row = db.scalar(
        select(CustomerValueReceipt).where(CustomerValueReceipt.receipt_id == goal["receipt_id"])
    )
    if row is None or row.evidence_digest != goal["goal_evidence_sha256"]:
        raise ValueError("workflow_customer_agreement_unavailable")
    return json_loads(row.evidence_json, {})


def _measured(db, execution, binding, due):
    from modstore_server.strategy_bets import _number, judge
    from modstore_server.workflow_customer_delivery import load_completed_delivery

    contract = binding["customer_delivery"]
    agreed = _current_goal(db, contract)
    if execution.status == "failed":
        return (
            False,
            _digest({"execution_id": execution.id, "status": "failed"}),
            "workflow_execution_failed",
        )
    original, produced = load_completed_delivery(db, execution.id)
    if original != binding:
        raise ValueError("workflow_customer_execution_identity_changed")
    completed = max(
        parse_datetime(execution.completed_at), parse_datetime(produced["completed_at"])
    )
    goal = contract["goal"]
    artifacts = {(item["artifact_id"], item["artifact_sha256"]) for item in produced["artifacts"]}
    receipts = list(
        db.scalars(
            select(CustomerValueReceipt).where(
                CustomerValueReceipt.customer_ref == goal["customer_ref"],
                CustomerValueReceipt.order_no == goal["order_no"],
                CustomerValueReceipt.customer_goal_id == goal["customer_goal_id"],
                CustomerValueReceipt.receipt_kind.in_(("outcome", "acceptance")),
                CustomerValueReceipt.verification_status == "verified",
                CustomerValueReceipt.environment.in_(("production", "prod")),
            )
        )
    )
    outcomes, acceptances, evidence = {}, {}, []
    for row in receipts:
        occurred, recorded = parse_datetime(row.occurred_at), parse_datetime(row.recorded_at)
        if not occurred or not recorded or not completed <= occurred <= due or recorded > due:
            continue
        body = json_loads(row.evidence_json, {})
        artifact = (row.artifact_id, str(body.get("artifact_sha256") or "").lower())
        if artifact not in artifacts:
            continue
        if row.receipt_kind == "outcome":
            if any(
                body.get(key) != agreed.get(key)
                for key in ("baseline", "target", "comparison", "unit", "measurement_window")
            ):
                continue
            direction = {"ge": "max", "le": "min"}.get(agreed.get("comparison"), "")
            target = _number(agreed.get("target"))
            if (
                target is None
                or judge("customer_goal", body.get("measured_value"), target, direction) != "hit"
            ):
                continue
            outcomes[artifact] = min(outcomes.get(artifact, occurred), occurred)
        elif body.get("customer_confirmed") is True or (
            len(str(body.get("signed_document_sha256") or "")) == 64
            and all(
                char in "0123456789abcdef" for char in str(body["signed_document_sha256"]).lower()
            )
        ):
            acceptances[artifact] = max(acceptances.get(artifact, occurred), occurred)
        else:
            continue
        evidence.append([row.receipt_id, row.evidence_digest])
    refunds = [
        row
        for row in _refunds(db, goal)
        if parse_datetime(row.occurred_at) <= due and parse_datetime(row.recorded_at) <= due
    ]
    successful = not refunds and any(
        artifact in acceptances and occurred <= acceptances[artifact]
        for artifact, occurred in outcomes.items()
    )
    evidence.extend([row.receipt_id, row.evidence_digest] for row in refunds)
    return (
        successful,
        _digest(
            {
                "contract_sha256": contract["contract_sha256"],
                "produced": produced,
                "receipts": sorted(evidence),
                "due_at": due.isoformat(),
            }
        ),
        "" if successful else "customer_outcome_not_verified_before_deadline",
    )


def reconcile_customer_executions(request_id):
    """Existing Retort scheduler calls this before fetching/freezing GrowthBook results."""
    from modstore_server import retort_experiment_runtime as runtime
    from modstore_server.retort_feedback_experiments import approved_policy
    from modstore_server.workflow_execution_feedback import _admitted, _owned_graph

    counts = {"observed": 0, "pending": 0, "archived": 0}
    now = runtime.datetime.now(UTC)
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, request_id)
        spec, effects = approved_policy(row)
        if (spec.get("lifecycle") or {}).get("measurement_scope") != WORKFLOW_CUSTOMER_MEASUREMENT:
            return counts
        evaluation = parse_datetime((effects.get("experiment") or {}).get("evaluation_at"))
        for binding in _bindings(db, request_id):
            assignment = binding["assignment"]
            execution = db.get(WorkflowExecution, binding["execution_id"])
            observation_id = f"workflow-customer:{binding['execution_id']}"
            event_id = f"experiment.observed:{observation_id}"
            archived_id = f"experiment.customer_outcome_archived:{binding['execution_id']}"
            previous = db.scalar(select(OutboxEvent.id).where(OutboxEvent.event_id == event_id))
            refunds = _refunds(db, binding["customer_delivery"]["goal"])
            if previous:
                if any(parse_datetime(refund.occurred_at) <= now for refund in refunds):
                    enqueue(
                        db,
                        "experiment.customer_outcome_archived",
                        request_id,
                        {
                            **assignment,
                            "execution_id": binding["execution_id"],
                            "reason": "refund_after_frozen_customer_outcome",
                        },
                        event_id=archived_id,
                    )
                continue
            if db.scalar(select(OutboxEvent.id).where(OutboxEvent.event_id == archived_id)):
                continue
            if binding.get("metric_admitted") is not True:
                continue  # Approved rollout is product traffic, not a new experimental sample.
            due = parse_datetime(binding.get("customer_outcome_due_at"))
            if not due or not evaluation or due > evaluation:
                raise ValueError("workflow_customer_window_unbound")
            if now < due or execution is None or execution.status not in {"completed", "failed"}:
                counts["pending"] += 1
                continue
            original = {
                **assignment,
                "generation_observation_id": assignment["observation_id"],
                "observation_id": observation_id,
                "execution_id": execution.id,
                "generation_run_id": binding["generation_run_id"],
                "graph_fingerprint": binding["graph_fingerprint"],
                "assigned_at": binding["started_at"],
            }
            if not (
                binding.get("execution_allowed") is True
                and execution.user_id == binding["user_id"]
                and execution.workflow_id == binding["workflow_id"]
                and _digest(json_loads(execution.input_data, None)) == binding["input_sha256"]
                and _owned_graph(db, execution, binding["graph_fingerprint"])
                and _admitted(db, binding, completing=True)
            ):
                enqueue(
                    db,
                    "experiment.customer_outcome_archived",
                    request_id,
                    {
                        **original,
                        "reason": "execution_identity_or_approval_no_longer_current",
                    },
                    event_id=archived_id,
                )
                counts["archived"] += 1
                continue
            try:
                success, evidence, reason = _measured(db, execution, binding, due)
            except (HTTPException, ValueError):
                counts["pending"] += 1  # Unreadable payment/goal/producer is not negative data.
                continue
            runtime.enqueue_observation(
                db,
                {
                    **original,
                    "customer_outcome_evidence_sha256": evidence,
                    "customer_outcome_due_at": due.isoformat(),
                },
                result={"ok": success, "error": reason},
                duration_ms=max(
                    0, (due - parse_datetime(binding["started_at"])).total_seconds() * 1000
                ),
            )
            counts["observed"] += 1
        db.commit()
    return counts
