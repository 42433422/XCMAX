"""Bind approved strategy inputs to the existing authorized employee runtime."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from types import ModuleType
from typing import Any


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
    from modstore_server.strategic_portfolio import PortfolioError, digest

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

    if usage._SCOPE.get() is not None:
        usage.remaining_execution_seconds()
        reasoning["input"] = deepcopy(payload)


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


@contextmanager
def approved_python_module(
    employee_id: str,
    user_id: int,
    actions: dict[str, Any],
    payload: dict[str, Any],
) -> Iterator[ModuleType | None]:
    """Execute the approved archive snapshot, never a mutable extraction/pyc cache."""
    from modstore_server import strategic_portfolio_usage as usage

    if usage._SCOPE.get() is None:
        yield None
        return

    import hashlib
    import io
    import re
    import tempfile
    import zipfile
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path

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
        usage.remaining_execution_seconds()
        loader.exec_module(module)
        yield module
