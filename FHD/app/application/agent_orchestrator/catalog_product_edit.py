"""Signed immutable catalog authority; original records survive session retirement.

Current admission is separate from historical proof. Missing either host or source
proof is not absence and never authorizes another effect, including a new UUID.
"""

import hmac
import json
from contextlib import contextmanager
from datetime import datetime
from uuid import UUID

from app.application.agent_orchestrator.business_action_ledger import (
    _action_identity,
    canonical_hash,
)
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, agent_run_from_dict
from app.application.agent_orchestrator.run_repository import get_agent_run_repository
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.workflow.plan_store import CATALOG_HEAD_PREFIX as HEAD
from app.application.workflow.plan_store import CATALOG_OPERATION_PREFIX as OPERATION
from app.db.models.agent import AgentRunRecord
from app.db.models.agent_business_action import AgentBusinessActionRecord, validate_ledger_storage
from app.db.models.workflow import WorkflowPlan
from app.infrastructure.auth.agent_principal import AgentPrincipal
from app.infrastructure.tenant_scope import tenant_scope
from app.mod_sdk.catalog_product_store import TOOL, encoded, factory_for, proof, reviewed_params


def repository():
    result = get_agent_run_repository()
    if not isinstance(result, SQLAlchemyAgentRunRepository):
        raise ValueError("durable catalog claims required")
    return result


def scope(principal, *, writing=False):
    from app.fastapi_routes.domains.agent.route_support import authenticated_runtime_context
    from app.infrastructure.auth.agent_mod_scope import _bound_actor, agent_dataset_access_context

    context = authenticated_runtime_context({}, principal)
    actor = _bound_actor(context)
    permissions = {"product.edit"} if writing else {"product.view", "dataset.read"}
    if (
        str(actor.tenant_id) != principal.tenant_id
        or not permissions <= agent_dataset_access_context(context).permissions
    ):
        raise ValueError("current catalog permission required")
    return principal.tenant_id, principal.user_id, context["mod_id"]


def operation_key(principal, operation_id):
    if not isinstance(operation_id, str) or str(UUID(operation_id)) != operation_id:
        raise ValueError("canonical operation identifier required")
    tenant, user, mod = scope(principal)
    return OPERATION + canonical_hash([tenant, mod, user, operation_id])


def journal(db, key):
    # Head ownership uses bulk CAS updates; never trust a stale identity-map image.
    return (
        db.query(WorkflowPlan).filter_by(plan_id=key, intent=TOOL).populate_existing().one_or_none()
    )


def action_context(run):
    step = run.steps[0]
    return {
        **run.metadata["runtime_context"],
        "run_id": run.run_id,
        "step_id": step.step_id,
        "node_id": step.node_id,
        "business_action_id": f"agent:{run.run_id}:{step.step_id}",
    }


def validate_host_operation(db, row, *, run=None):
    """Historical signature/record joins only; never requires the retired session."""
    import jwt

    from app.application.agent_orchestrator.approval_grant import (
        _ALGORITHM,
        _AUDIENCE,
        _EVIDENCE_KEY,
        _ISSUER,
        _action_claims,
        _secret,
    )
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
    from app.db.models.agent_approval import AgentApprovalConsumption
    from app.db.schema_migrations.owned_source_host import validate_owned_host_runtime_schema

    validate_owned_host_runtime_schema(db.connection())
    if row is None:
        raise ValueError("original operation unavailable")
    claim = json.loads(row.plan_json)
    unsigned = {k: v for k, v in claim.items() if k not in {"proof", "operation_digest"}}
    signed = {**unsigned, "operation_digest": canonical_hash(unsigned)}
    if claim.get("operation_digest") != signed["operation_digest"] or not hmac.compare_digest(
        str(claim.get("proof", "")), proof(signed)
    ):
        raise ValueError("original operation signature differs")
    if run is None:
        record = db.get(AgentRunRecord, claim["run_id"], populate_existing=True)
        if record is None:
            raise ValueError("original run missing")
        run = agent_run_from_dict(json.loads(record.payload_json))
    context = run.metadata.get("runtime_context", {})
    if (
        run.run_id != claim["run_id"]
        or row.plan_id != claim["operation_key"]
        or row.intent != TOOL
        or row.status not in {"pending", "verified", "rejected"}
        or row.user_id != claim["owner"]
        or run.user_id != claim["owner"]
        or len(run.steps) != 1
        or run.steps[0].tool_id != TOOL
        or run.steps[0].action != claim["params"]["action"]
        or run.steps[0].params != claim["params"]
        or canonical_hash(claim["params"]) != claim["request_digest"]
        or run.metadata.get("catalog_price_binding") != claim["binding"]
        or run.metadata.get("catalog_operation_digest") != claim["operation_digest"]
        or context.get("tenant_id") != claim["binding"]["tenant_id"]
        or context.get("mod_id") != claim["binding"]["mod_id"]
        or row.plan_id
        != OPERATION
        + canonical_hash(
            [context["tenant_id"], context["mod_id"], run.user_id, claim["params"]["operation_id"]]
        )
        or claim["head"] != HEAD + canonical_hash([claim["binding"], claim["params"]["product_id"]])
    ):
        raise ValueError("original operation and run differ")
    step = run.steps[0]
    expected = _action_claims(run, step, run.user_id)
    validate_ledger_storage(db)
    key, fingerprint = _action_identity(
        get_tool_action_spec(TOOL, step.action), step.params, action_context(run)
    )
    action = db.get(AgentBusinessActionRecord, key)
    token = (run.metadata.get(_EVIDENCE_KEY) or {}).get(step.step_id)
    if not token:
        if (
            row.status != "pending"
            or run.status not in {"waiting_user", "paused", "cancelled", "failed", "blocked"}
            or step.status not in {"waiting_user", "pending", "failed", "skipped"}
            or action is not None
            or db.query(AgentApprovalConsumption)
            .filter_by(run_id=run.run_id, step_id=step.step_id)
            .first()
            is not None
        ):
            raise ValueError("original approval evidence missing")
        return run, claim, None
    granted = jwt.decode(
        token,
        _secret(),
        algorithms=[_ALGORITHM],
        audience=_AUDIENCE,
        issuer=_ISSUER,
        options={"verify_exp": False, "require": ["exp", "iat", "aud", "iss", "sub", "jti"]},
    )
    approval = db.get(AgentApprovalConsumption, granted["jti"])
    consumed_at = datetime.fromisoformat(approval.consumed_at).timestamp() if approval else 0
    if (
        any(str(granted.get(k) or "") != v for k, v in expected.items())
        or not approval
        or approval.run_id != run.run_id
        or approval.step_id != step.step_id
        or not int(granted["iat"]) - 1 <= consumed_at <= int(granted["exp"])
    ):
        raise ValueError("original signed approval/consumption differs")
    if action is None:
        if row.status != "pending" or run.status not in {
            "queued",
            "running",
            "retrying",
            "paused",
            "cancelled",
            "failed",
            "blocked",
        }:
            raise ValueError("original action missing")
        return run, claim, None
    if (
        action.fingerprint != fingerprint
        or action.run_id != run.run_id
        or action.tool_id != TOOL
        or action.action != step.action
        or action.user_id != run.user_id
        or action.tenant_id != context["tenant_id"]
        or action.mod_id != context["mod_id"]
        or action.business_action_id != expected["business_action_id"]
        or (row.status == "verified" and action.state != "completed")
        or (row.status == "rejected" and action.state != "rejected")
    ):
        raise ValueError("original durable action differs")
    return run, claim, action


def original(principal, operation_id):
    key = operation_key(principal, operation_id)
    with repository().transaction(read_only=True) as db:
        row = journal(db, key)
        if row is None or row.user_id != principal.user_id:
            raise ValueError("original catalog operation unavailable")
        run, claim, _ = validate_host_operation(db, row)
        return run, claim, row.status


def reconcile_source(db, binding, *, executing=None):
    """Bidirectional proof before every new operation/effect, no watermark shortcut."""
    from app.application.etl.catalog_price_history import manual_provenance
    from app.db.models.owned_source import ProductPriceHistory
    from app.mod_sdk.catalog_product_store import RECEIPT, image, receipt_payload

    receipts = {
        r.plan_id: receipt_payload(db, r.plan_id)
        for r in db.query(WorkflowPlan).filter(WorkflowPlan.plan_id.startswith(RECEIPT)).all()
    }
    with repository().transaction(read_only=True) as host:
        from app.application.agent_orchestrator.catalog_authority_retention import catalog_retention

        catalog_retention(host)
        operations = {}
        for row in (
            host.query(WorkflowPlan).filter(WorkflowPlan.plan_id.startswith(OPERATION)).all()
        ):
            run, claim, action = validate_host_operation(host, row)
            if (claim["binding"]["tenant_id"], claim["binding"]["mod_id"]) != (
                binding["tenant_id"],
                binding["mod_id"],
            ):
                continue
            if claim["binding"] != binding:
                raise ValueError("original source generation differs")
            key = RECEIPT + canonical_hash(claim["operation_key"])
            payload = receipts.get(key)
            if payload is None:
                if row.status != "pending" or (
                    action is not None
                    and not (
                        executing == claim["operation_key"]
                        and action.state == "claimed"
                        and action.receipt_json == "{}"
                    )
                ):
                    raise ValueError("original source evidence missing; reconciliation required")
            else:
                if (
                    action is None
                    or payload["params"] != claim["params"]
                    or payload["run_id"] != run.run_id
                    or payload["owner"] != run.user_id
                    or payload["business_action_id"] != action.business_action_id
                    or payload.get("operation_digest") != claim["operation_digest"]
                ):
                    raise ValueError("source/host original authority differs")
                validate_receipt_authority(claim, payload, action)
                if row.status != "pending" and action.receipt_json != encoded(payload):
                    raise ValueError("retained immutable receipt differs")
                if row.status == "pending" and executing != claim["operation_key"]:
                    raise ValueError("original owner must reconcile pending effect")
            operations[key] = claim
        if set(receipts) - set(operations):
            raise ValueError("source receipt has lost original host authority")
        events = {
            row.source_key: row
            for row in db.query(ProductPriceHistory)
            .filter_by(tenant_id=int(binding["tenant_id"]))
            .all()
        }
        for key, payload in receipts.items():
            expected = canonical_hash([TOOL, operations[key]["operation_key"]])
            if payload.get("outcome") == "saved":
                if expected not in events or image(events[expected]) != payload["event"]:
                    raise ValueError("immutable source history missing or changed")
            elif payload.get("outcome") != "rejected_no_effect" or expected in events:
                raise ValueError("source rejection conflicts with history")
        for row in events.values():
            provenance = manual_provenance(row)
            if provenance and provenance["receipt_key"] not in receipts:
                raise ValueError("history has lost original receipt")


def create_edit(principal, product_id, body):
    from app.fastapi_routes.domains.agent.route_support import authenticated_runtime_context

    scope(principal, writing=True)
    key = operation_key(principal, body.get("operation_id"))
    repo = repository()
    factory = factory_for(principal)
    try:
        with tenant_scope(int(principal.tenant_id)), factory.guard():
            factory.knowledge.validate()
            with repo.transaction(read_only=True) as host:
                existing = journal(host, key)
                old = json.loads(existing.plan_json) if existing else None
            if old:
                if old["params"]["product_id"] != product_id or body != old["request"]:
                    raise ValueError("operation already bound to another request")
                return original(principal, body["operation_id"])[0]
            with factory() as db:
                reconcile_source(db, factory.binding)
                params = reviewed_params(db, principal.tenant_id, product_id, body)
            binding = dict(factory.binding)
            resource = HEAD + canonical_hash([binding, product_id])
            run = AgentRun(
                user_id=principal.user_id,
                message="审核目录价格修改",
                status="waiting_user",
                steps=[
                    AgentStep(
                        node_id="catalog-price-review",
                        tool_id=TOOL,
                        action=params["action"],
                        risk="medium",
                        status="waiting_user",
                        params=params,
                    )
                ],
                metadata={
                    "runtime_context": authenticated_runtime_context({}, principal),
                    "catalog_price_binding": binding,
                },
            )
            claim = {
                "run_id": run.run_id,
                "params": params,
                "request": body,
                "binding": binding,
                "head": resource,
                "operation_key": key,
                "request_digest": canonical_hash(params),
                "owner": principal.user_id,
            }
            claim["operation_digest"] = canonical_hash(claim)
            claim["proof"] = proof(claim)
            run.metadata["catalog_operation_digest"] = claim["operation_digest"]
            with repo.transaction() as host:
                from app.desktop_runtime.database_generation_registry import (
                    validate_owned_host_session,
                )

                validate_owned_host_session(host)
                head = journal(host, resource)
                if head is None:
                    host.add(
                        WorkflowPlan(
                            plan_id=resource,
                            intent=TOOL,
                            user_id=principal.user_id,
                            status="active",
                            runtime_context=key,
                        )
                    )
                elif (
                    host.query(WorkflowPlan)
                    .filter_by(plan_id=resource, intent=TOOL, status="idle", runtime_context="")
                    .update({"status": "active", "runtime_context": key}, synchronize_session=False)
                    != 1
                ):
                    raise ValueError("original product operation still requires verification")
                host.add(
                    WorkflowPlan(
                        plan_id=key,
                        intent=TOOL,
                        user_id=principal.user_id,
                        status="pending",
                        plan_json=encoded(claim),
                    )
                )
                host.flush()
                repo.save_in_session(host, run)
            return run
    finally:
        factory.engine.dispose()


def principal_from_context(context):
    return AgentPrincipal(
        user_id=str(context.get("user_id") or ""),
        tenant_id=str(context.get("tenant_id") or ""),
        mod_authorization=context.get("_mod_authorization"),
        actor_authorization=context.get("_actor_authorization"),
    )


def trusted_original(params, context, *, writing=False):
    principal = principal_from_context(context)
    scope(principal, writing=writing)
    run, claim, status = original(principal, params["operation_id"])
    if params != claim["params"] or any(
        context.get(k) != v
        for k, v in action_context(run).items()
        if k in {"run_id", "step_id", "node_id", "business_action_id"}
    ):
        raise ValueError("original catalog action differs")
    if writing and (
        run.status != "running" or run.steps[0].status != "running" or status != "pending"
    ):
        raise ValueError("original catalog action is not running")
    return principal, run, claim


def existing_action(params, context):
    """Current READ admission and immutable HOST joins; no claim or state change."""
    principal, run, claim = trusted_original(params, context)
    with repository().transaction(read_only=True) as db:
        _, current, action = validate_host_operation(db, journal(db, claim["operation_key"]))
        if current != claim:
            raise ValueError("original catalog action differs")
        return action is not None


def fresh_claim_guard(db, params, context):
    """Fence a new catalog ledger claim on its caller's HOST transaction.

    An existing action is readback-only. Never acquire a source lock while holding
    the HOST writer: the effect path owns source then HOST, in that order.
    """
    from app.application.agent_orchestrator.business_write_guard import capture_worker_claim
    from app.application.agent_orchestrator.worker_repository import lock_execution_claim
    from app.desktop_runtime.database_generation_registry import validate_owned_host_session
    from app.mod_sdk.owned_price_catalog import _context

    principal = principal_from_context(context)
    key = operation_key(principal, params["operation_id"])
    row = journal(db, key)
    run, claim, action = validate_host_operation(db, row)
    if params != claim["params"] or any(
        context.get(k) != v
        for k, v in action_context(run).items()
        if k in {"run_id", "step_id", "node_id", "business_action_id"}
    ):
        raise ValueError("original catalog action differs")
    if action is not None:
        return False  # The ledger's unique key must route this race to readback only.
    reference = capture_worker_claim()
    if reference is None or reference[0] != run.run_id:
        raise ValueError("original durable worker lease required")
    validate_owned_host_session(db)
    lock_execution_claim(
        db, run_id=reference[0], owner_id=reference[1], execution_count=reference[2]
    )
    # Reload after acquiring writer ownership; no stale read can admit a new effect.
    db.expire_all()
    _context(principal, mixed=True)  # Recheck full WRITE grants under HOST ownership.
    row = journal(db, key)
    run, claim, action = validate_host_operation(db, row)
    if action is not None:
        return False
    if (
        run.status != "running"
        or run.steps[0].status != "running"
        or row.status != "pending"
        or not run.metadata.get("_tool_approval_grants")
        or params != claim["params"]
    ):
        raise ValueError("original catalog action is not running")
    if (
        db.query(WorkflowPlan)
        .filter_by(plan_id=claim["head"], intent=TOOL, status="active", runtime_context=key)
        .update({"status": "active"}, synchronize_session=False)
        != 1
    ):
        raise ValueError("original resource claim is no longer active")
    return True


@contextmanager
def active_worker(claim, context):
    from app.application.agent_orchestrator.business_write_guard import capture_worker_claim
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
    from app.application.agent_orchestrator.worker_repository import lock_execution_claim
    from app.desktop_runtime.database_generation_registry import validate_owned_host_session

    reference = capture_worker_claim()
    if reference is None or reference[0] != claim["run_id"]:
        raise ValueError("original durable worker lease required")
    with repository().transaction() as db:
        validate_owned_host_session(db)
        lock_execution_claim(
            db, run_id=reference[0], owner_id=reference[1], execution_count=reference[2]
        )
        if (
            db.query(WorkflowPlan)
            .filter_by(
                plan_id=claim["head"],
                intent=TOOL,
                status="active",
                runtime_context=claim["operation_key"],
            )
            .update({"status": "active"}, synchronize_session=False)
            != 1
        ):
            raise ValueError("original resource claim is no longer active")
        key, fingerprint = _action_identity(
            get_tool_action_spec(TOOL, claim["params"]["action"]), claim["params"], context
        )
        action = db.get(AgentBusinessActionRecord, key)
        if (
            not action
            or action.run_id != claim["run_id"]
            or action.fingerprint != fingerprint
            or action.state != "claimed"
            or action.receipt_json != "{}"
            or action.owner != context.get("_catalog_claim_owner")
        ):
            raise ValueError("original action is not a fresh owned dispatch")
        yield {
            "action_key": key,
            "fingerprint": fingerprint,
            "owner": action.owner,
            "execution_count": reference[2],
        }


def release_verified(claim, payload):
    """Only independent source verifier calls this CAS while holding source guard."""
    with repository().transaction() as db:
        row = journal(db, claim["operation_key"])
        run, original_claim, action = validate_host_operation(db, row)
        if original_claim != claim or action is None:
            raise ValueError("original action authority changed")
        validate_receipt_authority(claim, payload, action)
        terminal = "rejected" if payload["outcome"] == "rejected_no_effect" else "verified"
        if row.status == terminal:
            if action.receipt_json != encoded(payload):
                raise ValueError("immutable original receipt differs")
            return
        if (
            row.status != "pending"
            or action.state not in {"claimed", "verification_required", "unknown"}
            or action.receipt_json not in {"{}", encoded(payload)}
        ):
            raise ValueError("original action state differs")
        changed = (
            db.query(AgentBusinessActionRecord)
            .filter_by(
                action_key=action.action_key,
                owner=action.owner,
                fingerprint=action.fingerprint,
                state=action.state,
                receipt_json=action.receipt_json,
            )
            .update(
                {
                    "state": "rejected" if terminal == "rejected" else "completed",
                    "receipt_json": encoded(payload),
                },
                synchronize_session=False,
            )
        )
        if (
            changed != 1
            or db.query(WorkflowPlan)
            .filter_by(
                plan_id=claim["head"],
                intent=TOOL,
                status="active",
                runtime_context=claim["operation_key"],
            )
            .update({"status": "idle", "runtime_context": ""}, synchronize_session=False)
            != 1
        ):
            raise ValueError("original claim CAS lost")
        row.status = terminal


def validate_receipt_authority(claim, payload, action):
    """Join either signed receipt to the original immutable ledger owner.

    The historical execution count is evidence, not a current live lease. A later
    queue generation cannot invalidate history or substitute a new ledger owner.
    """
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

    field = {"saved": "effect_claim", "rejected_no_effect": "no_effect"}.get(payload.get("outcome"))
    evidence = payload.get(field) if field else None
    spec = get_tool_action_spec(TOOL, claim["params"]["action"])
    if (
        not isinstance(evidence, dict)
        or set(evidence) != {"action_key", "fingerprint", "owner", "execution_count"}
        or spec is None
    ):
        raise ValueError("original receipt action proof unavailable")
    expected_key = canonical_hash(
        [
            claim["binding"]["tenant_id"],
            claim["binding"]["mod_id"],
            payload.get("business_action_id"),
        ]
    )
    expected_fingerprint = canonical_hash(
        [claim["owner"], spec.owner_mod_id, TOOL, spec.action, spec.version, claim["params"]]
    )
    if (
        action is None
        or action.action_key != expected_key
        or evidence["action_key"] != expected_key
        or action.fingerprint != expected_fingerprint
        or evidence["fingerprint"] != expected_fingerprint
        or action.run_id != claim["run_id"]
        or action.user_id != claim["owner"]
        or action.tool_id != TOOL
        or action.action != claim["params"]["action"]
        or action.tenant_id != claim["binding"]["tenant_id"]
        or action.mod_id != claim["binding"]["mod_id"]
        or action.owner != evidence["owner"]
        or action.business_action_id != payload.get("business_action_id")
        or type(evidence["execution_count"]) is not int
        or evidence["execution_count"] < 1
    ):
        raise ValueError("original receipt action proof differs")


def verify_receipt_authority(claim, payload):
    with repository().transaction(read_only=True) as db:
        _, current, action = validate_host_operation(db, journal(db, claim["operation_key"]))
        if current != claim:
            raise ValueError("original receipt operation differs")
        validate_receipt_authority(claim, payload, action)
