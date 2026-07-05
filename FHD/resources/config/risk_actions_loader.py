"""Load risk_actions.registry.json — SSOT for tool action risk tiers."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "risk_actions.registry.json"

_REQUIRED_ACTION_CLASSES = frozenset(
    {
        "business_db.write",
        "im.send",
        "permission.grant",
        "payment.charge",
        "bulk_import",
        "delete.batch",
    }
)


def _registry_path() -> Path:
    override = (__import__("os").environ.get("XCAGI_RISK_REGISTRY_PATH") or "").strip()
    if override:
        return Path(override)
    return _REGISTRY_PATH


@lru_cache(maxsize=1)
def load_risk_registry() -> dict[str, Any]:
    path = _registry_path()
    if not path.is_file():
        raise FileNotFoundError(f"risk registry not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("risk registry root must be an object")
    action_classes = data.get("action_classes") or {}
    missing = _REQUIRED_ACTION_CLASSES - set(action_classes.keys())
    if missing:
        raise ValueError(f"risk registry missing action_classes: {sorted(missing)}")
    tools = data.get("tools")
    if not isinstance(tools, dict) or not tools:
        raise ValueError("risk registry must include non-empty tools object")
    return data


def invalidate_risk_registry_cache() -> None:
    load_risk_registry.cache_clear()


def get_workflow_tools_from_registry() -> dict[str, Any]:
    """Return the tools section (compatible with legacy get_workflow_tool_registry shape)."""
    reg = load_risk_registry()
    tools = reg.get("tools") or {}
    return json.loads(json.dumps(tools))


def _resolve_action_spec(tool_id: str, action: str) -> dict[str, Any] | None:
    tools = load_risk_registry().get("tools") or {}
    tool = tools.get(tool_id)
    if not isinstance(tool, dict):
        return None
    actions = tool.get("actions") or {}
    spec = actions.get(action)
    return spec if isinstance(spec, dict) else None


def get_action_risk(tool_id: str, action: str, *, default: str = "low") -> str:
    spec = _resolve_action_spec(tool_id, action)
    if not spec:
        return default
    action_class = str(spec.get("action_class") or "").strip()
    if action_class:
        classes = load_risk_registry().get("action_classes") or {}
        cls = classes.get(action_class)
        if isinstance(cls, dict) and cls.get("risk"):
            return str(cls["risk"])
    risk = spec.get("risk")
    return str(risk) if risk else default


def get_action_approval(tool_id: str, action: str) -> str | None:
    spec = _resolve_action_spec(tool_id, action)
    if not spec:
        return None
    action_class = str(spec.get("action_class") or "").strip()
    if action_class:
        classes = load_risk_registry().get("action_classes") or {}
        cls = classes.get(action_class)
        if isinstance(cls, dict) and cls.get("approval"):
            return str(cls["approval"])
    approval = spec.get("approval")
    return str(approval) if approval else None


def requires_write_approval(tool_id: str, action: str = "execute") -> bool:
    tid = str(tool_id or "").strip()
    if tid in _LEGACY_WRITE_TOOLS or tid in list_code_write_tools():
        return True
    spec = _resolve_action_spec(tid, action)
    if spec and spec.get("requires_write_approval") is True:
        return True
    action_class = str((spec or {}).get("action_class") or "").strip()
    if action_class:
        classes = load_risk_registry().get("action_classes") or {}
        cls = classes.get(action_class)
        if isinstance(cls, dict) and cls.get("requires_write_approval") is True:
            return True
    return False


_LEGACY_WRITE_TOOLS = frozenset(
    {
        "import_excel_to_database",
        "products_bulk_import",
    }
)


@lru_cache(maxsize=1)
def list_write_tools() -> frozenset[str]:
    tools = load_risk_registry().get("tools") or {}
    write_tools: set[str] = set(_LEGACY_WRITE_TOOLS)
    write_tools.update(list_code_write_tools())
    for tool_id, tool in tools.items():
        if not isinstance(tool, dict):
            continue
        actions = tool.get("actions") or {}
        for spec in actions.values():
            if isinstance(spec, dict) and requires_write_approval_for_spec(spec):
                write_tools.add(str(tool_id))
                break
    return frozenset(write_tools)


def requires_write_approval_for_spec(spec: dict[str, Any]) -> bool:
    if spec.get("requires_write_approval") is True:
        return True
    action_class = str(spec.get("action_class") or "").strip()
    if not action_class:
        return False
    classes = load_risk_registry().get("action_classes") or {}
    cls = classes.get(action_class)
    return isinstance(cls, dict) and cls.get("requires_write_approval") is True


def list_code_write_tools() -> frozenset[str]:
    return frozenset({"patch_file", "write_file"})


__all__ = [
    "get_action_approval",
    "get_action_risk",
    "get_workflow_tools_from_registry",
    "invalidate_risk_registry_cache",
    "list_code_write_tools",
    "list_write_tools",
    "load_risk_registry",
    "requires_write_approval",
]
