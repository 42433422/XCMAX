"""Deterministic employee assignment planner with dependency validation."""

from __future__ import annotations

from typing import Any


def _has_cycle(graph: dict[str, list[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(dependency) for dependency in graph.get(node, [])):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


def run(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    requirements = payload.get("requirements")
    employees = payload.get("employees")
    if not isinstance(requirements, list) or not isinstance(employees, list):
        return _failed("requirements and employees must be arrays")

    roster: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for index, employee in enumerate(employees):
        if not isinstance(employee, dict) or not str(employee.get("id") or "").strip():
            blockers.append({"kind": "invalid_employee", "index": index})
            continue
        roster.append(
            {
                "id": str(employee["id"]).strip(),
                "capabilities": {
                    str(value).strip()
                    for value in employee.get("capabilities") or []
                    if str(value).strip()
                },
                "available": employee.get("available") is True,
            }
        )

    graph: dict[str, list[str]] = {}
    normalized: list[dict[str, Any]] = []
    for index, requirement in enumerate(requirements):
        if not isinstance(requirement, dict) or not str(requirement.get("id") or "").strip():
            blockers.append({"kind": "invalid_requirement", "index": index})
            continue
        requirement_id = str(requirement["id"]).strip()
        capabilities = sorted(
            {
                str(value).strip()
                for value in requirement.get("capabilities") or []
                if str(value).strip()
            }
        )
        dependencies = sorted(
            {
                str(value).strip()
                for value in requirement.get("depends_on") or []
                if str(value).strip()
            }
        )
        graph[requirement_id] = dependencies
        normalized.append(
            {
                "id": requirement_id,
                "capabilities": capabilities,
                "depends_on": dependencies,
            }
        )

    known_requirements = set(graph)
    for requirement in normalized:
        missing_dependencies = [
            value for value in requirement["depends_on"] if value not in known_requirements
        ]
        if missing_dependencies:
            blockers.append(
                {
                    "kind": "missing_dependencies",
                    "requirement_id": requirement["id"],
                    "dependencies": missing_dependencies,
                }
            )
    if _has_cycle(graph):
        blockers.append({"kind": "dependency_cycle"})

    plan: list[dict[str, Any]] = []
    for requirement in normalized:
        required = set(requirement["capabilities"])
        candidates = sorted(
            employee["id"]
            for employee in roster
            if employee["available"] and required.issubset(employee["capabilities"])
        )
        if not candidates:
            blockers.append(
                {
                    "kind": "capability_unassigned",
                    "requirement_id": requirement["id"],
                    "capabilities": requirement["capabilities"],
                }
            )
            continue
        plan.append(
            {
                "requirement_id": requirement["id"],
                "employee_id": candidates[0],
                "depends_on": requirement["depends_on"],
            }
        )

    approved = not blockers and len(plan) == len(normalized)
    return {
        "ok": True,
        "status": "approved" if approved else "rejected",
        "summary": (
            f"已只读规划 {len(normalized)} 项能力需求，形成 {len(plan)} 项分工；"
            f"发现 {len(blockers)} 个依赖或能力阻塞。"
        ),
        "plan": plan,
        "blockers": blockers,
        "evidence": [
            "input.requirements",
            "input.employees",
            "dependency DAG validation",
        ],
        "read_only": True,
        "side_effects": [],
    }


def _failed(message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "failed",
        "summary": message,
        "plan": [],
        "blockers": [{"kind": "invalid_input"}],
        "evidence": [],
        "read_only": True,
        "side_effects": [],
    }
