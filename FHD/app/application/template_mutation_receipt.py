"""Read original template transactions without hydrating or repairing the library."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.domain.task_lifecycle.control import SessionBook

TEMPLATE_MUTATIONS = frozenset({"create", "update", "delete"})
_MODULE = "document_template_mutation"
_CLAIM: ContextVar[tuple[str, str, dict[str, Any], str] | None] = ContextVar(
    "document_template_claim", default=None
)


def _row(db, template_id, tenant):
    return (
        db.execute(
            text(
                "SELECT id, tenant_id, template_key, template_name, template_type, "
                "original_file_path, analyzed_data, editable_config, zone_config, "
                "merged_cells_config, style_config, business_rules, is_active "
                "FROM templates WHERE id=:id AND tenant_id=:tenant"
            ),
            {"id": template_id, "tenant": int(tenant)},
        )
        .mappings()
        .first()
    )


def _db_id(value):
    raw = str(value or "").strip().removeprefix("db:")
    return int(raw) if raw.isdecimal() and int(raw) > 0 else None


def _file_sha(path: str, tenant: str) -> str:
    if not path:
        return ""
    from app.application.shipment_excel_elt_security import (
        _open_directory_under_root,
        _windows_open_relative,
    )
    from app.utils.path_io.path_utils import get_app_data_dir

    root = Path(get_app_data_dir(create=False)).resolve()
    candidate = Path(path)
    roots = [root / "templates/reviewed_excel" / tenant]
    roots.extend(
        root / "tenants" / tenant / folder
        for folder in ("templates", "document_templates", "template_library")
    )
    if (
        ".." in candidate.parts
        or candidate != candidate.resolve(strict=True)
        or not any(candidate.is_relative_to(owned) for owned in roots)
    ):
        raise ValueError("template file is outside the original tenant directory")
    name = re.fullmatch(r"[^/\\\x00]{1,255}", candidate.name)
    if name is None or name.group(0) in {".", ".."}:
        raise ValueError("invalid template filename")
    filename = name.group(0)
    directory = _open_directory_under_root(root, candidate.parent, create=False)
    try:
        descriptor = (
            _windows_open_relative(
                directory, filename, directory=False, create=False, for_input=True
            )
            if os.name == "nt"
            else os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        )
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or not 0 < info.st_size <= 32 * 1024 * 1024
            ):
                raise ValueError("template file is not a bounded regular file")
            content = stream.read(32 * 1024 * 1024 + 1)
            if len(content) != info.st_size:
                raise ValueError("template file changed during readback")
            return hashlib.sha256(content).hexdigest()
    finally:
        os.close(directory)


def _binding(context, action):
    fields = ("run_id", "step_id", "node_id", "call_id", "input_sha256", "user_id", "tenant_id")
    return {"action": action, **{key: str(context.get(key) or "") for key in fields}}


@contextmanager
def template_mutation_claim(key, fingerprint, context, action):
    token = _CLAIM.set((key, fingerprint, dict(context), action))
    try:
        yield
    finally:
        _CLAIM.reset(token)


def record_template_mutation(db, template_id, action):
    """Stage proof beside the changed row; the existing writer owns the commit."""
    claim = _CLAIM.get()
    if claim is None:
        return
    key, fingerprint, context, expected_action = claim
    binding = _binding(context, action)
    if action != expected_action or not key or not all(binding.values()):
        raise ValueError("template receipt is missing its original execution binding")
    row = _row(db, template_id, binding["tenant_id"])
    if row is None or (row["is_active"] == 0) != (action == "delete"):
        raise ValueError("template receipt does not match the committed tenant state")
    SessionBook(db).put(
        _MODULE,
        binding["tenant_id"],
        key,
        {
            "binding": binding,
            "fingerprint": fingerprint,
            "template_id": int(row["id"]),
            "row_sha256": canonical_hash(dict(row)),
            "file_sha256": _file_sha(str(row["original_file_path"] or ""), binding["tenant_id"]),
        },
    )


def template_execution_denial(step, context) -> dict[str, Any] | None:
    """Reject proven absent/installed targets before a mutating handler is entered."""
    if step.tool_id != "document_template" or step.action not in {"update", "delete"}:
        return None
    from app.db import session as db_session
    from app.infrastructure.auth.agent_mod_scope import _bound_actor
    from app.utils.path_io.path_utils import get_base_dir

    _bound_actor(context)
    raw = str(step.params.get("id") or "").strip()
    status = 0
    if step.action == "delete" and raw.startswith("fs:"):
        name = raw[3:]
        base = Path(str(context.get("template_base_dir") or get_base_dir()))
        if name and Path(name).name == name and not any(c in name for c in "\\:/\0"):
            if any(
                os.path.lexists(folder / name)
                for folder in (base, base / "templates", base / "resources/templates")
            ):
                status = 403
    elif (template_id := _db_id(raw)) is not None:
        try:
            with db_session.SessionLocal() as db:
                if _row(db, template_id, str(context.get("tenant_id") or "")) is None:
                    status = 404
        except OperationalError:
            # The original handler remains responsible for unavailable storage.
            return None
    if not status:
        return None
    return {
        "success": False,
        "http_status_code": status,
        "error_code": "template_target_not_owned"
        if status == 404
        else "template_builtin_read_only",
        "message": "模板不存在" if status == 404 else "内置模板不可删除，请先另存为自定义模板",
        "outcome": "denied",
        "retryable": False,
    }


def verify_template_mutation(run, step, call, output, context) -> dict[str, Any]:
    from app.application.agent_orchestrator.tool_permission import (
        _fingerprint,
        _reread_claim,
        idempotency_scope_key,
    )
    from app.application.agent_orchestrator.verification_readback import _report
    from app.db import session as db_session
    from app.domain.shared_services.auth_service import get_auth_service
    from app.domain.shared_services.document_templates.crud import _build_template_payload_from_row
    from app.infrastructure.auth.agent_mod_scope import _bound_actor, agent_mod_execution_scope
    from app.infrastructure.tenant_scope import owned_tenant_scope
    from app.request_active_mod_ctx import reset_request_active_mod_id, set_request_active_mod_id

    source = "template_transaction"
    actor = _bound_actor(context)
    if "elt.template.manage" not in get_auth_service().get_user_permissions(actor):
        return _report("inconclusive", "result_read_permission_unavailable", source)
    tenant = str(context.get("tenant_id") or "")
    key = idempotency_scope_key(context, step.tool_id, step.action, step.params)
    original = _reread_claim(key, durable_read_only=True)
    if original is None or original.get("inflight") or not isinstance(original.get("output"), dict):
        return _report("inconclusive", "result_receipt_unavailable", source)
    fingerprint = _fingerprint(step.params, context)
    if original.get("fingerprint") != fingerprint or canonical_hash(
        original["output"]
    ) != canonical_hash(output):
        return _report("failed", "result_receipt_mismatch", source)
    token = set_request_active_mod_id("")
    try:
        with (
            owned_tenant_scope(int(tenant)),
            agent_mod_execution_scope(context.get("_mod_authorization")),
            db_session.SessionLocal() as db,
        ):
            proof = SessionBook(db).get(_MODULE, tenant, key)
            binding = _binding(
                {
                    **context,
                    "run_id": run.run_id,
                    "step_id": step.step_id,
                    "node_id": step.node_id,
                    "call_id": call.call_id,
                    "input_sha256": canonical_hash(step.params),
                },
                step.action,
            )
            if not proof.get("template_id"):
                return _report("inconclusive", "result_template_receipt_unavailable", source)
            if proof.get("binding") != binding or proof.get("fingerprint") != fingerprint:
                return _report("failed", "result_template_receipt_mismatch", source)
            row = _row(db, proof["template_id"], tenant)
            if row is None or canonical_hash(dict(row)) != proof.get("row_sha256"):
                return _report("failed", "result_template_state_mismatch", source)
            data = output.get("deleted" if step.action == "delete" else "template")
            if (
                not isinstance(data, dict)
                or _db_id(data.get("db_id") or data.get("id")) != row["id"]
            ):
                return _report("failed", "result_template_identity_mismatch", source)
            if (
                step.action != "create"
                and not str(step.params.get("id") or "").startswith("fs:")
                and _db_id(step.params.get("id")) != row["id"]
            ):
                return _report("failed", "result_template_identity_mismatch", source)
            if step.action == "delete":
                if (
                    row["is_active"] != 0
                    or data.get("soft_deleted") is not True
                    or data.get("id") != str(step.params["id"])
                    or ("path" in data and data["path"] != row["original_file_path"])
                ):
                    return _report("failed", "result_template_state_mismatch", source)
            else:
                expected = _build_template_payload_from_row(SimpleNamespace(**dict(row)))
                if row["is_active"] == 0 or any(
                    data.get(field) != value for field, value in expected.items()
                ):
                    return _report("failed", "result_template_state_mismatch", source)
            path = str(row["original_file_path"] or "")
            try:
                file_sha = _file_sha(path, tenant)
            except (OSError, ValueError):
                return _report("inconclusive", "result_template_file_unavailable", source)
            if file_sha != proof.get("file_sha256"):
                return _report("failed", "result_template_file_mismatch", source)
            return _report(
                "verified",
                "result_verified",
                source,
                scope="template_current_state",
                template_id=int(row["id"]),
                tenant_id=tenant,
                owner_user_id=str(actor.id),
                row_sha256=proof["row_sha256"],
                file_sha256=proof["file_sha256"],
                params_sha256=canonical_hash(step.params),
                receipt_key_sha256=canonical_hash(key),
                receipt_sha256=canonical_hash(proof),
                is_active=row["is_active"] != 0,
            )
    finally:
        reset_request_active_mod_id(token)
