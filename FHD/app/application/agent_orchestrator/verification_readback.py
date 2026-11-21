"""Read original business evidence; never dispatch or repair the producing action.

Adapters are chosen by the host action contract, not by an executor's claimed
``verified`` field or the presence of an arbitrary output file.
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import ParseError

from app.utils.operational_errors import RECOVERABLE_ERRORS

_FILE_ACTIONS = frozenset({("reports", "export"), ("excel_analysis", "export")})
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


def _customer(step: Any, output: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    from app.application.agent_orchestrator.tool_permission import (
        _customer_create_effect,
        _fingerprint,
        idempotency_scope_key,
    )

    params = dict(step.params)
    key = idempotency_scope_key(context, step.tool_id, step.action, params)
    if key.endswith(":"):
        return _report("inconclusive", "result_receipt_missing", "customer_transaction")
    fingerprint = _fingerprint(params)
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
    return _report(
        "inconclusive",
        "result_catalog_state_changed",
        "catalog_transaction",
        **evidence,
    )


def _file_structure(content: bytes, suffix: str) -> dict[str, Any]:
    if suffix in {".xlsx", ".xlsm", ".docx", ".pptx"}:
        from defusedxml.common import DefusedXmlException
        from defusedxml.ElementTree import fromstring

        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) > 5000 or sum(item.file_size for item in members) > 64 * 1024 * 1024:
                raise ValueError("office artifact exceeds verification budget")
            try:
                for item in members:
                    if item.filename.endswith((".xml", ".rels")):
                        fromstring(archive.read(item))
            except DefusedXmlException as exc:
                raise ValueError("unsafe office XML") from exc
    if suffix in {".xlsx", ".xlsm"}:
        from openpyxl import load_workbook
        from openpyxl.utils.exceptions import InvalidFileException

        try:
            workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=False)
        except InvalidFileException as exc:
            raise ValueError("invalid spreadsheet artifact") from exc
        try:
            populated = any(
                any(value is not None for value in row)
                for sheet in workbook
                for row in sheet.iter_rows(min_row=1, max_row=200, max_col=200, values_only=True)
            )
            if not workbook.sheetnames or not populated:
                raise ValueError("spreadsheet has no inspectable content")
            return {"format": suffix[1:], "sheets": len(workbook.sheetnames)}
        finally:
            workbook.close()
    if suffix == ".csv":
        text = content.decode("utf-8-sig")
        if "\x00" in text:
            raise ValueError("binary CSV content")
        rows = sum(1 for row in csv.reader(io.StringIO(text), strict=True) if any(row))
        if not rows:
            raise ValueError("empty CSV artifact")
        return {"format": "csv", "rows": rows}
    if suffix == ".docx":
        from docx import Document

        document = Document(io.BytesIO(content))
        if not any(p.text.strip() for p in document.paragraphs) and not document.tables:
            raise ValueError("empty document artifact")
        return {
            "format": "docx",
            "paragraphs": len(document.paragraphs),
            "tables": len(document.tables),
        }
    if suffix == ".pptx":
        from pptx import Presentation

        slides = len(Presentation(io.BytesIO(content)).slides)
        if not slides:
            raise ValueError("empty presentation artifact")
        return {"format": "pptx", "slides": slides}
    if suffix == ".pdf":
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        try:
            reader = PdfReader(io.BytesIO(content), strict=True)
            if reader.is_encrypted or not len(reader.pages):
                raise ValueError("unreadable PDF artifact")
            return {"format": "pdf", "pages": len(reader.pages)}
        except PdfReadError as exc:
            raise ValueError("invalid PDF artifact") from exc
    raise ValueError("unsupported artifact format")


def _compare_table_input(step: Any, content: bytes, suffix: str) -> dict[str, Any]:
    """Compare explicit approved tabular input with the independently parsed file."""
    rows = step.params.get("rows" if step.tool_id == "excel_analysis" else "data")
    if not isinstance(rows, list) or suffix not in {".xlsx", ".xlsm", ".csv"}:
        return {}
    if len(rows) > 50_000 or any(not isinstance(row, dict) or len(row) > 200 for row in rows):
        raise RuntimeError("table comparison exceeds verification budget")
    import pandas as pd

    from app.application.agent_orchestrator.business_action_ledger import canonical_hash

    expected = pd.DataFrame(rows)
    expected = expected.astype(object).where(pd.notna(expected), "")
    if suffix == ".csv":
        actual = pd.read_csv(io.BytesIO(content), dtype=object, keep_default_na=False)
        expected = expected.astype(str)
    else:
        actual = pd.read_excel(
            io.BytesIO(content),
            dtype=object,
            keep_default_na=False,
            engine_kwargs={"data_only": False},
        )
    try:
        pd.testing.assert_frame_equal(actual, expected, check_dtype=False, check_exact=True)
    except AssertionError as exc:
        raise ValueError("artifact differs from the approved table rows") from exc
    return {
        "input_rows_match": True,
        "input_rows_sha256": canonical_hash(rows),
        "row_count": len(rows),
    }


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
        read_verified_run_file,
    )
    from app.application.agent_orchestrator.business_action_ledger import canonical_hash

    artifacts = output.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts or len(artifacts) > 32:
        return _report("inconclusive", "result_artifact_missing", "run_artifact")
    checks = []
    for artifact in artifacts:
        if not isinstance(artifact, dict) or artifact.get("artifact_type") != "file":
            return _report("failed", "result_artifact_identity_mismatch", "run_artifact")
        artifact_id = artifact.get("artifact_id")
        metadata = artifact.get("metadata")
        if not isinstance(artifact_id, str) or not isinstance(metadata, dict):
            return _report("failed", "result_artifact_identity_mismatch", "run_artifact")
        expected_uri = f"/api/agent/runs/{run.run_id}/artifacts/{artifact_id}"
        if artifact.get("uri") != expected_uri or any(
            field in metadata and str(metadata[field]) != expected
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
        structure = _file_structure(content, actual_suffix)
        comparison = _compare_table_input(step, content, actual_suffix) if not suffix else {}
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
    catalog_action = step.tool_id == "catalog_products_v1" and step.action in {
        "append_price",
        "correct_price",
    }
    from app.application.agent_orchestrator.verification_sales import SALES_ACTIONS

    sales_action = step.tool_id == "sales" and step.action in SALES_ACTIONS
    cognition_action = step.tool_id == "enterprise_cognition" and step.action in {
        "bind_goal",
        "plan",
        "evaluate",
    }
    kellai_action = action == ("kellai", "send")
    elt_preview = action == ("elt_import", "preview")
    from app.application.agent_orchestrator.verification_surface import (
        supports_surface_verification,
    )

    surface_action = supports_surface_verification(step.tool_id, step.action)
    employee_admission = action == ("employee", "execute") and employee == "clerk"
    if not (
        action == ("customers", "create")
        or catalog_action
        or file_action
        or sales_action
        or cognition_action
        or kellai_action
        or surface_action
        or employee_admission
        or elt_preview
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
        if elt_preview:
            from app.application.agent_orchestrator.verification_elt import verify_elt_preview

            return verify_elt_preview(step, output, context)
        if employee_admission:
            return _employee_admission(run, step, call, output, context)
        if sales_action:
            from app.application.agent_orchestrator.verification_sales import verify_sales_result

            return verify_sales_result(step, call, output, context)
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
        if action == ("customers", "create"):
            from app.infrastructure.auth.business_scope_gate import (
                check_owned_business_permission,
            )

            try:
                tenant = check_owned_business_permission(actor, "customer.view")
            except HTTPException:
                return _report("inconclusive", "result_read_permission_unavailable", "task_scope")
            if str(tenant) != str(context["tenant_id"]):
                return _report("failed", "result_scope_mismatch", "task_scope")
            return _customer(step, output, context)
        if catalog_action:
            if (
                not {"product.view", "dataset.read"}
                <= agent_dataset_access_context(context).permissions
            ):
                return _report("inconclusive", "result_read_permission_unavailable", "task_scope")
            return _catalog(step, context)
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
