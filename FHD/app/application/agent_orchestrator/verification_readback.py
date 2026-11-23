"""Read original business evidence; never dispatch or repair the producing action.

Adapters are chosen by the host action contract, not by an executor's claimed
``verified`` field or the presence of an arbitrary output file.
"""

from __future__ import annotations

import csv
import zipfile
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import ParseError

from app.utils.operational_errors import RECOVERABLE_ERRORS

_EMPLOYEE_COMPLETION_ACTIONS = frozenset({"run_tools", "child_return", "chain"})
_FILE_ACTIONS = frozenset(
    {
        ("reports", "export"),
        ("excel_analysis", "export"),
        ("generate_office_document", "execute"),
        ("customers", "export"),
        ("shipment_records", "export"),
    }
)
_GENERATORS = {
    "excel-generate-employee": ".xlsx",
    "csv-generate-employee": ".csv",
    "word-generate-employee": ".docx",
    "pdf-generate-employee": ".pdf",
    "ppt-generate-employee": ".pptx",
}
_MAX_FILE_BYTES = 32 * 1024 * 1024


def _report(status: str, code: str, source: str, **evidence: Any) -> dict[str, Any]:
    return {
        "status": status,
        "code": code,
        "checks": [
            {
                "check_id": source,
                "status": {"verified": "passed", "failed": "failed"}.get(status, "unavailable"),
                "source": source,
                "evidence": evidence,
            }
        ],
    }


def _scope_matches(run: Any, step: Any, call: Any, context: dict[str, Any]) -> bool:
    saved = run.metadata.get("runtime_context") or {}
    tenant = str(context.get("tenant_id") or "")
    owner = str(context.get("user_id") or "")
    return bool(
        tenant
        and owner
        and isinstance(saved, dict)
        and str(saved.get("tenant_id") or "") == tenant
        and str(saved.get("user_id") or run.user_id) == owner
        and str(saved.get("mod_id") or saved.get("active_mod_id") or "")
        == str(context.get("mod_id") or context.get("active_mod_id") or "")
        and context.get("run_id") == run.run_id
        and context.get("step_id") == step.step_id
        and call.step_id == step.step_id
        and call.node_id == step.node_id
        and call.tool_id == step.tool_id
        and call.action == step.action
        and call.params == step.params
        and (
            not call.metadata.get("idempotency_key")
            or call.metadata["idempotency_key"] == context.get("idempotency_key")
        )
    )


def _catalog(step: Any, context: dict[str, Any]) -> dict[str, Any]:
    from app.mod_sdk.catalog_product_store import verify_catalog_action

    readback = verify_catalog_action(dict(step.params), context, release=False)
    proof = readback.get("business_verification") or {}
    if not isinstance(proof, dict) or proof.get("verified") is not True:
        return _report("inconclusive", "result_receipt_unavailable", "catalog_transaction")
    outcome = readback.get("operation_outcome")
    evidence = {
        "operation_id": step.params.get("operation_id"),
        "operation_outcome": outcome,
        "historical_effect_verified": readback.get("historical_effect_verified") is True,
        "current_matches": readback.get("current_matches") is True,
        "fresh_save": False,
    }
    if readback.get("success") is True and outcome == "saved" and evidence["current_matches"]:
        return _report("verified", "result_verified", "catalog_transaction", **evidence)
    if outcome == "rejected_no_effect":
        return _report("failed", "result_catalog_rejected", "catalog_transaction", **evidence)
    if (
        outcome == "saved"
        and readback.get("outcome") == "historical_saved"
        and evidence["historical_effect_verified"]
        and readback.get("current_matches") is False
        and readback.get("fresh_save") is False
        and proof.get("source_binding_verified") is True
        and proof.get("method") == "catalog_price_receipt_v1"
    ):
        # Verify the signed original effect, without claiming it is still current.
        # The catalog projection retains historical_saved and business success=False.
        return _report(
            "verified", "result_catalog_historical_verified", "catalog_transaction", **evidence
        )
    return _report(
        "inconclusive",
        "result_catalog_state_changed",
        "catalog_transaction",
        **evidence,
    )


def _files(
    run: Any,
    step: Any,
    call: Any,
    output: dict[str, Any],
    context: dict[str, Any],
    suffix: str,
) -> dict[str, Any]:
    from app.application.agent_orchestrator.artifact_files import (
        RUN_FILE_MIME_TYPES,
        artifact_path,
        compare_run_file_table,
        inspect_run_file_structure,
        read_verified_run_file,
    )
    from app.application.agent_orchestrator.business_action_ledger import canonical_hash

    artifacts = output.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts or len(artifacts) > 32:
        return _report("inconclusive", "result_artifact_missing", "run_artifact")
    office = (step.tool_id, step.action) == ("generate_office_document", "execute")
    business_export = step.tool_id in {"customers", "shipment_records"} and step.action == "export"
    if business_export:
        suffix = ".xlsx"
    if office:
        templated = any(
            step.params.get(key) for key in ("template_id", "template_name", "template")
        )
        suffix = (
            ".xlsx"
            if templated
            or str(step.params.get("output_format") or "docx").strip().lower() == "xlsx"
            else ".docx"
        )
    checks = []
    for artifact in artifacts:
        permitted_types = {"file", "office_document"} if office else {"file"}
        if not isinstance(artifact, dict) or artifact.get("artifact_type") not in permitted_types:
            return _report("failed", "result_artifact_identity_mismatch", "run_artifact")
        artifact_id = artifact.get("artifact_id")
        metadata = artifact.get("metadata")
        if not isinstance(artifact_id, str) or not isinstance(metadata, dict):
            return _report("failed", "result_artifact_identity_mismatch", "run_artifact")
        expected_uri = f"/api/agent/runs/{run.run_id}/artifacts/{artifact_id}"
        if artifact.get("uri") != expected_uri or any(
            (office or business_export or field in metadata)
            and str(metadata.get(field)) != expected
            for field, expected in (
                ("run_id", run.run_id),
                ("tenant_id", str(context["tenant_id"])),
                ("owner_user_id", str(context["user_id"])),
                ("step_id", step.step_id),
                ("node_id", step.node_id),
                ("call_id", call.call_id),
                ("params_sha256", canonical_hash(step.params)),
            )
        ):
            return _report("failed", "result_artifact_scope_mismatch", "run_artifact")
        path = artifact_path(run.run_id, artifact_id)
        actual_suffix = path.suffix
        permitted = {suffix} if suffix else {".xlsx", ".xlsm", ".csv"}
        size = metadata.get("size_bytes")
        if (
            actual_suffix not in permitted
            or Path(str(artifact.get("name") or "")).suffix.lower() != actual_suffix
            or artifact.get("mime_type") != RUN_FILE_MIME_TYPES[actual_suffix]
            or type(size) is not int
            or not 0 < size <= _MAX_FILE_BYTES
            or path.stat().st_size > _MAX_FILE_BYTES
        ):
            return _report("failed", "result_artifact_invalid", "run_artifact")
        if actual_suffix in {".docx", ".pptx", ".pdf"} and any(
            not metadata.get(field) for field in ("run_id", "tenant_id", "owner_user_id")
        ):
            return _report("inconclusive", "result_artifact_owner_missing", "run_artifact")
        content = read_verified_run_file(run.run_id, artifact)
        structure = inspect_run_file_structure(content, actual_suffix)
        rows = step.params.get("rows" if step.tool_id == "excel_analysis" else "data")
        comparison = compare_run_file_table(rows, content, actual_suffix) if not suffix else {}
        checks.append(
            _report(
                "verified",
                "result_verified",
                "run_artifact",
                artifact_id=artifact_id,
                sha256=metadata["sha256"],
                size_bytes=len(content),
                run_id=run.run_id,
                tenant_id=str(context["tenant_id"]),
                owner_user_id=str(context["user_id"]),
                verification_scope="artifact_integrity",
                **comparison,
                **structure,
            )["checks"][0]
        )
    return {"status": "verified", "code": "result_verified", "checks": checks}


def _employee_admission(run, step, call, output, context) -> dict[str, Any]:
    from app.application.agent_orchestrator.business_action_ledger import canonical_hash
    from app.application.employee_runtime.task_continuity import (
        SOURCE,
        _public_task,
        _step_from,
        load_employee_task_ledger,
        task_admission_origin,
    )
    from app.infrastructure.workspace import workspace_root

    source = "employee_task_ledger"
    params = step.params
    payload = dict(params["input"]) if isinstance(params.get("input"), dict) else {}
    for key, value in params.items():
        if key not in {
            "employee_id",
            "pack_id",
            "tool_name",
            "id",
            "task",
            "user_request",
            "input",
        }:
            payload.setdefault(key, value)
    if (
        str(payload.get("continuity_action") or "").strip() != "start"
        or payload.get("execute_limit") is not None
    ):
        return _report("inconclusive", "result_verifier_unavailable", source)
    root = workspace_root()
    origin = task_admission_origin({**context, "node_id": step.node_id}, root)
    contract = call.metadata.get("verification_contract") or {}
    if (
        any(
            not origin[key]
            for key in ("run_id", "step_id", "node_id", "idempotency_key", "user_id", "tenant_id")
        )
        or origin["workspace_sha256"] != contract.get("workspace_sha256")
        or context.get("node_id", step.node_id) != step.node_id
    ):
        return _report("failed", "result_employee_scope_mismatch", source)
    ledger = load_employee_task_ledger(root)
    matches = [row for row in ledger["tasks"].values() if row.get("agent_admission") == origin]
    if len(matches) != 1:
        return _report("inconclusive", "result_employee_admission_unavailable", source)
    row = matches[0]
    data = output.get("data") or {}
    task_id = row["task_id"]
    events = [item for item in ledger["events"] if item.get("task_id") == task_id]
    if (
        ledger["tasks"].get(task_id) is not row
        or str(row.get("user_id")) != origin["user_id"]
        or str(row.get("tenant_id")) != origin["tenant_id"]
        or row.get("owner_employee") != "clerk"
        or row.get("holder_employee") != "clerk"
        or data.get("source") != SOURCE
        or data.get("task_id") != task_id
        or data.get("employee_id") != "clerk"
        or data.get("business_success") is not False
        or data.get("task") != _public_task(row)
        or len(events) != 1
        or events[0].get("kind") != "task_created"
        or events != data.get("events")
        or events[0].get("evidence") != data.get("evidence")
    ):
        return _report("failed", "result_employee_admission_mismatch", source)
    expected_steps = [
        _step_from(task_id, raw, index) for index, raw in enumerate(payload.get("steps") or [])
    ]
    expected = {
        "goal": str(
            payload.get("goal")
            or str(
                params.get("task")
                or params.get("user_request")
                or params.get("message")
                or run.message
                or ""
            ).strip()
        ),
        "conditions": dict(payload.get("conditions") or {}),
        "constraints": list(payload.get("constraints") or []),
        "business_data": dict(payload.get("business_data") or {}),
        "requirements": list(payload.get("requirements") or []),
        "steps": expected_steps,
        "status": "running",
        "error_code": "",
        "error_message": "",
        "result_payload": {},
        "completed_steps": [],
        "authorized_employees": ["clerk"],
        "grants": {"clerk": ["*"]},
    }
    if any(row.get(key) != value for key, value in expected.items()):
        return _report("inconclusive", "result_employee_admission_changed", source)
    return _report(
        "verified",
        "result_verified",
        source,
        scope="task_admission",
        task_id=task_id,
        current_child_status=row["status"],
        admission_verified=True,
        business_effect_verified=False,
        origin_sha256=canonical_hash(origin),
        task_sha256=canonical_hash(row),
    )


def verify_independent_result(
    *, run: Any, step: Any, call: Any, output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Read server-selected evidence under the original authenticated task scope."""
    action = (step.tool_id, step.action)
    employee = (
        str(
            next(
                (
                    step.params[key]
                    for key in ("employee_id", "pack_id", "tool_name", "id")
                    if step.params.get(key)
                ),
                "",
            )
        )
        if action == ("employee", "execute")
        else ""
    )
    file_action = action in _FILE_ACTIONS or (
        action == ("employee", "execute") and employee in _GENERATORS
    )
    from app.domain.workbook_write_contract import WORKBOOK_WRITER

    workbook_write = action == ("employee", "execute") and employee == WORKBOOK_WRITER
    catalog_action = step.tool_id == "catalog_products_v1" and step.action in {
        "append_price",
        "correct_price",
    }
    from app.application.agent_orchestrator.verification_transactions import (
        PURCHASE_ACTIONS,
        SALES_ACTIONS,
    )

    sales_action = step.tool_id == "sales" and step.action in SALES_ACTIONS
    sales_closed_loop = action == ("sales", "execute_closed_loop")
    purchase_action = step.tool_id == "purchase" and step.action in PURCHASE_ACTIONS
    cognition_action = step.tool_id == "enterprise_cognition" and step.action in {
        "bind_goal",
        "plan",
        "evaluate",
    }
    kellai_action = action == ("kellai", "send")
    from app.application.agent_orchestrator.verification_surface import (
        supports_surface_verification,
    )

    surface_action = supports_surface_verification(step.tool_id, step.action)
    from app.application.agent_orchestrator.verification_multitask import (
        OPERATIONS,
        employee_payload,
    )

    employee_completion = (
        action == ("employee", "execute")
        and str(employee_payload(step.params).get("continuity_action") or "").strip() in OPERATIONS
    )
    employee_admission = action == ("employee", "execute") and employee == "clerk"
    office_stage = action == ("excel_import", "office_stage")
    template_mutation = step.tool_id == "document_template" and step.action in {
        "create",
        "update",
        "delete",
    }
    business_write = action == ("business_db", "write")
    shipment_mutation = step.tool_id == "shipment_records" and step.action in {
        "create",
        "update",
        "delete",
    }
    stock_movement = step.tool_id == "inventory" and step.action in {"stock_in", "stock_out"}
    dataset_ingest = action in {
        ("dataset_rag", "ingest_document"),
        ("dataset_rag", "rollback_version"),
    }
    dataset_rebuild = step.tool_id == "dataset_rag" and step.action in {
        "rebuild_index",
        "cancel_rebuild",
    }
    customer_write = step.tool_id == "customers" and step.action in {
        "update",
        "delete",
        "batch_delete",
    }
    elt_preview = action == ("elt_import", "preview")
    elt_execution = action == ("elt_import", "execute")
    memory_action = step.tool_id == "memory_v2" and step.action in {
        "propose_candidate",
        "confirm",
        "reject",
        "correct",
        "delete",
    }
    if not (
        action == ("customers", "create")
        or catalog_action
        or file_action
        or workbook_write
        or sales_action
        or sales_closed_loop
        or purchase_action
        or cognition_action
        or kellai_action
        or surface_action
        or employee_admission
        or elt_preview
        or employee_completion
        or office_stage
        or template_mutation
        or business_write
        or shipment_mutation
        or stock_movement
        or dataset_ingest
        or dataset_rebuild
        or customer_write
        or elt_preview
        or elt_execution
        or memory_action
    ):
        return _report("inconclusive", "result_verifier_unavailable", "host_registry")
    if not _scope_matches(run, step, call, context):
        return _report("failed", "result_scope_mismatch", "task_scope")
    if employee and output.get("employee_id", employee) != employee:
        return _report("failed", "result_employee_mismatch", "task_scope")
    try:
        from fastapi import HTTPException

        from app.infrastructure.auth.agent_mod_scope import (
            AgentModAuthorizationError,
            _bound_actor,
            agent_dataset_access_context,
        )

        try:
            actor = _bound_actor(context)
        except AgentModAuthorizationError:
            return _report("inconclusive", "result_read_permission_unavailable", "task_scope")
        if surface_action:
            from app.application.agent_orchestrator.verification_surface import (
                verify_surface_result,
            )

            return verify_surface_result(run, step, call, output, context)
        if workbook_write:
            from app.application.agent_orchestrator.verification_workbook import verify_workbook

            return verify_workbook(run, step, call, output, context)
        if employee_completion:
            from app.application.agent_orchestrator.verification_multitask import (
                verify_employee_completion,
            )

            return verify_employee_completion(run, step, call, output, context, employee)
        if employee_admission:
            return _employee_admission(run, step, call, output, context)
        if office_stage:
            from app.application.elt.docking_approval import verify_office_stage_submission

            return verify_office_stage_submission(run, output, context)
        if template_mutation:
            from app.application.template_mutation_receipt import verify_template_mutation

            return verify_template_mutation(run, step, call, output, context)
        if memory_action:
            from app.application.memory_v2_facade import verify_memory_mutation

            return verify_memory_mutation(step, call, output, context)
        if business_write:
            from app.application.business_db_write_verification import (
                verify_independent_business_write,
            )

            return verify_independent_business_write(step, output, context)
        if shipment_mutation:
            from app.application.shipment_app_service import verify_agent_shipment_mutation

            return verify_agent_shipment_mutation(step, output, context)
        if stock_movement:
            from app.application.inventory_app_service import verify_agent_stock_movement

            return verify_agent_stock_movement(step, output, context)
        if sales_closed_loop:
            from app.application.sales.verification import verify_agent_closed_loop

            return verify_agent_closed_loop(step, output, context)
        if dataset_rebuild:
            from app.application.dataset_rag.rebuild_coordinator import verify_agent_rebuild

            return verify_agent_rebuild(step, call, output, context)
        if dataset_ingest:
            from app.application.dataset_rag.document_lifecycle import verify_agent_document

            return verify_agent_document(step, call, output, context)
        if customer_write:
            from app.application.business_db_write_verification import (
                verify_independent_customer_write,
            )

            return verify_independent_customer_write(step, output, context)
        if elt_preview:
            from app.application.elt.preview_confirmation import verify_agent_preview

            return verify_agent_preview(call, output, context)
        if elt_execution:
            from app.application.elt.preview_confirmation import verify_agent_execution

            return verify_agent_execution(step, call, output, context)
        if sales_action:
            from app.application.agent_orchestrator.verification_transactions import (
                verify_sales_result,
            )

            return verify_sales_result(step, call, output, context)
        if purchase_action:
            from app.application.agent_orchestrator.verification_transactions import (
                verify_purchase_result,
            )

            return verify_purchase_result(step, call, output, context)
        if cognition_action:
            from app.application.agent_orchestrator.verification_cognition import (
                verify_cognition_result,
            )

            return verify_cognition_result(run, step, output, context)
        if kellai_action:
            from app.application.agent_orchestrator.verification_kellai import (
                verify_kellai_delivery,
            )

            return verify_kellai_delivery(run, step, call, context)
        if action in {("customers", "create"), ("customers", "export")}:
            from app.infrastructure.auth.business_scope_gate import (
                check_owned_business_permission,
            )

            try:
                tenant = check_owned_business_permission(actor, "customer.view")
            except HTTPException:
                return _report("inconclusive", "result_read_permission_unavailable", "task_scope")
            if str(tenant) != str(context["tenant_id"]):
                return _report("failed", "result_scope_mismatch", "task_scope")
            if action == ("customers", "create"):
                from app.application.business_db_write_verification import verify_customer_creation

                return verify_customer_creation(step, output, context)
        if catalog_action:
            if (
                not {"product.view", "dataset.read"}
                <= agent_dataset_access_context(context).permissions
            ):
                return _report("inconclusive", "result_read_permission_unavailable", "task_scope")
            return _catalog(step, context)
        if action == ("shipment_records", "export"):
            from app.domain.shared_services.auth_service import get_auth_service

            if "shipment.view" not in get_auth_service().get_user_permissions(actor):
                return _report("inconclusive", "result_read_permission_unavailable", "task_scope")
        return _files(run, step, call, output, context, _GENERATORS.get(employee, ""))
    except (PermissionError, OSError, RuntimeError, ImportError):
        return _report("inconclusive", "result_source_unavailable", "independent_readback")
    except (AgentModAuthorizationError, HTTPException):
        return _report("inconclusive", "result_read_permission_unavailable", "task_scope")
    except (
        ValueError,
        zipfile.BadZipFile,
        csv.Error,
        ParseError,
    ):
        return _report("failed", "result_evidence_mismatch", "independent_readback")
    except RECOVERABLE_ERRORS:
        return _report("inconclusive", "result_source_unavailable", "independent_readback")
