#!/usr/bin/env python3
"""One-shot / maintenance: export tools_execution registry dict to risk_actions.registry.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FHD_ROOT))

import importlib.util

_registry_path = FHD_ROOT / "app" / "services" / "tools_execution" / "registry.py"
_spec = importlib.util.spec_from_file_location("_risk_export_registry", _registry_path)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
# After SSOT migration, re-apply action_class bindings onto existing JSON.
from resources.config.risk_actions_loader import (  # noqa: E402
    get_workflow_tools_from_registry,
)

get_workflow_tool_registry = get_workflow_tools_from_registry

ACTION_CLASSES = {
    "business_db.write": {
        "risk": "medium",
        "approval": "interactive",
        "requires_write_approval": True,
    },
    "im.send": {"risk": "medium", "approval": "always"},
    "permission.grant": {"risk": "high", "approval": "always"},
    "payment.charge": {"risk": "high", "approval": "always"},
    "bulk_import": {
        "risk": "high",
        "approval": "interactive",
        "requires_write_approval": True,
    },
    "delete.batch": {"risk": "high", "approval": "always"},
}

# tool_id -> action -> action_class
ACTION_CLASS_BINDINGS: dict[str, dict[str, str]] = {
    "business_db": {"write": "business_db.write"},
    "products": {
        "create": "business_db.write",
        "update": "business_db.write",
        "delete": "delete.batch",
        "batch_create": "bulk_import",
        "batch_delete": "delete.batch",
    },
    "customers": {
        "create": "business_db.write",
        "update": "business_db.write",
        "delete": "delete.batch",
        "batch_delete": "delete.batch",
        "ensure_exists": "business_db.write",
    },
    "import_excel_to_database": {"import": "bulk_import", "execute": "bulk_import"},
    "products_bulk_import": {"import": "bulk_import", "execute": "bulk_import"},
    "excel_import": {"execute_import": "bulk_import", "import_records": "bulk_import"},
    "unit_products_import": {"execute_import": "bulk_import"},
    "patch_file": {"execute": "business_db.write"},
    "write_file": {"execute": "business_db.write"},
    "im": {"send": "im.send", "send_message": "im.send"},
    "permission": {"grant": "permission.grant", "revoke": "permission.grant"},
    "payment": {"charge": "payment.charge", "deduct": "payment.charge"},
}


def _apply_action_classes(tools: dict) -> dict:
    out = json.loads(json.dumps(tools))
    for tool_id, bindings in ACTION_CLASS_BINDINGS.items():
        tool = out.get(tool_id)
        if not isinstance(tool, dict):
            continue
        actions = tool.get("actions") or {}
        for action, action_class in bindings.items():
            spec = actions.get(action)
            if isinstance(spec, dict):
                spec["action_class"] = action_class
    return out


def main() -> int:
    out_path = FHD_ROOT / "config" / "risk_actions.registry.json"
    tools = get_workflow_tool_registry()
    # Keep the autonomy policy envelope (schema v2, autonomous_actions and policy knobs)
    # intact.  This exporter owns only the action classes and workflow-tool projection.
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    payload["action_classes"] = ACTION_CLASSES
    payload["tools"] = _apply_action_classes(tools)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {out_path} ({len(tools)} tools)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
