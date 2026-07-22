"""Deterministic, read-only workflow graph validator."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

EMPLOYEE_ID = "workflow-automator"


def _failure(message: str, code: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "failed",
        "summary": message[:500],
        "error_code": code,
        "evidence": [],
        "read_only": True,
        "side_effects": [],
    }


def run(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Validate a supplied skill graph and return a topological plan only."""

    data = dict(payload or {})
    if str(data.get("action") or "validate_workflow_graph") != "validate_workflow_graph":
        return _failure("unsupported action", "unsupported_action")
    workflow = data.get("workflow")
    if not isinstance(workflow, dict):
        return _failure("workflow object is required", "missing_workflow")
    nodes = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
    edges = workflow.get("edges") if isinstance(workflow.get("edges"), list) else []
    if not nodes:
        return _failure("workflow.nodes must be non-empty", "missing_nodes")

    issues: list[dict[str, str]] = []
    node_ids: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(nodes[:200]):
        node = raw if isinstance(raw, dict) else {}
        node_id = str(node.get("id") or "").strip()[:160]
        skill_id = str(node.get("skill_id") or "").strip()[:160]
        if not node_id:
            issues.append({"code": "missing_node_id", "path": f"workflow.nodes[{index}].id"})
            continue
        if node_id in seen:
            issues.append({"code": "duplicate_node_id", "path": f"workflow.nodes[{index}].id"})
            continue
        seen.add(node_id)
        node_ids.append(node_id)
        if not skill_id:
            issues.append({"code": "missing_skill_id", "path": f"workflow.nodes[{index}].skill_id"})

    indegree = dict.fromkeys(node_ids, 0)
    graph: dict[str, list[str]] = defaultdict(list)
    for index, raw in enumerate(edges[:400]):
        edge = raw if isinstance(raw, dict) else {}
        source = str(edge.get("from") or "").strip()[:160]
        target = str(edge.get("to") or "").strip()[:160]
        if source not in indegree or target not in indegree:
            issues.append({"code": "dangling_edge", "path": f"workflow.edges[{index}]"})
            continue
        graph[source].append(target)
        indegree[target] += 1

    queue = deque(sorted(node_id for node_id, degree in indegree.items() if degree == 0))
    ordered: list[str] = []
    while queue:
        node_id = queue.popleft()
        ordered.append(node_id)
        for target in sorted(graph[node_id]):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if len(ordered) != len(node_ids):
        issues.append({"code": "cycle_detected", "path": "workflow.edges"})
    if len(node_ids) > 1 and not edges:
        issues.append({"code": "unconnected_graph", "path": "workflow.edges"})

    status = "approved" if not issues else "rejected"
    workflow_id = str(workflow.get("id") or "?").strip()[:160]
    return {
        "ok": True,
        "status": status,
        "summary": (
            f"工作流 {workflow_id} 已完成只读图契约核对："
            f"{len(node_ids)} 个节点、{len(edges[:400])} 条连线、{len(issues)} 个阻塞项；未创建画布。"
        ),
        "workflow_id": workflow_id,
        "node_count": len(node_ids),
        "edge_count": len(edges[:400]),
        "topological_order": ordered if not issues else [],
        "issues": issues,
        "ready_for_creation": not issues,
        "evidence": ["input.workflow.nodes", "input.workflow.edges"],
        "read_only": True,
        "side_effects": [],
        "meta": {"employee_id": EMPLOYEE_ID, "contract_version": "1.0"},
    }
