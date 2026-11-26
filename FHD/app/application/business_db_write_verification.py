"""Tenant-scoped read-after-write verification for the Business Harness."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.domain.shared_services.tools_workflow_common import _result_record_id as _nested_id


def _normalized_fields(payload: dict[str, Any]) -> dict[str, Any]:
    nested = payload.get("changes")
    if not isinstance(nested, dict):
        nested = payload.get("fields")
    return dict(nested) if isinstance(nested, dict) else dict(payload)


def _model_config(entity: str):
    if entity == "customers":
        from app.db.models.purchase_unit import PurchaseUnit

        return (
            PurchaseUnit,
            {
                "unit_name": "unit_name",
                "customer_name": "unit_name",
                "name": "unit_name",
                "contact_person": "contact_person",
                "contact_phone": "contact_phone",
                "contact_address": "address",
                "address": "address",
            },
            ("unit_name", "customer_name", "name"),
        )
    if entity == "products":
        from app.db.models.product import Product

        return (
            Product,
            {
                "name_or_model": "name",
                "product_name": "name",
                "name": "name",
                "model_number": "model_number",
                "product_code": "model_number",
                "unit_price": "price",
                "price": "price",
                "measure_unit": "unit",
                "unit": "unit",
            },
            ("model_number", "product_code", "product_name", "name", "name_or_model"),
        )
    if entity == "materials":
        from app.db.models.material import Material

        return (
            Material,
            {
                "material_code": "material_code",
                "material_name": "name",
                "name": "name",
                "unit_price": "unit_price",
                "quantity": "quantity",
            },
            ("material_code", "material_name", "name"),
        )
    if entity == "shipment_records":
        from app.db.models.shipment import ShipmentRecord

        return (
            ShipmentRecord,
            {
                "purchase_unit": "purchase_unit",
                "unit_name": "purchase_unit",
                "product_name": "product_name",
                "model_number": "model_number",
                "status": "status",
                "quantity_kg": "quantity_kg",
                "quantity_tins": "quantity_tins",
                "tin_spec": "tin_spec",
                "unit_price": "unit_price",
                "amount": "amount",
                "printed_at": "printed_at",
                "printer_name": "printer_name",
                "raw_text": "raw_text",
                "parsed_data": "parsed_data",
                "created_at": "created_at",
            },
            ("id", "record_id"),
        )
    raise ValueError(f"unsupported entity: {entity}")


def _same_value(actual: Any, expected: Any) -> bool:
    if isinstance(actual, Decimal):
        try:
            return actual == Decimal(str(expected))
        except (ValueError, TypeError):
            return False
    if isinstance(actual, float):
        try:
            return abs(actual - float(expected)) < 1e-9
        except (ValueError, TypeError):
            return False
    return actual == expected or str(actual) == str(expected)


def verify_business_db_write(
    *,
    entity: str,
    operation: str,
    payload: dict[str, Any],
    result: dict[str, Any],
    verify_empty_fields: bool = False,
) -> dict[str, Any]:
    """Return a success result only after committed tenant data can be read back."""

    if not result.get("success"):
        return result

    from app.db.session import get_db
    from app.infrastructure.tenant_scope import tenant_id_for_write

    tenant_id = tenant_id_for_write()
    verification: dict[str, Any] = {
        "verified": False,
        "entity": entity,
        "operation": operation,
        "tenant_id": tenant_id,
        "state": "unverified",
        "checked_fields": [],
    }
    try:
        model, field_map, selector_keys = _model_config(entity)
        record_id = _nested_id(result) or _nested_id(payload)
        fields = _normalized_fields(payload)
        with get_db() as db:
            query = db.query(model).filter(model.tenant_id == tenant_id)
            if record_id:
                query = query.filter(model.id == record_id)
            else:
                selector = next(
                    (
                        (field_map.get(key, key), fields.get(key))
                        for key in selector_keys
                        if fields.get(key) not in (None, "")
                    ),
                    None,
                )
                if selector is None:
                    verification["reason"] = "write_result_missing_identity"
                    return _failed_result(result, verification)
                column_name, value = selector
                query = query.filter(getattr(model, column_name) == value)
            rows = query.limit(2).all()
            snapshots: list[dict[str, Any]] = [
                {
                    "id": int(row.id),
                    "is_active": bool(row.is_active) if hasattr(row, "is_active") else None,
                    "values": {
                        column_name: getattr(row, column_name)
                        for column_name in set(field_map.values())
                    },
                }
                for row in rows
            ]

        if len(snapshots) > 1:
            verification["reason"] = "ambiguous_readback"
            return _failed_result(result, verification)
        record = snapshots[0] if snapshots else None
        if record_id:
            verification["record_id"] = record_id

        if operation == "delete":
            inactive = record is not None and record["is_active"] is False
            verification["state"] = (
                "absent" if record is None else "inactive" if inactive else "present"
            )
            verification["verified"] = record is None or inactive
            if not verification["verified"]:
                verification["reason"] = "record_still_active"
                return _failed_result(result, verification)
            return {**result, "business_verification": verification}

        if record is None:
            verification.update(state="absent", reason="record_not_found")
            return _failed_result(result, verification)
        if record["is_active"] is False:
            verification.update(state="inactive", reason="record_inactive")
            return _failed_result(result, verification)

        checked: list[str] = []
        for input_name, column_name in field_map.items():
            if input_name not in fields or (
                not verify_empty_fields and fields[input_name] in (None, "")
            ):
                continue
            if not _same_value(record["values"][column_name], fields[input_name]):
                verification.update(
                    state="present", reason="field_mismatch", checked_fields=checked
                )
                return _failed_result(result, verification)
            checked.append(column_name)
        # Seeing an existing row by ID is not evidence that a requested
        # create/update/upsert happened. Require at least one value read back
        # from the authoritative database before accepting the business result.
        if not checked and operation in {"create", "update", "upsert"}:
            verification.update(state="present", reason="no_verifiable_fields")
            return _failed_result(result, verification)
        verification.update(
            verified=True,
            state="present",
            record_id=record["id"],
            checked_fields=sorted(set(checked)),
        )
        return {**result, "business_verification": verification}
    except (AttributeError, RuntimeError, SQLAlchemyError, TypeError, ValueError):
        verification["reason"] = "readback_unavailable"
        return _failed_result(result, verification)


def _failed_result(result: dict[str, Any], verification: dict[str, Any]) -> dict[str, Any]:
    return {
        **result,
        "success": False,
        "error_code": "business_write_verification_failed",
        "message": "业务写入未通过数据库回查，已按失败处理。",
        "business_verification": verification,
    }


def verify_independent_business_write(
    step: Any, output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Re-read the original write under its live actor and tenant, never its verdict."""
    from app.application.agent_orchestrator.tool_permission import _ENTITY_READ_PERMISSIONS
    from app.application.agent_orchestrator.verification_readback import _report
    from app.domain.shared_services.tools_workflow_common import _normalize_business_db_entity

    params = step.params
    entity = _normalize_business_db_entity(params.get("entity"))
    operation = str(params.get("operation") or params.get("op") or "create").strip().lower()
    payload = params.get("payload")
    if (
        entity not in _ENTITY_READ_PERMISSIONS
        or operation not in {"create", "ensure_exists", "upsert", "update", "delete"}
        or not isinstance(payload, dict)
    ):
        return _report("inconclusive", "result_verifier_unavailable", "business_database")
    return _verify_independent_write(step, output, context, entity, operation, payload)


def verify_independent_customer_write(
    step: Any, output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Bind direct customer mutations to the same durable claim and scoped readback."""
    from app.application.agent_orchestrator.verification_readback import _report
    from app.application.customer_deletion import valid_customer_delete_ids

    params = step.params
    if step.action == "update":
        if not _nested_id(params):
            return _report("failed", "result_business_identity_mismatch", "business_database")
        return _verify_independent_write(
            step,
            output,
            context,
            "customers",
            "update",
            params,
            verify_empty_fields=context.get("service_source") == "fastapi_customer_route",
        )
    # The existing generic row reader cannot prove that all cascading product and
    # shipment effects match the original deletion. Keep that broader claim closed.
    if step.action not in {"delete", "batch_delete"} or params.get("force"):
        return _report("inconclusive", "result_verifier_unavailable", "business_database")
    ids = (
        params.get("ids") or params.get("customer_ids")
        if step.action == "batch_delete"
        else [params.get("id", params.get("customer_id"))]
    )
    if not valid_customer_delete_ids(ids):
        return _report("failed", "result_business_identity_mismatch", "business_database")
    count = output.get("deleted_count")
    if type(count) is not int or count != len(set(ids)):
        return _report("failed", "result_business_state_mismatch", "business_database")
    reports = [
        _verify_independent_write(step, output, context, "customers", "delete", {"id": record_id})
        for record_id in sorted(set(ids))
    ]
    for report in reports:
        if report["status"] != "verified":
            return report
    evidence = dict(reports[0]["checks"][0]["evidence"])
    evidence.pop("record_id", None)
    return _report(
        "verified", "result_verified", "business_database", **evidence, record_ids=sorted(set(ids))
    )


def _verify_independent_write(
    step: Any,
    output: dict[str, Any],
    context: dict[str, Any],
    entity: str,
    operation: str,
    payload: dict[str, Any],
    *,
    verify_empty_fields: bool = False,
) -> dict[str, Any]:
    from app.application.agent_orchestrator.business_action_ledger import canonical_hash
    from app.application.agent_orchestrator.tool_permission import (
        _ENTITY_READ_PERMISSIONS,
        _fingerprint,
        _reread_claim,
        idempotency_scope_key,
    )
    from app.application.agent_orchestrator.verification_readback import _report
    from app.domain.shared_services.auth_service import get_auth_service
    from app.infrastructure.auth.agent_mod_scope import _bound_actor, agent_mod_execution_scope
    from app.infrastructure.tenant_scope import tenant_scope
    from app.request_active_mod_ctx import reset_request_active_mod_id, set_request_active_mod_id

    params = step.params
    actor = _bound_actor(context)
    if _ENTITY_READ_PERMISSIONS[entity] not in get_auth_service().get_user_permissions(actor):
        return _report("inconclusive", "result_read_permission_unavailable", "task_scope")
    tenant_text = str(context.get("tenant_id") or "")
    if not tenant_text.isdecimal() or int(tenant_text) <= 0:
        return _report("failed", "result_scope_mismatch", "task_scope")
    tenant = int(tenant_text)
    for body in (payload, output, output.get("data")):
        if isinstance(body, dict) and any(
            isinstance(body.get(key), bool)
            for key in ("id", "customer_id", "product_id", "material_id", "record_id")
        ):
            return _report("failed", "result_business_identity_mismatch", "business_database")
    submitted_id, returned_id = _nested_id(payload), _nested_id(output)
    if submitted_id and returned_id and submitted_id != returned_id:
        return _report("failed", "result_business_identity_mismatch", "business_database")
    key = idempotency_scope_key(context, step.tool_id, step.action, params)
    receipt = _reread_claim(key, durable_read_only=True)
    if receipt is None or receipt.get("inflight") or not isinstance(receipt.get("output"), dict):
        return _report("inconclusive", "result_receipt_unavailable", "tool_idempotency")
    if receipt.get("fingerprint") != _fingerprint(params, context) or canonical_hash(
        receipt["output"]
    ) != canonical_hash(output):
        return _report("failed", "result_receipt_mismatch", "tool_idempotency")
    token = set_request_active_mod_id("")
    try:
        with agent_mod_execution_scope(context.get("_mod_authorization")), tenant_scope(tenant):
            readback = verify_business_db_write(
                entity=entity,
                operation=operation,
                payload=payload,
                result={
                    key: value for key, value in output.items() if key != "business_verification"
                },
                verify_empty_fields=verify_empty_fields,
            )
    finally:
        reset_request_active_mod_id(token)
    evidence = readback.get("business_verification") or {}
    if evidence.get("verified") is not True:
        unavailable = evidence.get("reason") in {
            "readback_unavailable",
            "write_result_missing_identity",
        }
        return _report(
            "inconclusive" if unavailable else "failed",
            "result_source_unavailable" if unavailable else "result_business_state_mismatch",
            "business_database",
            **evidence,
        )
    return _report(
        "verified",
        "result_verified",
        "business_database",
        params_sha256=canonical_hash(params),
        receipt_sha256=canonical_hash(receipt["output"]),
        receipt_key_sha256=canonical_hash(key),
        scope="current_business_state",
        **evidence,
    )


__all__ = ["verify_business_db_write"]


def verify_customer_creation(
    step: Any, output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    from app.application.agent_orchestrator.tool_permission import (
        _customer_create_effect,
        _fingerprint,
        idempotency_scope_key,
    )
    from app.application.agent_orchestrator.verification_readback import _report

    params = dict(step.params)
    key = idempotency_scope_key(context, step.tool_id, step.action, params)
    if key.endswith(":"):
        return _report("inconclusive", "result_receipt_missing", "customer_transaction")
    fingerprint = _fingerprint(params, context)
    from app.infrastructure.auth.agent_mod_scope import agent_mod_execution_scope
    from app.infrastructure.tenant_scope import tenant_scope
    from app.request_active_mod_ctx import (
        reset_request_active_mod_id,
        set_request_active_mod_id,
    )

    # The producing child restored these ContextVars only in its own process.
    # Clear an unrelated request's Mod even when the original run has no Mod.
    token = set_request_active_mod_id("")
    try:
        with (
            agent_mod_execution_scope(context.get("_mod_authorization")),
            tenant_scope(int(context["tenant_id"])),
        ):
            effect, receipt = _customer_create_effect(
                str(context["tenant_id"]),
                params,
                key=key,
                fingerprint=fingerprint,
                receipted=False,
            )
    finally:
        reset_request_active_mod_id(token)
    if effect != "matched" or not isinstance(receipt, dict):
        return _report("inconclusive", "result_receipt_unavailable", "customer_transaction")
    actual = receipt["data"]
    returned = output.get("data")
    returned = returned if isinstance(returned, dict) else {}
    claimed_id = output.get("id", returned.get("id"))
    mismatch = claimed_id is not None and (
        type(claimed_id) is not int or claimed_id != actual["id"]
    )
    for field in (
        "id",
        "tenant_id",
        "customer_name",
        "contact_person",
        "contact_phone",
        "contact_address",
    ):
        if field in returned and str(returned[field]) != str(actual[field]):
            mismatch = True
    if mismatch:
        return _report("failed", "result_customer_mismatch", "customer_transaction")
    return _report(
        "verified",
        "result_verified",
        "customer_transaction",
        customer_id=actual["id"],
        tenant_id=str(actual["tenant_id"]),
        params_sha256=fingerprint,
        version=actual["version"],
    )
