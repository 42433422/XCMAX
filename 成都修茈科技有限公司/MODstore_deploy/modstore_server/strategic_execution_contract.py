"""Bind approved strategy inputs to the existing authorized employee runtime."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any

_WORKFLOW_SCOPE: ContextVar[dict[str, Any] | None] = ContextVar(
    "approved_workflow_file_execution", default=None
)


@contextmanager
def workflow_execution_scope(contract: dict[str, Any]) -> Iterator[None]:
    """Restore a server-recorded workflow contract without creating a strategy lease."""
    from modstore_server import strategic_portfolio_usage as usage
    from modstore_server.workflow_customer_delivery import require_running_contract

    if usage._SCOPE.get() is not None or _WORKFLOW_SCOPE.get() is not None:
        raise ValueError("workflow file execution cannot replace another execution scope")
    require_running_contract(contract)
    token = _WORKFLOW_SCOPE.set(deepcopy(contract))
    try:
        yield
    finally:
        _WORKFLOW_SCOPE.reset(token)


def _workflow_contract() -> dict[str, Any] | None:
    contract = _WORKFLOW_SCOPE.get()
    if contract is not None:
        from modstore_server.workflow_customer_delivery import require_running_contract

        require_running_contract(contract)
    return contract


def validate_input(value: dict[str, Any]) -> dict[str, Any]:
    from modstore_server.strategic_portfolio import PortfolioError, _json

    reserved = {
        "employee_id",
        "user_id",
        "owner_user_id",
        "idempotency_key",
        "deadline_epoch",
        "handler",
        "handler_mode",
        "delegate",
        "multi_step",
        "fallback_cursor",
        "burn_in",
        "work_contract",
        "bench_llm_override",
        "customer_goal_ids",
        "customer_goal_bindings",
        "provider",
        "model",
        "api_key",
        "authorization",
        "token",
        "password",
    }
    if not isinstance(value, dict) or any(
        not isinstance(key, str)
        or key in reserved
        or key.startswith(("_", "strategic_", "suppress_", "allow_"))
        for key in value
    ):
        raise PortfolioError("strategy input contains reserved execution control fields")
    if len(_json(value).encode("utf-8")) > 64_000:
        raise PortfolioError("strategy input exceeds 64000 bytes")
    return value


def _pack_identity(pack: dict[str, Any]) -> dict[str, str]:
    from modstore_server.catalog_store import catalog_archive_available
    from modstore_server.strategic_portfolio import PortfolioError, digest

    archive_sha = str(pack.get("sha256") or "").lower()
    if pack.get("stored_filename") and not catalog_archive_available(
        pack["stored_filename"], archive_sha
    ):
        raise PortfolioError("approved employee archive integrity could not be verified")

    return {
        "pack_id": str(pack["pack_id"]),
        "version": str(pack["version"]),
        "manifest_sha256": digest(pack.get("manifest") or {}),
        "archive_sha256": archive_sha,
    }


def _workspace_file(path: str, workspace: str, user_id: int, *, exists: bool) -> Path:
    from modstore_server.integrations.vibe_adapter import VibePathError, ensure_within_workspace
    from modstore_server.strategic_portfolio import PortfolioError

    try:
        candidate = Path(path.strip())
        if candidate.parts and candidate.parts[0].startswith("~"):
            raise ValueError("home aliases are not workspace-relative paths")
        root = ensure_within_workspace(workspace, user_id=user_id)
        if not root.is_dir():
            raise PortfolioError("strategy workspace is not a directory")
        target = ensure_within_workspace(candidate, user_id=user_id, within=root, must_exist=exists)
        if exists and not target.is_file():
            raise PortfolioError("strategy file is not a regular file")
    except (VibePathError, ValueError) as exc:
        raise PortfolioError(
            "strategy file is outside the selected workspace or unavailable"
        ) from exc
    return target


def _verify_file_paths(payload: dict[str, Any], config: dict[str, Any], user_id: int) -> None:
    from modstore_server.employee_path_guard import check_path_guard
    from modstore_server.strategic_portfolio import PortfolioError

    workspace = payload["project_root"]
    actions = config.get("actions") or {}
    nested = actions.get("actions")
    actions = nested if isinstance(nested, dict) else actions
    direct = actions.get("direct_python") or {}
    output = payload.get("output_relpath") or direct.get("default_output_relpath")
    source = payload.get("file_path")
    if output and "direct_python" in actions.get("handlers", []):
        source = source or payload.get("path") or payload.get("excel_path")
    if source:
        _workspace_file(str(source), workspace, user_id, exists=True)
    if output and "direct_python" in actions.get("handlers", []):
        target = _workspace_file(str(output), workspace, user_id, exists=False)
        path = target.relative_to(Path(workspace)).as_posix()
        guard = check_path_guard(
            config=config,
            result={"outputs": [{"handler": "direct_python", "files_changed": [path]}]},
            employee_id="",
        )
        if guard.get("ok") is not True or guard.get("checked") is not True:
            raise PortfolioError("strategy output is outside the approved employee scope")


def _verify_file_support(
    module: ModuleType, payload: dict[str, Any], config: dict[str, Any], user_id: int
) -> None:
    support = getattr(module, "_file_support", None)
    if support is None:
        return
    from app.mod_sdk.file_employee_support import FileEmployeeSupport

    if not isinstance(support, FileEmployeeSupport):
        return
    actions = config.get("actions") or {}
    nested = actions.get("actions")
    actions = nested if isinstance(nested, dict) else actions
    direct = actions.get("direct_python") or {}
    effective = deepcopy(payload)
    for field in ("output_relpath", "template_relpath"):
        effective[field] = (
            effective.get(field)
            or direct.get(f"default_{field}")
            or support.rule_spec.get(f"default_{field}")
        )
    effective["output_relpath"] = effective["output_relpath"] or "outputs/employee_output.xlsx"
    _verify_file_paths(effective, config, user_id)
    template = support._resolve_template(effective, {"workspace_root": payload["project_root"]})
    if template is not None:
        # Use the original resolver's priority. Bundled templates are read from
        # the immutable archive snapshot, while workspace templates stay tenant-bound.
        snapshot = Path(str(module.__file__)).resolve().parents[2]
        if not template.resolve().is_relative_to(snapshot):
            _workspace_file(str(template), payload["project_root"], user_id, exists=True)


def bind_file_receipts(
    result: dict[str, Any], payload: dict[str, Any], config: dict[str, Any], user_id: int
) -> None:
    """Adapt legacy file employees only after checking real, authorized artifact bytes."""
    from modstore_server import strategic_portfolio_usage as usage
    from modstore_server.employee_change_request_verification import _workspace_fd
    from modstore_server.employee_path_guard import check_path_guard
    from modstore_server.strategic_execution_receipts import _control
    from modstore_server.strategic_portfolio import PortfolioError

    if usage._SCOPE.get() is None and _workflow_contract() is None:
        return
    workspace = payload["project_root"]
    for handler in result.get("outputs") or []:
        output = handler.get("output") if isinstance(handler, dict) else None
        if not isinstance(output, dict) or handler.get("handler") != "direct_python":
            continue
        paths = [
            str(item["output_path"])
            for item in [output, *(output.get("items") or [])]
            if isinstance(item, dict) and item.get("output_path")
        ]
        if not paths:
            continue
        try:
            if (
                handler.get("ok") is not True
                or output.get("ok", output.get("success")) is not True
                or _control(output, "file_employee") is not None
                or len(str(output.get("summary") or "").strip()) < 10
            ):
                raise PortfolioError("file employee did not report a completed result with summary")
            verified_paths = {
                path: _workspace_file(path, workspace, user_id, exists=True)
                for path in dict.fromkeys(paths)
            }
            files = list(dict.fromkeys(verified_paths.values()))
            relative = [path.relative_to(Path(workspace)).as_posix() for path in files]
            checked = {"handler": "direct_python", "files_changed": relative}
            guard = check_path_guard(config=config, result={"outputs": [checked]}, employee_id="")
            if guard.get("ok") is not True or guard.get("checked") is not True:
                raise PortfolioError("file artifact is outside the approved employee scope")
            artifacts = []
            for rel in relative:
                # Keep every directory and the file anchored while hashing.
                # Reusing a validated pathname would follow a link substituted
                # after _workspace_file, even when both stat calls agree.
                with _workspace_fd(workspace, rel) as fd:
                    before = os.fstat(fd)
                    with os.fdopen(os.dup(fd), "rb") as source:
                        sha = hashlib.file_digest(source, "sha256").hexdigest()
                    after = os.fstat(fd)
                    with _workspace_fd(workspace, rel) as current_fd:
                        current = os.fstat(current_fd)
                # Hashing may update atime; retain the archive check's content
                # identity fields plus ownership/mode, never access time.
                if any(
                    len({getattr(item, field) for item in (before, after, current)}) != 1
                    for field in (
                        "st_dev",
                        "st_ino",
                        "st_mode",
                        "st_nlink",
                        "st_uid",
                        "st_gid",
                        "st_size",
                        "st_mtime_ns",
                        "st_ctime_ns",
                    )
                ):
                    raise PortfolioError("file artifact changed while verifying its bytes")
                artifacts.append(
                    {
                        "artifact_id": rel,
                        "artifact_sha256": sha,
                        "size_bytes": before.st_size,
                        "path": rel,
                    }
                )
            handler["files_changed"] = relative
            output.update(status="completed", files_changed=relative, artifacts=artifacts)
        except (OSError, ValueError) as exc:
            handler.update(ok=False, error=f"file artifact verification failed: {exc}")


def freeze_execution(owner_user_id: int, opportunity: dict[str, Any]) -> dict[str, Any]:
    """Resolve the existing tenant workspace and employee before presenting approval."""
    from modstore_server.db.db_base import get_session_factory
    from modstore_server.employee_runtime import (
        load_employee_pack_resolved,
        parse_employee_config_v2,
    )
    from modstore_server.employee_runtime_policy import apply_policy_to_config
    from modstore_server.integrations.vibe_adapter import (
        VibePathError,
        _tenant_workspace_root,
        ensure_within_workspace,
    )
    from modstore_server.strategic_customer_outcomes import validate_customer_goal_bindings
    from modstore_server.strategic_portfolio import PortfolioError, digest

    validate_customer_goal_bindings(opportunity)
    employee_id = opportunity["employee_id"]
    payload = deepcopy(validate_input(opportunity.get("input_data") or {}))
    root = (
        payload.get("project_root")
        or payload.get("workspace_root")
        or _tenant_workspace_root(owner_user_id)
    )
    try:
        workspace = str(ensure_within_workspace(root, user_id=owner_user_id))
        for key in ("project_root", "workspace_root"):
            if (
                payload.get(key)
                and str(ensure_within_workspace(payload[key], user_id=owner_user_id)) != workspace
            ):
                raise PortfolioError("strategy workspace inputs disagree")
    except VibePathError as exc:
        raise PortfolioError(
            "strategy workspace is outside the tenant boundary or unavailable"
        ) from exc
    payload.update(project_root=workspace, workspace_root=workspace)
    try:
        with get_session_factory()() as session:
            pack = load_employee_pack_resolved(
                session, employee_id, user_id=owner_user_id, execute=True
            )
    except (PermissionError, ValueError) as exc:
        raise PortfolioError("strategy employee package is unavailable or unauthorized") from exc
    config, _ = apply_policy_to_config(
        employee_id, deepcopy(parse_employee_config_v2(pack.get("manifest") or {}))
    )
    policy = config.get("workspace_policy")
    policy = policy if isinstance(policy, dict) else {}
    if not (policy.get("scope_globs") or policy.get("forbidden_globs")):
        raise PortfolioError(f"employee {employee_id} requires a configured workspace policy")
    actions = config.get("actions") or {}
    nested_actions = actions.get("actions")
    if isinstance(nested_actions, dict):
        actions = nested_actions
    if "direct_python" in actions.get("handlers", []) and not pack.get("stored_filename"):
        raise PortfolioError("strategic Python handlers require an immutable catalog archive")
    _verify_file_paths(payload, config, owner_user_id)
    binding = {
        **_pack_identity(pack),
        "config_sha256": digest(config),
        "input_sha256": digest(payload),
    }
    prior = opportunity.get("execution_binding")
    if prior and prior != binding:
        raise PortfolioError("employee execution contract changed; rediscover before approval")
    return {**opportunity, "input_data": payload, "execution_binding": binding}


def execution_payload(task: dict[str, Any]) -> dict[str, Any]:
    from modstore_server.strategic_portfolio import _date, digest

    return {
        **deepcopy(task.get("input_data") or {}),
        "strategic_decision_id": task["decision_id"],
        "strategic_opportunity_id": task["opportunity_id"],
        "strategic_source_refs": list(task["source_refs"]),
        "customer_goal_ids": list(task["customer_goal_ids"]),
        "customer_goal_bindings": deepcopy(task.get("customer_goal_bindings") or []),
        "idempotency_key": "portfolio-"
        + digest([task["decision_id"], task["opportunity_id"]])[:32],
        "deadline_epoch": _date(task["deadline"]).timestamp(),
        "allow_high_risk_real_run": False,
        "suppress_handoff": True,
        "suppress_employee_im": True,
        "suppress_lifecycle_events": True,
    }


def bind_reasoning_input(reasoning: dict[str, Any], payload: dict[str, Any]) -> None:
    """A model may plan work, but cannot replace approved business identifiers or paths."""
    from modstore_server import strategic_portfolio_usage as usage
    from modstore_server.strategic_portfolio import PortfolioError, portfolio_status

    scope = usage._SCOPE.get()
    workflow = _workflow_contract()
    if workflow is not None:
        approved = deepcopy(workflow["input_data"])
        if any(key not in payload or payload[key] != value for key, value in approved.items()):
            raise PortfolioError("perception changed approved workflow business input")
        reasoning["input"] = approved
        return
    if scope is not None:
        usage.remaining_execution_seconds()
        decision_id, opportunity_id, _lease = scope
        status = portfolio_status(decision_id)
        item = next(
            row for row in status["opportunities"] if row["opportunity_id"] == opportunity_id
        )
        approved = execution_payload(
            {
                **item,
                "decision_id": decision_id,
                "deadline": status["tasks"][opportunity_id]["deadline"],
            }
        )
        if any(key not in payload or payload[key] != value for key, value in approved.items()):
            raise PortfolioError("perception changed approved strategy business input")
        # Perception adds live _workspace_signals/_recent_runs context in-place.
        # Those observations remain cognition context, not executable business input.
        reasoning["input"] = approved


def verify_execution_binding(
    employee_id: str,
    *,
    user_id: int | None = None,
    pack: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> None:
    """Check the actual pack and effective config before perception, models or handlers."""
    from modstore_server import strategic_portfolio_usage as usage
    from modstore_server.integrations.vibe_adapter import ensure_within_workspace
    from modstore_server.strategic_portfolio import (
        PortfolioError,
        digest,
        portfolio_status,
    )

    scope = usage._SCOPE.get()
    workflow = _workflow_contract()
    if workflow is not None:
        binding = workflow["execution_binding"]
        if employee_id != workflow["employee_id"] or (
            user_id is not None and user_id != workflow["user_id"]
        ):
            raise PortfolioError("workflow executor owner or employee changed")
        if pack is not None and any(
            binding.get(key) != value for key, value in _pack_identity(pack).items()
        ):
            raise PortfolioError("approved employee package changed")
        if config is not None and digest(config) != binding["config_sha256"]:
            raise PortfolioError("approved employee runtime configuration changed")
        if payload is not None:
            if payload != workflow["input_data"] or digest(payload) != binding["input_sha256"]:
                raise PortfolioError("approved workflow business input changed")
            _verify_file_paths(payload, config or {}, workflow["user_id"])
        return
    if scope is None:
        return
    usage.remaining_execution_seconds()
    decision_id, opportunity_id, _lease = scope
    status = portfolio_status(decision_id)
    item = next(row for row in status["opportunities"] if row["opportunity_id"] == opportunity_id)
    binding = item.get("execution_binding") or {}
    if not binding or item["employee_id"] != employee_id:
        raise PortfolioError("strategy executor is not bound to the approved employee")
    if user_id is not None and user_id != status["owner_user_id"]:
        raise PortfolioError("strategy executor owner changed")
    if pack is not None and any(
        binding.get(key) != value for key, value in _pack_identity(pack).items()
    ):
        raise PortfolioError("approved employee package changed")
    if config is not None and digest(config) != binding.get("config_sha256"):
        raise PortfolioError("approved employee runtime configuration changed")
    if payload is not None:
        task = {
            **item,
            "decision_id": decision_id,
            "deadline": status["tasks"][opportunity_id]["deadline"],
        }
        if payload != execution_payload(task) or digest(item["input_data"]) != binding.get(
            "input_sha256"
        ):
            raise PortfolioError("approved strategy business input changed")
        resolved = ensure_within_workspace(
            item["input_data"]["project_root"], user_id=status["owner_user_id"]
        )
        if str(resolved) != item["input_data"]["project_root"]:
            raise PortfolioError("approved strategy workspace changed")
        _verify_file_paths(payload, config or {}, status["owner_user_id"])


@contextmanager
def approved_python_module(
    employee_id: str,
    user_id: int,
    actions: dict[str, Any],
    payload: dict[str, Any],
) -> Iterator[ModuleType | None]:
    """Execute the approved archive snapshot, never a mutable extraction/pyc cache."""
    from modstore_server import strategic_portfolio_usage as usage

    if usage._SCOPE.get() is None and _workflow_contract() is None:
        yield None
        return

    import hashlib
    import io
    import re
    import tempfile
    import zipfile
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_file_location

    from modman.archive_import import MAX_FILES, MAX_UNPACKED_BYTES
    from modstore_server import employee_executor as executor
    from modstore_server.catalog_archive_integrity import archive_path
    from modstore_server.catalog_store import files_dir
    from modstore_server.employee_runtime import parse_employee_config_v2
    from modstore_server.employee_runtime_policy import apply_policy_to_config
    from modstore_server.strategic_portfolio import PortfolioError

    # Cognition may have taken minutes. Resolve permission and the actual package
    # again at the code-loading boundary, with the approved owner and execute flag.
    with executor.get_session_factory()() as session:
        pack = executor.load_employee_pack_resolved(
            session, employee_id, user_id=user_id, execute=True
        )
    manifest = pack.get("manifest") or {}
    config, _ = apply_policy_to_config(employee_id, deepcopy(parse_employee_config_v2(manifest)))
    verify_execution_binding(
        employee_id, user_id=user_id, pack=pack, payload=payload, config=config
    )
    expected_actions = deepcopy(executor._get_section(config, "actions"))
    if employee_id == "taiyangniao-attendance-employee":
        expected_actions["direct_python"] = dict(expected_actions.get("direct_python") or {})
        expected_actions["direct_python"].pop("default_backend_path", None)
        expected_actions["handlers"] = ["direct_python"]
    if actions != expected_actions:
        raise PortfolioError("approved Python handler configuration changed")

    path = archive_path(pack.get("stored_filename"), pack.get("sha256"), (files_dir(),))
    if path is None:
        raise PortfolioError("approved employee archive integrity could not be verified")
    # Hash the same bounded bytes that will be extracted and compiled. A prior
    # cached path/hash check alone cannot protect a later read or cached .pyc.
    with path.open("rb") as handle:
        raw = handle.read(MAX_UNPACKED_BYTES + 1)
    if len(raw) > MAX_UNPACKED_BYTES or hashlib.sha256(raw).hexdigest() != pack["sha256"]:
        raise PortfolioError("approved employee archive bytes changed before execution")
    pack_id = str(manifest.get("id") or employee_id)
    module_name = str(
        (actions.get("direct_python") or {}).get("module") or "taiyangniao_attendance"
    )
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", pack_id) or not module_name.isidentifier():
        raise PortfolioError("approved Python package entry is invalid")
    member = f"{pack_id}/backend/employees/{module_name}.py"
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        if (
            len(names) != len(set(names))
            or len(names) > MAX_FILES
            or sum(info.file_size for info in archive.infolist()) > MAX_UNPACKED_BYTES
            or member not in names
        ):
            raise PortfolioError("approved Python package archive is invalid")
        source = archive.read(member)

    with tempfile.TemporaryDirectory(prefix="modstore-approved-employee-") as directory:
        root = executor._employee_pack_extract_root(
            employee_id,
            manifest,
            pack=pack,
            archive_bytes=raw,
            target_root=Path(directory) / pack_id,
        )
        module_path = str(root / "backend" / "employees" / f"{module_name}.py")

        class SnapshotLoader(SourceFileLoader):
            def get_code(self, fullname: str):
                return self.source_to_code(source, module_path)

        name = f"_modstore_approved_{employee_id.replace('-', '_')}_{module_name}"
        loader = SnapshotLoader(name, module_path)
        spec = spec_from_file_location(name, module_path, loader=loader)
        if spec is None:
            raise PortfolioError("approved Python module could not be loaded")
        module = module_from_spec(spec)
        if usage._SCOPE.get() is not None:
            usage.remaining_execution_seconds()
        else:
            _workflow_contract()
        loader.exec_module(module)
        _verify_file_support(module, payload, config, user_id)
        yield module
