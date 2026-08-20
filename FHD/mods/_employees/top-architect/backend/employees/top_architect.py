"""Deterministic, read-only architecture dependency boundary reviewer."""

from __future__ import annotations

from typing import Any


def run(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    architecture = payload.get("architecture")
    if not isinstance(architecture, dict):
        return _failed("architecture object is required", "missing_architecture")
    modules = architecture.get("modules")
    dependencies = architecture.get("dependencies")
    allowed = architecture.get("allowed_dependencies")
    if (
        not isinstance(modules, list)
        or not isinstance(dependencies, list)
        or not isinstance(allowed, dict)
    ):
        return _failed(
            "modules, dependencies and allowed_dependencies are required",
            "invalid_architecture",
        )

    module_layers = {
        str(item.get("name") or "").strip(): str(item.get("layer") or "").strip()
        for item in modules
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }
    violations: list[dict[str, str]] = []
    for raw in dependencies:
        edge = raw if isinstance(raw, dict) else {}
        source = str(edge.get("source") or "").strip()
        target = str(edge.get("target") or "").strip()
        source_layer = module_layers.get(source, "")
        target_layer = module_layers.get(target, "")
        allowed_targets = (
            allowed.get(source_layer) if isinstance(allowed.get(source_layer), list) else []
        )
        if not source_layer or not target_layer:
            violations.append({"source": source, "target": target, "reason": "module_unknown"})
        elif target_layer not in {str(item) for item in allowed_targets}:
            violations.append(
                {
                    "source": source,
                    "target": target,
                    "reason": f"forbidden_layer_dependency:{source_layer}->{target_layer}",
                }
            )

    approved = bool(module_layers) and not violations
    priorities = [
        {"priority": index + 1, "decision": "invert_or_remove_dependency", **item}
        for index, item in enumerate(violations)
    ]
    return {
        "ok": True,
        "status": "approved" if approved else "rejected",
        "summary": (
            f"架构边界已确定性只读审查：{len(module_layers)} 个模块、{len(dependencies)} 条依赖，"
            f"发现 {len(violations)} 条违规依赖；未修改架构。"
        ),
        "violations": violations,
        "priorities": priorities,
        "evidence": [
            "architecture.modules",
            "architecture.dependencies",
            "architecture.allowed_dependencies",
        ],
        "read_only": True,
        "side_effects": [],
    }


def _failed(message: str, code: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "failed",
        "summary": message,
        "error_code": code,
        "evidence": [],
        "read_only": True,
        "side_effects": [],
    }
