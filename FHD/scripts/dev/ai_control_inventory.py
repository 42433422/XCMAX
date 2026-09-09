#!/usr/bin/env python3
"""Emit a read-only registry audit; registered actions are not E2E coverage."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


def inventory(root: Path) -> dict:
    registry = json.loads((root / "config/risk_actions.registry.json").read_text())
    dispatcher = ast.parse((root / "app/services/tools_workflow_registered.py").read_text())
    routers = set()
    for node in ast.walk(dispatcher):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "_REGISTERED_WORKFLOW_ROUTERS":
                for child in ast.walk(node.value):
                    if isinstance(child, ast.Dict):
                        routers.update(
                            key.value for key in child.keys if isinstance(key, ast.Constant)
                        )
    actions = []
    for tool_id, tool in sorted(registry.get("tools", {}).items()):
        for action, spec in sorted(tool.get("actions", {}).items()):
            actions.append(
                {
                    "tool_id": tool_id,
                    "action": action,
                    "risk": spec.get("risk", "unknown"),
                    "required_params": spec.get("required_params", []),
                    "idempotent": bool(spec.get("idempotent", False)),
                    "dispatcher_present": tool_id in routers,
                    "business_acceptance": "not_measured",
                }
            )
    return {
        "scope": "registered workflow actions and static host dispatcher; excludes unregistered UI/API/Mods",
        "product_coverage_percent": None,
        "capability_count": len(registry.get("tools", {})),
        "action_count": len(actions),
        "missing_dispatcher": sorted(
            {row["tool_id"] for row in actions if not row["dispatcher_present"]}
        ),
        "actions": actions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = inventory(Path(__file__).resolve().parents[2])
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
