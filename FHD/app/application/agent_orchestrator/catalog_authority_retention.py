"""Retain original catalog authority during ordinary host repository cleanup.

The selector owns no transaction and performs no writes or schema preparation.
Its caller serializes the read/delete boundary on the same SQLite connection.
Retention is not source reconciliation and cannot reconstruct lost authority.
"""

import json
import unicodedata
from copy import deepcopy
from dataclasses import dataclass

from sqlalchemy import inspect, select

from app.application.agent_orchestrator.task_context import task_context_of
from app.application.workflow.plan_store import (
    CATALOG_HEAD_PREFIX,
    CATALOG_OPERATION_PREFIX,
    CATALOG_RECEIPT_PREFIX,
    OWNED_KNOWLEDGE_CONTROL_KEY,
    reserved_workflow_plan_id,
)

_TOOL = "catalog_products_v1"


def preserve_catalog_run_authority(db, run, previous):
    """Keep signed catalog identity through all saves, including stale snapshots.

    This runs before generic generation matching: renewed sessions may change that
    match, but can never change the original operation or its consumed approval.
    New catalog runs must already have a signed operation/head in this transaction.
    """

    def catalog(value):
        return value is not None and (
            any(step.tool_id == _TOOL for step in value.steps)
            or any(
                key in value.metadata
                for key in ("catalog_price_binding", "catalog_operation_digest")
            )
        )

    if not catalog(run) and not catalog(previous):
        return
    from app.application.agent_orchestrator.approval_grant import _EVIDENCE_KEY
    from app.application.agent_orchestrator.business_action_ledger import canonical_hash
    from app.application.agent_orchestrator.catalog_product_edit import (
        journal,
        validate_host_operation,
    )
    from app.infrastructure.auth.agent_mod_scope import _bound_actor

    origin = previous if previous is not None else run
    if len(origin.steps) != 1 or origin.steps[0].tool_id != _TOOL or len(run.steps) != 1:
        raise ValueError("catalog run identity cannot be replaced")
    context = origin.metadata.get("runtime_context") or {}
    key = CATALOG_OPERATION_PREFIX + canonical_hash(
        [
            context.get("tenant_id"),
            context.get("mod_id"),
            origin.user_id,
            origin.steps[0].params.get("operation_id"),
        ]
    )
    row = journal(db, key)
    if previous is not None:
        # Validate the merged incoming snapshot below: an approval transaction has
        # already inserted consumption while its previous payload still lacks the token.
        identity = lambda item: (
            item.run_id,
            item.user_id,
            item.created_at,
            tuple(
                getattr(item.steps[0], field)
                for field in (
                    "step_id",
                    "node_id",
                    "tool_id",
                    "action",
                    "params",
                    "risk",
                    "idempotent",
                    "depends_on",
                )
            ),
        )
        if identity(run) != identity(previous):
            raise ValueError("catalog run identity cannot be replaced")
        for field in ("catalog_price_binding", "catalog_operation_digest"):
            if field in run.metadata and run.metadata[field] != previous.metadata.get(field):
                raise ValueError("immutable catalog binding differs")
            run.metadata[field] = deepcopy(previous.metadata[field])
        incoming = run.metadata.get("runtime_context") or {}
        for field in ("user_id", "actor_id", "tenant_id", "mod_id", "active_mod_id"):
            if incoming.get(field) != context.get(field):
                raise ValueError("catalog actor scope cannot change")
        for field, mutable in (
            ("_actor_authorization", {"session_row_id", "proof"}),
            ("_mod_authorization", {"session_row_id"}),
        ):
            old, new = context.get(field), incoming.get(field)
            if (
                not isinstance(old, dict)
                or not isinstance(new, dict)
                or {k: v for k, v in old.items() if k not in mutable}
                != {k: v for k, v in new.items() if k not in mutable}
            ):
                raise ValueError("catalog actor scope cannot change")
            if old != new:
                _bound_actor(incoming)  # Only a valid same-owner renewed session is accepted.
    else:
        _bound_actor(context)
    old = (previous.metadata.get(_EVIDENCE_KEY) or {}) if previous else {}
    incoming = run.metadata.get(_EVIDENCE_KEY, {})
    if not isinstance(old, dict) or not isinstance(incoming, dict):
        raise ValueError("catalog approval evidence must be an object")
    if any(key in incoming and incoming[key] != value for key, value in old.items()):
        raise ValueError("immutable catalog approval differs")
    evidence = {**old, **incoming}
    if set(evidence) - {run.steps[0].step_id} or any(
        not isinstance(token, str) or not token for token in evidence.values()
    ):
        raise ValueError("catalog approval identity differs")
    if evidence:
        run.metadata[_EVIDENCE_KEY] = deepcopy(evidence)
    _, claim, _ = validate_host_operation(db, row, run=run)
    head = journal(db, claim["head"])
    if head is None or (
        row.status == "pending" and (head.status != "active" or head.runtime_context != key)
    ):
        raise ValueError("catalog operation head missing or changed")


@dataclass(frozen=True)
class CatalogRetention:
    run_ids: frozenset[str]
    task_keys: frozenset[tuple[str, str, str]]


def lock_catalog_cleanup(db):
    """Acquire SQLite writer ownership before inspecting retained authorities."""
    connection = db.connection()
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("BEGIN IMMEDIATE")


def catalog_retention(db) -> CatalogRetention:
    """Validate both host reference directions; any conflict aborts cleanup."""
    from app.db.models.agent import AgentRunRecord
    from app.db.models.agent_business_action import (
        AgentBusinessActionRecord,
        validate_ledger_storage,
    )
    from app.db.models.workflow import WorkflowPlan

    connection = db.connection()
    tables = set(inspect(connection).get_table_names())
    operations, heads = {}, []
    if WorkflowPlan.__tablename__ in tables:
        for row in connection.execute(select(WorkflowPlan.__table__)):
            if not reserved_workflow_plan_id(row.plan_id):
                continue
            normalized = unicodedata.normalize("NFKC", row.plan_id).strip().casefold()
            if normalized == OWNED_KNOWLEDGE_CONTROL_KEY:
                continue
            if normalized != row.plan_id or row.intent != _TOOL:
                raise ValueError("invalid protected catalog authority")
            if row.plan_id.startswith(CATALOG_OPERATION_PREFIX):
                operations[row.plan_id] = row
            elif row.plan_id.startswith(CATALOG_HEAD_PREFIX):
                heads.append(row)
            elif row.plan_id.startswith(CATALOG_RECEIPT_PREFIX):
                # Immutable physical receipts belong to the owned source, not HOST.
                raise ValueError("unexpected catalog receipt in host authority")

    ledger = []
    if AgentBusinessActionRecord.__tablename__ in tables:
        validate_ledger_storage(db)
        ledger = list(
            connection.execute(
                select(AgentBusinessActionRecord.__table__).where(
                    AgentBusinessActionRecord.__table__.c.tool_id == _TOOL
                )
            )
        )
    catalog_runs = set()
    if AgentRunRecord.__tablename__ in tables:
        for row in connection.execute(
            select(AgentRunRecord.__table__).where(AgentRunRecord.payload_json.contains(_TOOL))
        ):
            payload = json.loads(row.payload_json)
            if any(step.get("tool_id") == _TOOL for step in payload.get("steps", [])):
                catalog_runs.add(row.run_id)
    if not operations and not heads and not ledger and not catalog_runs:
        return CatalogRetention(frozenset(), frozenset())

    from app.application.agent_orchestrator.catalog_product_edit import validate_host_operation

    runs, task_keys, claims, action_keys = set(), set(), {}, set()
    for key, row in operations.items():
        run, claim, action = validate_host_operation(db, row)
        if claim["operation_key"] != key or run.run_id in runs:
            raise ValueError("catalog operation identity conflict")
        runs.add(run.run_id)
        claims[key] = claim
        task_keys.add(
            (
                str(claim["binding"]["tenant_id"]),
                str(run.user_id),
                str(task_context_of(run)["task_id"]),
            )
        )
        if action is not None:
            if action.run_id != run.run_id:
                raise ValueError("catalog ledger run differs")
            action_keys.add(action.action_key)
    if (
        catalog_runs != runs
        or {row.action_key for row in ledger} != action_keys
        or any(row.run_id not in runs for row in ledger)
    ):
        raise ValueError("orphaned catalog run or ledger authority")
    for row in heads:
        if row.status == "idle" and not row.runtime_context:
            if not any(claim["head"] == row.plan_id for claim in claims.values()):
                raise ValueError("orphaned catalog head")
            continue
        claim = claims.get(row.runtime_context)
        if row.status != "active" or claim is None or claim["head"] != row.plan_id:
            raise ValueError("catalog active head differs from original operation")
    if any(claim["head"] not in {row.plan_id for row in heads} for claim in claims.values()):
        raise ValueError("catalog operation head missing")
    return CatalogRetention(frozenset(runs), frozenset(task_keys))
