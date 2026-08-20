# mypy: disable-error-code="arg-type, attr-defined, no-any-return, union-attr, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.employee_executor")


def _auto_wrap_execution_result_to_change_requests(
    employee_id: str,
    user_id: int,
    input_payload: _facade().Dict[str, _facade().Any],
    result: _facade().Dict[str, _facade().Any],
) -> _facade().Dict[str, _facade().Any]:
    """Glue layer: execution outputs -> EmployeeChangeRequest.

    Priority:
    1) Respect CR ids already returned by handlers (agent deferred writes).
    2) For outputs carrying ``files_changed`` with ``path + content``, auto-create CR.
    """
    outputs = result.get("outputs") if isinstance(result.get("outputs"), list) else []
    existing_ids: set[int] = set()
    file_candidates: _facade().List[_facade().Dict[str, str]] = []
    top_level_proposed = (
        result.get("proposed_changes") if isinstance(result.get("proposed_changes"), list) else []
    )
    if top_level_proposed:
        synthetic_out = {
            "files_changed": list(top_level_proposed),
            "workspace_root": str(
                input_payload.get("project_root") or input_payload.get("workspace_root") or ""
            ),
        }
        outputs = list(outputs) + [synthetic_out]
    for out in outputs:
        if not isinstance(out, dict):
            continue
        cid_raw = out.get("change_request_id")
        try:
            cid = int(cid_raw or 0)
        except (TypeError, ValueError):
            cid = 0
        if cid > 0:
            existing_ids.add(cid)
        cid_list = (
            out.get("change_request_ids") if isinstance(out.get("change_request_ids"), list) else []
        )
        for one in cid_list:
            try:
                _cid = int(one or 0)
            except (TypeError, ValueError):
                _cid = 0
            if _cid > 0:
                existing_ids.add(_cid)
        files_changed = (
            out.get("files_changed") if isinstance(out.get("files_changed"), list) else []
        )
        proposed = (
            out.get("proposed_changes") if isinstance(out.get("proposed_changes"), list) else []
        )
        if proposed:
            files_changed = list(files_changed) + list(proposed)
        for f in files_changed:
            if isinstance(f, dict):
                path = str(f.get("path") or "").strip()
                content = f.get("content")
                if not isinstance(content, str):
                    content = ""
                ws = str(
                    f.get("workspace_root")
                    or out.get("workspace_root")
                    or input_payload.get("project_root")
                    or input_payload.get("workspace_root")
                    or ""
                ).strip()
                if path:
                    file_candidates.append({"path": path, "content": content, "workspace_root": ws})
            elif isinstance(f, str) and f.strip():
                ws = str(
                    out.get("workspace_root")
                    or input_payload.get("project_root")
                    or input_payload.get("workspace_root")
                    or ""
                ).strip()
                file_candidates.append({"path": f.strip(), "content": "", "workspace_root": ws})
    created_ids: _facade().List[int] = []
    skipped: _facade().List[_facade().Dict[str, str]] = []
    if file_candidates:
        try:
            from modstore_server.employee_change_request_service import (
                defer_write_as_change_request,
            )
            from modstore_server.employee_scope_policy import (
                workspace_policy_from_manifest,
            )

            sf = _facade().get_session_factory()
            with sf() as session:
                try:
                    pack = _facade().load_employee_pack_resolved(session, employee_id)
                except RECOVERABLE_ERRORS:
                    pack = {}
            manifest = pack.get("manifest") if isinstance(pack.get("manifest"), dict) else {}
            scope_globs, forbidden_globs, approval_required_globs = workspace_policy_from_manifest(
                manifest
            )
        except RECOVERABLE_ERRORS as exc:
            return {
                "ok": False,
                "error": f"prepare CR bridge failed: {str(exc)[:300]}",
                "change_request_ids": sorted(existing_ids),
                "existing_change_request_ids": sorted(existing_ids),
                "created_change_request_ids": [],
                "skipped": [{"reason": "prepare_failed"}],
            }
        default_workspace = ""
        try:
            from modstore_server.employee_workspace_manager import get_workspace_path

            default_workspace = str(get_workspace_path(employee_id))
        except RECOVERABLE_ERRORS:
            default_workspace = ""
        dedup_keys: set[str] = set()
        for item in file_candidates:
            path = str(item.get("path") or "").strip()
            content = str(item.get("content") or "")
            ws = str(item.get("workspace_root") or "").strip() or default_workspace
            if not path:
                skipped.append({"reason": "empty_path"})
                continue
            if not content:
                skipped.append({"path": path[:500], "reason": "missing_content"})
                continue
            if not ws:
                skipped.append({"path": path[:500], "reason": "missing_workspace_root"})
                continue
            key = f"{ws}::{path}::{hash(content)}"
            if key in dedup_keys:
                continue
            dedup_keys.add(key)
            try:
                cid = defer_write_as_change_request(
                    employee_id,
                    ws,
                    path,
                    content,
                    scope_globs=scope_globs,
                    forbidden_globs=forbidden_globs,
                    approval_required_globs=approval_required_globs,
                )
                created_ids.append(int(cid))
            except RECOVERABLE_ERRORS as exc:
                skipped.append({"path": path[:500], "reason": str(exc)[:300]})
    all_ids = sorted(existing_ids.union(created_ids))
    return {
        "ok": True,
        "existing_change_request_ids": sorted(existing_ids),
        "created_change_request_ids": created_ids,
        "change_request_ids": all_ids,
        "processed_file_candidates": len(file_candidates),
        "skipped": skipped[:100],
    }


def _handlers_execution_ok(result: _facade().Dict[str, _facade().Any]) -> bool:
    """actions 层：任一 handler 显式成功即通过；否则任一 ok=False 为失败。

    用于 Para 离线后的本地回退：``para_delegate`` 失败但 ``agent``/``vibe_edit``
    成功时不应整单 handler_failed。
    """
    outputs = result.get("outputs") if isinstance(result.get("outputs"), list) else []
    if not outputs:
        return True
    if any((isinstance(out, dict) and out.get("ok") is True for out in outputs)):
        return True
    if any((isinstance(out, dict) and out.get("ok") is False for out in outputs)):
        return False
    return True


def _handler_failure_detail(result: _facade().Dict[str, _facade().Any]) -> str:
    """Return a compact, classifiable description for the first failed handler."""
    outputs = result.get("outputs") if isinstance(result.get("outputs"), list) else []
    for out in outputs:
        if not isinstance(out, dict) or out.get("ok") is not False:
            continue
        parts = []
        for key in ("handler", "status", "source", "error"):
            value = str(out.get(key) or "").strip()
            if value:
                parts.append(f"{key}={value}")
        nested = out.get("output") if isinstance(out.get("output"), dict) else {}
        if nested:
            for key in ("error_code", "error", "summary"):
                value = str(nested.get(key) or "").strip()
                if value:
                    parts.append(f"{key}={value[:240]}")
                    break
        return "handler failed: " + " ".join(parts) if parts else "handler returned ok=False"
    return "one or more handlers returned ok=False"


def _evaluate_employee_risk_gate(
    employee_id: str,
    manifest: _facade().Dict[str, _facade().Any],
    handler_list: _facade().List[str],
    payload: _facade().Dict[str, _facade().Any],
) -> _facade().Dict[str, _facade().Any]:
    try:
        from modstore_server.employee_risk_middleware import gate_action_or_block

        return gate_action_or_block(employee_id, manifest, handler_list, payload)
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("risk middleware unavailable; blocking employee execution")
        return {
            "ok": False,
            "blocked": True,
            "pending_approval": False,
            "risk_level": "blocked",
            "decision": "blocked",
            "reason": "risk middleware unavailable; fail-closed",
            "detail": f"risk middleware error ({type(exc).__name__})",
        }
