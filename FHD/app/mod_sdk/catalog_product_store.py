"""Reviewed edits in the real mixed catalog; never routes to legacy ERP or pilot."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import date
from decimal import Decimal
from typing import Any

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.etl.batch_owned_source import OwnedSqlSessions
from app.application.etl.batch_price_sources import price_value
from app.application.etl.catalog_price_history import (
    effective_history,
    effective_price,
    history_events,
    validate_correction,
)
from app.db.models.owned_source import EtlPriceDimension, ProductPriceHistory
from app.db.models.product import Product
from app.db.models.purchase_unit import PurchaseUnit
from app.db.models.workflow import WorkflowPlan
from app.infrastructure.tenant_scope import tenant_scope
from app.mod_sdk.owned_price_catalog import CatalogPurpose

TOOL = "catalog_products_v1"
ACTIONS = {"append_price", "correct_price"}
from app.application.workflow.plan_store import CATALOG_RECEIPT_PREFIX as RECEIPT


def encoded(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def image(row):
    if row is None:
        return None
    return {
        column.name: (
            value.isoformat()
            if hasattr(value, "isoformat")
            else str(value)
            if isinstance(value, Decimal)
            else value
        )
        for column in row.__table__.columns
        for value in [getattr(row, column.name)]
    }


def receipt_secret():
    secret = os.environ.get("SECRET_KEY", "").strip()
    if not secret:
        raise ValueError("catalog receipts require a stable server signing key")
    return secret


def proof(payload):
    return hmac.new(
        receipt_secret().encode(), encoded(payload).encode(), hashlib.sha256
    ).hexdigest()


def source_view(binding):
    return {key: binding[key] for key in ("source_id", "epoch", "protocol")}


def receipt_payload(db, key):
    record = db.query(WorkflowPlan).filter_by(plan_id=key, intent=TOOL).one_or_none()
    if (
        record is None
        or not key.startswith(RECEIPT)
        or record.status not in {"succeeded", "rejected"}
    ):
        raise ValueError("original catalog receipt unavailable")
    envelope = json.loads(record.runtime_context)
    payload = envelope["payload"]
    if not hmac.compare_digest(envelope["proof"], proof(payload)):
        raise ValueError("original catalog receipt proof differs")
    if payload["binding"] != db.info.get("etl_owned_source"):
        raise ValueError("original catalog receipt source differs")
    return payload


def verify_manual_row(db, row, provenance):
    """Verify immutable inserted event, not the mutable current product image."""
    try:
        payload = receipt_payload(db, provenance["receipt_key"])
        dimension = (
            db.query(EtlPriceDimension)
            .filter_by(tenant_id=row.tenant_id, product_id=row.product_id)
            .one_or_none()
        )
        return (
            dimension is not None
            and (dimension.currency, dimension.price_unit)
            == (provenance["currency"], provenance["price_unit"])
            and payload["event"] == image(row)
            and payload["params"]["operation_id"] == provenance["operation_id"]
            and payload["run_id"] == provenance["run_id"]
            and payload["owner"] == provenance["actor_id"]
            and payload["params"]["currency"] == provenance["currency"]
            and payload["params"]["price_unit"] == provenance["price_unit"]
        )
    except (ValueError, KeyError, TypeError):
        return False


def state(db, product_id, tenant):
    product = db.query(Product).filter_by(id=product_id, tenant_id=int(tenant)).one_or_none()
    if product is None:
        raise ValueError("catalog product unavailable")
    history = (
        db.query(ProductPriceHistory)
        .filter_by(tenant_id=int(tenant), product_id=product_id)
        .order_by(ProductPriceHistory.id)
        .limit(5001)
        .all()
    )
    if len(history) > 5000:
        raise ValueError("catalog history exceeds review limit")
    dimension = (
        db.query(EtlPriceDimension)
        .filter_by(tenant_id=int(tenant), product_id=product_id)
        .one_or_none()
    )
    if dimension is None:
        raise ValueError("catalog price dimension unavailable")
    effective = effective_history(
        history, verify_manual=lambda row, p: verify_manual_row(db, row, p)
    )
    raw = {
        "product": image(product),
        "history": [image(row) for row in history],
        "dimension": image(dimension),
    }
    revision = canonical_hash({"source": db.info["etl_owned_source"], "state": raw})
    active = {row.source_key for row in effective}
    view = {
        "id": product.id,
        "name": product.name,
        "model_number": product.model_number or "",
        "unit": product.unit,
        "price": format(Decimal(product.price), ".2f"),
        "currency": dimension.currency,
        "price_unit": dimension.price_unit,
        "revision": revision,
        "source": source_view(db.info["etl_owned_source"]),
        "history": [
            {
                "source_key": row.source_key,
                "price": format(row.price, ".2f"),
                "period_start": row.period_start.isoformat() if row.period_start else None,
                "period_end": row.period_end.isoformat() if row.period_end else None,
                "period_label": row.period_label,
                "effective": row.source_key in active,
            }
            for row in history
        ],
    }
    return product, history, dimension, effective, view


def validate_request(body):
    from uuid import UUID

    keys = {
        "operation_id",
        "revision",
        "action",
        "price",
        "period_start",
        "period_end",
        "selected_sources",
        "reason",
        "confirmed",
    }
    if not isinstance(body, dict) or set(body) != keys or body["confirmed"] is not True:
        raise ValueError("explicit complete price review required")
    if str(UUID(body["operation_id"])) != body["operation_id"]:
        raise ValueError("canonical operation id required")
    if (
        not isinstance(body["action"], str)
        or body["action"] not in ACTIONS
        or not isinstance(body["price"], str)
        or price_value(body["price"]) != body["price"]
    ):
        raise ValueError("canonical two-decimal price required")
    if (
        not isinstance(body["reason"], str)
        or not 1 <= len(body["reason"]) <= 500
        or body["reason"] != body["reason"].strip()
    ):
        raise ValueError("explicit correction or addition reason required")
    if not isinstance(body["selected_sources"], list) or len(body["selected_sources"]) > 5000:
        raise ValueError("reviewed source observations required")
    start, end = body["period_start"], body["period_end"]
    if (start is None) != (end is None):
        raise ValueError("both period boundaries required")
    if start is not None:
        if not isinstance(start, str) or not isinstance(end, str):
            raise ValueError("ISO business period required")
        if (
            date.fromisoformat(start).isoformat() != start
            or date.fromisoformat(end).isoformat() != end
            or start >= end
        ):
            raise ValueError("valid original business period required")
    elif body["action"] != "correct_price":
        raise ValueError("new observations require an explicit business period")
    if body["action"] == "append_price" and body["selected_sources"]:
        raise ValueError("append cannot replace observations")
    return dict(body)


def reviewed_params(db, tenant, product_id, body):
    body = validate_request(body)
    product, history, dimension, effective, view = state(db, product_id, tenant)
    if (
        not effective
        or Decimal(str(effective_price(history_events(effective))["price"])) != product.price
    ):
        raise ValueError("existing product price is not verified against its history")
    if body["revision"] != view["revision"]:
        raise ValueError("product, source, dimensions or history changed; review again")
    if db.query(PurchaseUnit).filter_by(tenant_id=int(tenant), unit_name=product.unit).count() != 1:
        raise ValueError("purchase customer must remain unique")
    selected = []
    start = date.fromisoformat(body["period_start"]) if body["period_start"] else None
    end = date.fromisoformat(body["period_end"]) if body["period_end"] else None
    if body["action"] == "correct_price":
        selected = validate_correction(effective, body["selected_sources"], start, end)
    # Validate the proposed effective set before any approval or mutation.
    removed = {row.source_key for row in selected}
    events = history_events([row for row in effective if row.source_key not in removed])
    events.append(
        {
            "source_key": "0" * 64,
            "period_start": start,
            "period_end": end,
            "period_label": "",
            "price": body["price"],
        }
    )
    effective_price(events)
    return {
        **body,
        "product_id": product_id,
        "currency": dimension.currency,
        "price_unit": dimension.price_unit,
        "selected_observations": [
            item for item in view["history"] if item["source_key"] in removed
        ],
    }


def factory_for(principal, *, purpose=CatalogPurpose.ETL, lock_timeout=0):
    from app.application.agent_orchestrator.catalog_product_edit import scope

    scope(principal, writing=purpose is not CatalogPurpose.READ)
    receipt_secret()
    return OwnedSqlSessions(principal, mixed=True, purpose=purpose, lock_timeout=lock_timeout)


def read_products(principal, *, product_id=None, keyword="", operation_key=None):
    from app.application.agent_orchestrator.catalog_product_edit import reconcile_source

    factory = factory_for(principal, purpose=CatalogPurpose.READ)
    try:
        with tenant_scope(int(principal.tenant_id)), factory.guard():
            factory.knowledge.validate()
            with factory() as db:
                reconcile_source(db, factory.binding, executing=operation_key)
                if product_id is not None:
                    return state(db, product_id, principal.tenant_id)[4]
                query = db.query(Product.id).filter_by(tenant_id=int(principal.tenant_id))
                if keyword:
                    from sqlalchemy import or_

                    query = query.filter(
                        or_(Product.name.contains(keyword), Product.model_number.contains(keyword))
                    )
                ids = [row.id for row in query.order_by(Product.id).limit(20)]
                return {
                    "data": [state(db, pid, principal.tenant_id)[4] for pid in ids],
                    "source": source_view(factory.binding),
                    "capability": "catalog_prices_v1",
                }
    finally:
        factory.engine.dispose()


def execute_catalog_price(params, action, *, source_factory=None):
    from app.application.agent_orchestrator.catalog_product_edit import (
        active_worker,
        reconcile_source,
        trusted_original,
    )
    from app.application.agent_orchestrator.tool_executor import controlled_tool_context

    context = controlled_tool_context(TOOL, action)
    if not context or context.get("_controlled_params_sha256") != canonical_hash(params):
        raise ValueError("controlled catalog dispatch required")
    principal, run, claim = trusted_original(params, context, writing=True)
    factory = source_factory if source_factory is not None else factory_for(principal)
    try:
        if factory.principal != principal or factory.binding != claim["binding"]:
            raise ValueError("original catalog source changed")
        with tenant_scope(int(principal.tenant_id)), factory.guard():
            factory.knowledge.validate()
            with active_worker(claim, context) as ownership, factory() as db:
                db.connection().exec_driver_sql("BEGIN IMMEDIATE")
                factory.validate(db)
                reconcile_source(db, factory.binding, executing=claim["operation_key"])
                key = RECEIPT + canonical_hash(claim["operation_key"])
                source_key = canonical_hash([TOOL, claim["operation_key"]])
                if (
                    db.query(WorkflowPlan.id).filter_by(plan_id=key).first()
                    or db.query(ProductPriceHistory.id).filter_by(source_key=source_key).first()
                ):
                    raise ValueError("original catalog effect already exists; reconcile only")
                rejected = False
                try:
                    fresh = reviewed_params(
                        db, principal.tenant_id, params["product_id"], claim["request"]
                    )
                    if fresh != params:
                        raise ValueError("reviewed price observations changed")
                except (ValueError, RuntimeError):
                    # No business DML has occurred. The original lease and fresh global
                    # ledger claim remain locked across this same-source transaction.
                    payload = {
                        "binding": factory.binding,
                        "operation_digest": claim["operation_digest"],
                        "params": params,
                        "run_id": run.run_id,
                        "owner": principal.user_id,
                        "business_action_id": context["business_action_id"],
                        "outcome": "rejected_no_effect",
                        "no_effect": ownership,
                        "absent_source_key": source_key,
                        "reason_code": "review_precondition_changed",
                    }
                    db.add(
                        WorkflowPlan(
                            plan_id=key,
                            intent=TOOL,
                            user_id=principal.user_id,
                            status="rejected",
                            runtime_context=encoded({"payload": payload, "proof": proof(payload)}),
                        )
                    )
                    db.commit()
                    rejected = True
                if not rejected:
                    product, history, dimension, effective, before = state(
                        db, params["product_id"], principal.tenant_id
                    )
                    provenance = {
                        "kind": "catalog_price_v1",
                        "operation_id": params["operation_id"],
                        "run_id": run.run_id,
                        "reason": params["reason"],
                        "supersedes": params["selected_sources"],
                        "currency": dimension.currency,
                        "price_unit": dimension.price_unit,
                        "actor_id": principal.user_id,
                        "receipt_key": key,
                    }
                    start = (
                        date.fromisoformat(params["period_start"])
                        if params["period_start"]
                        else None
                    )
                    end = date.fromisoformat(params["period_end"]) if params["period_end"] else None
                    row = ProductPriceHistory(
                        tenant_id=int(principal.tenant_id),
                        product_id=product.id,
                        owner_user_id=int(principal.user_id),
                        period_start=start,
                        period_end=end,
                        period_label=f"{start} 至 {end}（不含结束日）" if start else "未标业务时间",
                        price=Decimal(params["price"]),
                        source_key=canonical_hash([TOOL, claim["operation_key"]]),
                        provenance_json=encoded(provenance),
                    )
                    db.add(row)
                    db.flush()
                    payload = {
                        "binding": factory.binding,
                        "operation_digest": claim["operation_digest"],
                        "effect_claim": ownership,
                        "outcome": "saved",
                        "params": params,
                        "run_id": run.run_id,
                        "owner": principal.user_id,
                        "event": image(row),
                        "business_action_id": context["business_action_id"],
                        "before_revision": before["revision"],
                    }
                    receipt = WorkflowPlan(
                        plan_id=key,
                        intent=TOOL,
                        user_id=principal.user_id,
                        status="succeeded",
                        runtime_context=encoded({"payload": payload, "proof": proof(payload)}),
                    )
                    db.add(receipt)
                    db.flush()
                    active = effective_history(
                        history + [row],
                        verify_manual=lambda item, p: verify_manual_row(db, item, p),
                    )
                    product.price = Decimal(str(effective_price(history_events(active))["price"]))
                    db.flush()
                    after = state(db, product.id, principal.tenant_id)[4]
                    payload["after_revision"] = after["revision"]
                    receipt.runtime_context = encoded({"payload": payload, "proof": proof(payload)})
                    db.flush()
                    db.commit()
        # The caller retaining this exact factory releases the source lock before
        # independent physical readback. Do not recursively open a second factory.
        if source_factory is None:
            return verify_catalog_action(params, context, release=True)
    finally:
        if source_factory is None:
            factory.engine.dispose()


def reconcile_operation(principal, operation_id):
    """Explicit original-owner resolution, never approval or original-write retry.

    Supported restore epochs remain mandatory. Missing terminal source evidence
    is not recreated from HOST, and this is not an anti-rollback external ledger.
    """
    from app.application.agent_orchestrator.catalog_product_edit import (
        PRECLAIM_RECEIPT,
        action_context,
        original,
        prepare_preclaim_finalization,
        reconcile_source,
    )

    run, claim, status = original(principal, operation_id)
    factory = factory_for(principal, lock_timeout=5)
    try:
        if factory.binding != claim["binding"]:
            raise ValueError("original catalog source changed")
        with tenant_scope(int(principal.tenant_id)), factory.guard():
            factory.knowledge.validate()
            with factory() as db:
                db.connection().exec_driver_sql("BEGIN IMMEDIATE")
                factory.validate(db)
                reconcile_source(db, factory.binding, executing=claim["operation_key"])
                key = RECEIPT + canonical_hash(claim["operation_key"])
                record = db.query(WorkflowPlan).filter_by(plan_id=key).one_or_none()
                payload = receipt_payload(db, key) if record is not None else None
                if payload is None or payload.get("receipt_kind") == PRECLAIM_RECEIPT:
                    source_key = canonical_hash([TOOL, claim["operation_key"]])
                    if db.query(ProductPriceHistory.id).filter_by(source_key=source_key).first():
                        raise ValueError("original preclaim operation has a source event")
                    # Independent current history validation is required even for
                    # zero DML. An absent ledger/receipt alone proves nothing.
                    product, _, _, effective, view = state(
                        db, claim["params"]["product_id"], principal.tenant_id
                    )
                    if (
                        Decimal(str(effective_price(history_events(effective))["price"]))
                        != product.price
                    ):
                        raise ValueError("current price differs from effective history")
                    if status != "finalized_no_effect":
                        intent = prepare_preclaim_finalization(
                            principal, claim, view["revision"], payload=payload
                        )
                        if payload is None:
                            payload = {
                                "receipt_kind": PRECLAIM_RECEIPT,
                                "binding": factory.binding,
                                "operation_digest": claim["operation_digest"],
                                "params": claim["params"],
                                "run_id": run.run_id,
                                "owner": principal.user_id,
                                "business_action_id": action_context(run)["business_action_id"],
                                "outcome": "rejected_no_effect",
                                "reason_code": "preclaim_finalized",
                                "absent_source_key": source_key,
                                "preclaim_fence": intent,
                            }
                            db.add(
                                WorkflowPlan(
                                    plan_id=key,
                                    intent=TOOL,
                                    user_id=principal.user_id,
                                    status="rejected",
                                    runtime_context=encoded(
                                        {"payload": payload, "proof": proof(payload)}
                                    ),
                                )
                            )
                            db.commit()
    finally:
        factory.engine.dispose()
    # New physical connection/factory after source commit; never release a head
    # from the just-written ORM object or an uncertain commit response.
    return verify_operation(principal, operation_id, release=True)


def verify_operation(principal, operation_id, *, release=False):
    from app.application.agent_orchestrator.catalog_product_edit import (
        PRECLAIM_RECEIPT,
        original,
        reconcile_source,
        release_preclaim_verified,
        release_verified,
        verify_receipt_authority,
    )

    run, claim, status = original(principal, operation_id)
    factory = factory_for(
        principal,
        purpose=CatalogPurpose.ETL if release else CatalogPurpose.READ,
        lock_timeout=5 if release else 0,
    )
    try:
        if factory.binding != claim["binding"]:
            raise ValueError("original catalog source changed")
        with tenant_scope(int(principal.tenant_id)), factory.guard():
            factory.knowledge.validate()
            with factory() as db:
                reconcile_source(db, factory.binding, executing=claim["operation_key"])
                key = RECEIPT + canonical_hash(claim["operation_key"])
                payload = receipt_payload(db, key)
                if (
                    payload["params"] != claim["params"]
                    or payload["run_id"] != run.run_id
                    or payload["owner"] != principal.user_id
                    or payload.get("operation_digest") != claim["operation_digest"]
                ):
                    raise ValueError("original catalog receipt identity differs")
                verify_receipt_authority(claim, payload)
                product, history, dimension, effective, view = state(
                    db, claim["params"]["product_id"], principal.tenant_id
                )
                rejected = payload.get("outcome") == "rejected_no_effect"
                if rejected:
                    expected_key = canonical_hash([TOOL, claim["operation_key"]])
                    if (
                        payload.get("absent_source_key") != expected_key
                        or "event" in payload
                        or any(row.source_key == expected_key for row in history)
                    ):
                        raise ValueError(
                            "rejected original action has an effect or invalid absence proof"
                        )
                else:
                    event = next(
                        (
                            row
                            for row in history
                            if row.source_key == payload["event"]["source_key"]
                        ),
                        None,
                    )
                    if event is None or image(event) != payload["event"]:
                        raise ValueError("original catalog history event changed")
                if (
                    Decimal(str(effective_price(history_events(effective))["price"]))
                    != product.price
                ):
                    raise ValueError("current price differs from effective history")
                result = {
                    "verified": True,
                    "outcome": "rejected_no_effect" if rejected else "saved",
                    "historical_effect_verified": not rejected,
                    "fresh_save": False,  # Verification/reconciliation never dispatches.
                    "reason_code": payload.get("reason_code", ""),
                    "current_matches": not rejected
                    and view["revision"] == payload["after_revision"],
                    "product": view,
                    "operation_id": operation_id,
                    "run_id": run.run_id,
                    "request_digest": claim["request_digest"],
                    "business_action_id": payload["business_action_id"],
                    **(
                        {"receipt_kind": PRECLAIM_RECEIPT}
                        if payload.get("receipt_kind") == PRECLAIM_RECEIPT
                        else {}
                    ),
                }
            if release:
                if payload.get("receipt_kind") == PRECLAIM_RECEIPT:
                    release_preclaim_verified(principal, claim, payload)
                else:
                    release_verified(claim, payload)
            return result
    finally:
        factory.engine.dispose()


def verify_catalog_action(
    params: dict[str, Any], context: dict[str, Any], *, release: bool = False
) -> dict[str, Any]:
    from app.application.agent_orchestrator.catalog_product_edit import trusted_original

    principal, run, claim = trusted_original(params, context)
    result = verify_operation(principal, params["operation_id"], release=release)
    saved = result["outcome"] == "saved"
    current = saved and result["current_matches"]
    return {
        # Historical proof is not success of a new save, nor an unknown effect.
        "success": current,
        "outcome": "success" if current else "historical_saved" if saved else "rejected_no_effect",
        "message": (
            "本次价格修改已提交并独立核验"
            if current and release
            else "原修改已核验，当前版本一致；本次未重新保存"
            if current
            else "原修改已核验，但当前已有后续变更；本次未保存"
            if saved
            else "原操作已核验并终结，无价格写入；本次未重新保存"
            if result.get("reason_code") == "preclaim_finalized"
            else "未保存：审核前态已变化；原操作已核验无副作用"
        ),
        "historical_effect_verified": saved,
        "fresh_save": bool(current and release),
        "operation_outcome": result["outcome"],
        "current_matches": result["current_matches"],
        "retryable": False,
        "data": {"id": params["product_id"], "operation_id": params["operation_id"]},
        "business_action_id": result["business_action_id"],
        "business_verification": {
            "verified": True,
            "method": "catalog_price_receipt_v1",
            "source_binding_verified": True,
            **source_view(claim["binding"]),
        },
    }
