# mypy: disable-error-code="union-attr"
"""Build bounded scheduled-duty inputs from reviewed repository SSOTs."""

from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path
from typing import Any

_MAX_ARCHITECTURE_FILES = 600
_MAX_ARCHITECTURE_EDGES = 500
_MAX_PACK_FILES = 500


def _reviewed_candidate(
    now: datetime, *, exclude: frozenset[str] = frozenset()
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    from modstore_server.duty_workforce_contracts import (
        load_reviewed_duty_manifest,
        workforce_contract_map,
    )

    contracts = workforce_contract_map()
    candidates = sorted(employee_id for employee_id in contracts if employee_id not in exclude)
    if not candidates:
        raise RuntimeError("reviewed duty workforce is empty")
    employee_id = candidates[now.date().toordinal() % len(candidates)]
    return employee_id, load_reviewed_duty_manifest(employee_id), contracts[employee_id]


def interview_input(now: datetime) -> tuple[dict[str, Any], tuple[str, ...], int, bool]:
    """Inspect one real reviewed role without collecting employee personal data."""

    employee_id, manifest, contract = _reviewed_candidate(
        now, exclude=frozenset({"employee-interview-assistant"})
    )
    config = manifest.get("employee_config_v2") or {}
    actions = config.get("actions") if isinstance(config.get("actions"), dict) else {}
    handlers = [str(item) for item in actions.get("handlers") or [] if str(item).strip()]
    capabilities = list(handlers)
    direct = actions.get("direct_python")
    if isinstance(direct, dict) and str(direct.get("action") or "").strip():
        capabilities.append(str(direct["action"]).strip())
    raw_dependencies = manifest.get("dependencies")
    dependencies = (
        sorted(str(item) for item in raw_dependencies if str(item).strip())
        if isinstance(raw_dependencies, dict)
        else []
    )
    role_context = {
        "mission": str(contract.get("mission") or "").strip(),
        "capabilities": sorted(set(capabilities)),
        "dependencies": dependencies,
        "risk_level": str(contract.get("risk_level") or "").strip(),
        "handlers": handlers,
    }
    return (
        {"target_employee_id": employee_id, "role_context": role_context},
        ("reviewed_duty_manifest_ssot", "duty_employee_work_contracts"),
        1,
        False,
    )


def quality_validator_input(
    now: datetime,
) -> tuple[dict[str, Any], tuple[str, ...], int, bool]:
    """Index the actual files of one reviewed employee pack for validation."""

    employee_id, manifest, _contract = _reviewed_candidate(
        now, exclude=frozenset({"quality-validator"})
    )
    from modstore_server.duty_workforce_contracts import resolve_work_contracts_path

    fhd_root = resolve_work_contracts_path().parent.parent
    pack_root = (fhd_root / "mods" / "_employees" / employee_id).resolve()
    employee_root = (fhd_root / "mods" / "_employees").resolve()
    try:
        pack_root.relative_to(employee_root)
    except ValueError as exc:
        raise RuntimeError("reviewed employee pack escaped employee root") from exc
    all_files = sorted(
        path.relative_to(pack_root).as_posix() for path in pack_root.rglob("*") if path.is_file()
    )
    files = all_files[:_MAX_PACK_FILES]
    return (
        {"pack": {"manifest": manifest, "files": files}},
        ("reviewed_duty_manifest_ssot", "employee_pack_file_index"),
        len(files),
        len(all_files) > _MAX_PACK_FILES,
    )


def _module_name(path: Path, package_root: Path) -> str:
    parts = list(path.relative_to(package_root).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(["modstore_server", *parts]) if parts else "modstore_server"


def _module_layer(path: Path, package_root: Path) -> str:
    parts = path.relative_to(package_root).parts
    first = parts[0] if len(parts) > 1 else ""
    if first == "api":
        return "interface"
    if first in {"db", "integrations", "services"}:
        return "infrastructure"
    if first == "scripts":
        return "tooling"
    return "application"


def _import_candidates(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names if alias.name.startswith("modstore_server")]
    if isinstance(node, ast.ImportFrom) and node.level == 0:
        module = str(node.module or "")
        if module == "modstore_server":
            return [f"{module}.{alias.name}" for alias in node.names]
        if module.startswith("modstore_server."):
            return [
                candidate
                for alias in node.names
                for candidate in (f"{module}.{alias.name}", module)
            ]
    return []


def _known_module(candidate: str, known: set[str]) -> str:
    current = candidate
    while current.startswith("modstore_server"):
        if current in known:
            return current
        if "." not in current:
            break
        current = current.rsplit(".", 1)[0]
    return ""


def architecture_input(
    _now: datetime,
) -> tuple[dict[str, Any], tuple[str, ...], int, bool]:
    """Extract the live backend import graph and review it against a code policy."""

    package_root = Path(__file__).resolve().parent
    all_files = sorted(package_root.rglob("*.py"))
    source_files = all_files[:_MAX_ARCHITECTURE_FILES]
    module_by_path = {path: _module_name(path, package_root) for path in source_files}
    known = set(module_by_path.values())
    modules = [
        {"name": module_by_path[path], "layer": _module_layer(path, package_root)}
        for path in source_files
    ]
    edges: set[tuple[str, str]] = set()
    for path in source_files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError):
            continue
        source = module_by_path[path]
        for node in ast.walk(tree):
            for candidate in _import_candidates(node):
                target = _known_module(candidate, known)
                if target and target != source:
                    edges.add((source, target))
    ordered_edges = sorted(edges)
    dependencies = [
        {"source": source, "target": target}
        for source, target in ordered_edges[:_MAX_ARCHITECTURE_EDGES]
    ]
    allowed_dependencies = {
        "application": ["application", "infrastructure"],
        "interface": ["interface", "application", "infrastructure"],
        "infrastructure": ["infrastructure", "application"],
        "tooling": ["tooling", "interface", "application", "infrastructure"],
    }
    return (
        {
            "architecture": {
                "modules": modules,
                "dependencies": dependencies,
                "allowed_dependencies": allowed_dependencies,
            }
        },
        ("modstore_server_python_source_tree", "architecture_dependency_policy_v1"),
        len(modules) + len(dependencies),
        (len(all_files) > _MAX_ARCHITECTURE_FILES or len(ordered_edges) > _MAX_ARCHITECTURE_EDGES),
    )


__all__ = ["architecture_input", "interview_input", "quality_validator_input"]
