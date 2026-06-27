from __future__ import annotations

from pathlib import Path
from typing import Any


SOURCE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".md", ".json", ".yml", ".yaml", ".toml"}
SKIP_PARTS = {".git", ".retort", "__pycache__", "node_modules", ".venv", ".pytest_cache", ".ruff_cache", "dist", "build"}
PIPELINE_STAGES = (
    "materialize_external_snapshot",
    "group_related_files",
    "map_diff_hunk_context",
    "extract_review_signals",
    "compare_component_gaps",
    "rank_absorption_tasks",
    "verify_feedback_loop",
)
COMPONENT_MARKERS = {
    "review_pipeline": ("review", "reflection", "localization", "diff hunk", "patch set", "code review"),
    "file_grouping": ("file group", "group files", "changed files", "related files", "pathspec"),
    "diff_hunk_review": ("diff hunk", "patch set", "line comment", "comment range", "changed lines"),
    "benchmark_eval": ("benchmark", "precision", "recall", "evaluation", "eval"),
    "provider_surface": ("provider", "model", "openai", "anthropic", "ollama", "multi-provider"),
    "plugin_surface": ("plugin", "extension", "github action", "codex", "vsix"),
    "safety_policy": ("license", "security", "policy", "permission", "sandbox"),
    "workflow_ci": ("workflow", "pipeline", "ci", "gate", "test"),
    "codebase_graph": ("code graph", "codebase graph", "dependency graph", "call graph", "symbol graph", "imports", "hotspot"),
    "static_analysis": ("static analysis", "security scan", "scanner", "taint", "rule engine", "ast rule", "vulnerability"),
    "context_packaging": ("repo map", "repository context", "codebase context", "context pack", "prompt context", "code digest"),
    "semantic_index": ("semantic index", "symbol index", "language server", "definition", "reference", "xref", "scip", "lsif"),
}
DEPTH_FOCUS_COMPONENTS = (
    "review_pipeline",
    "diff_hunk_review",
    "file_grouping",
    "benchmark_eval",
    "safety_policy",
    "workflow_ci",
    "codebase_graph",
    "static_analysis",
    "context_packaging",
    "semantic_index",
)
BREADTH_ONLY_COMPONENTS = {"provider_surface", "plugin_surface"}
MARKETPLACE_CANDIDATES_ENABLED = False
DIMENSION_COMPONENTS = {
    "comparative_analysis_depth": {"review_pipeline", "diff_hunk_review", "file_grouping", "benchmark_eval"},
    "external_ingestion": {"file_grouping", "review_pipeline"},
    "feedback_loop_closure": {"benchmark_eval", "workflow_ci"},
    "operational_readiness": {"workflow_ci", "safety_policy"},
    "product_operability": {"review_pipeline"},
    "architecture_depth": {"codebase_graph", "workflow_ci", "safety_policy", "static_analysis", "context_packaging", "semantic_index"},
}


def build_absorption_review_report(own_project: str | Path, external_project: str | Path, tasks: list[dict[str, Any]]) -> dict[str, Any]:
    own = Path(own_project)
    external = Path(external_project)
    own_groups = group_review_files(own)
    external_groups = group_review_files(external)
    component_gaps = compare_component_gaps(own_groups, external_groups)
    depth_workflow = build_depth_absorption_workflow(own_groups, external_groups, tasks)
    return {
        "pipeline_stages": list(PIPELINE_STAGES),
        "own_file_groups": own_groups,
        "external_file_groups": external_groups,
        "component_gaps": component_gaps,
        "prioritized_absorptions": _prioritize_absorptions(component_gaps, tasks),
        "depth_absorption_workflow": depth_workflow,
        "benchmark": _benchmark_metrics(component_gaps, tasks),
    }


def group_review_files(root: str | Path) -> dict[str, dict[str, Any]]:
    base = Path(root)
    groups = {name: {"files": [], "marker_hits": 0} for name in COMPONENT_MARKERS}
    for path in _project_files(base):
        text = _read(path).lower()
        if not text:
            continue
        rel = str(path.relative_to(base))
        for component, markers in COMPONENT_MARKERS.items():
            hits = sum(text.count(marker) for marker in markers)
            if hits <= 0:
                continue
            group = groups[component]
            group["marker_hits"] = int(group["marker_hits"]) + hits
            if len(group["files"]) < 12:
                group["files"].append(rel)
    return {name: value for name, value in groups.items() if value["files"] or value["marker_hits"]}


def compare_component_gaps(own_groups: dict[str, dict[str, Any]], external_groups: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for component, external in external_groups.items():
        own = own_groups.get(component, {"files": [], "marker_hits": 0})
        file_gap = len(external.get("files") or []) - len(own.get("files") or [])
        marker_gap = int(external.get("marker_hits") or 0) - int(own.get("marker_hits") or 0)
        if file_gap <= 0 and marker_gap <= 0:
            continue
        gaps.append(
            {
                "component": component,
                "external_files": len(external.get("files") or []),
                "own_files": len(own.get("files") or []),
                "file_gap": file_gap,
                "marker_gap": marker_gap,
                "representative_external_files": list((external.get("files") or [])[:5]),
            }
        )
    return sorted(gaps, key=lambda item: (int(item["marker_gap"]), int(item["file_gap"])), reverse=True)


def build_depth_absorption_workflow(own_groups: dict[str, dict[str, Any]], external_groups: dict[str, dict[str, Any]], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep absorption focused on similar-function depth, not project breadth."""
    task_text = " ".join(str(task.get("title", "")) + " " + str(task.get("dimension", "")) + " " + str(task.get("why", "")) for task in tasks).lower()
    requested_components = _requested_components(tasks)
    focused: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for component, external in external_groups.items():
        external_hits = int(external.get("marker_hits") or 0)
        external_files = list(external.get("files") or [])
        own = own_groups.get(component, {"files": [], "marker_hits": 0})
        own_hits = int(own.get("marker_hits") or 0)
        own_files = list(own.get("files") or [])
        if component in BREADTH_ONLY_COMPONENTS and component not in requested_components:
            rejected.append(_rejected_component(component, external, "breadth_only_for_current_phase"))
            continue
        if component not in DEPTH_FOCUS_COMPONENTS:
            rejected.append(_rejected_component(component, external, "not_same_direction_depth"))
            continue
        if not (own_files or own_hits or component in requested_components or component in task_text):
            rejected.append(_rejected_component(component, external, "no_internal_overlap_yet"))
            continue
        depth_gap = max(0, external_hits - own_hits)
        similarity = _similarity_score(component, own_hits, external_hits, own_files, external_files, requested_components)
        focused.append(
            {
                "component": component,
                "priority": "P0" if component in requested_components or depth_gap >= 20 else "P1",
                "own_marker_hits": own_hits,
                "external_marker_hits": external_hits,
                "depth_gap": depth_gap,
                "similarity_score": similarity,
                "source_files": external_files[:5],
                "absorption_goal": _absorption_goal(component),
                "acceptance": _acceptance_for_component(component),
                "evidence_required": _evidence_for_component(component),
                "employee_task": _employee_task_for_component(component),
            }
        )
    focused = sorted(focused, key=lambda item: (item["priority"] == "P0", int(item["similarity_score"]), int(item["depth_gap"])), reverse=True)
    employee_tasks = [item["employee_task"] for item in focused]
    breadth_rejections = [item for item in rejected if item["reason"] == "breadth_only_for_current_phase"]
    marketplace_candidates = [_marketplace_candidate(item) for item in breadth_rejections] if MARKETPLACE_CANDIDATES_ENABLED else []
    deferred_breadth = [_deferred_breadth_component(item) for item in breadth_rejections]
    quality_gate = {
        "minimum_focused_component_count": 3,
        "focused_component_count": len(focused),
        "rejected_breadth_component_count": len(breadth_rejections),
        "kept_breadth_component_count": len([item for item in focused if item["component"] in BREADTH_ONLY_COMPONENTS]),
        "marketplace_candidates_enabled": MARKETPLACE_CANDIDATES_ENABLED,
        "marketplace_candidate_count": len(marketplace_candidates),
        "deferred_breadth_component_count": len(deferred_breadth),
        "all_employee_tasks_have_acceptance": all(bool(task.get("acceptance")) and bool(task.get("evidence_required")) for task in employee_tasks),
    }
    quality_gate["passed"] = bool(
        quality_gate["focused_component_count"] >= quality_gate["minimum_focused_component_count"]
        and quality_gate["kept_breadth_component_count"] == 0
        and quality_gate["all_employee_tasks_have_acceptance"]
    )
    return {
        "focus_mode": "similar_function_depth_only",
        "marketplace_candidates_enabled": MARKETPLACE_CANDIDATES_ENABLED,
        "focused_components": focused,
        "rejected_breadth_components": rejected,
        "deferred_breadth_components": deferred_breadth,
        "marketplace_candidates": marketplace_candidates,
        "employee_tasks": employee_tasks,
        "quality_gate": quality_gate,
    }


def _prioritize_absorptions(component_gaps: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    task_text = " ".join(str(task.get("title", "")) + " " + str(task.get("why", "")) for task in tasks).lower()
    prioritized = []
    for gap in component_gaps[:8]:
        component = str(gap["component"])
        priority = "P0" if component in task_text or int(gap["marker_gap"]) >= 20 else "P1"
        prioritized.append(
            {
                "component": component,
                "priority": priority,
                "source_files": gap["representative_external_files"],
                "acceptance": f"Retort has a tested {component} behavior, not only a recorded signal.",
            }
        )
    return prioritized


def _requested_components(tasks: list[dict[str, Any]]) -> set[str]:
    components: set[str] = set()
    task_text = ""
    for task in tasks:
        dimension = str(task.get("dimension") or "")
        components.update(DIMENSION_COMPONENTS.get(dimension, set()))
        task_text += " " + str(task.get("title", "")) + " " + str(task.get("why", ""))
    lowered = task_text.lower()
    for component in COMPONENT_MARKERS:
        if component.replace("_", " ") in lowered or component in lowered:
            components.add(component)
    return components


def _rejected_component(component: str, external: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "component": component,
        "reason": reason,
        "external_marker_hits": int(external.get("marker_hits") or 0),
        "source_files": list(external.get("files") or [])[:5],
    }


def _similarity_score(component: str, own_hits: int, external_hits: int, own_files: list[str], external_files: list[str], requested_components: set[str]) -> int:
    score = 30 if component in DEPTH_FOCUS_COMPONENTS else 0
    if component in requested_components:
        score += 25
    if own_files:
        score += 20
    if external_files:
        score += 10
    if external_hits:
        score += min(15, int((min(own_hits, external_hits) / max(external_hits, 1)) * 15))
    return min(100, score)


def _absorption_goal(component: str) -> str:
    goals = {
        "review_pipeline": "turn external review stages into Retort discovery, localization, reflection, and task dispatch",
        "diff_hunk_review": "make each changed hunk produce scoped risk evidence and publishable comments",
        "file_grouping": "group related changed files before expensive reasoning so depth is spent on the same feature area",
        "benchmark_eval": "measure whether absorbed review behavior improves precision instead of just increasing comments",
        "safety_policy": "keep license, secret, permission, and rollback checks in the absorption path",
        "workflow_ci": "prove absorption with repeatable local gates and replay commands",
        "codebase_graph": "locate architecture hotspots and dependency impact before deciding what to absorb",
        "static_analysis": "scan absorbed diffs for rule-based security and correctness risks before LLM review",
        "context_packaging": "pack only the highest-value repository context for deep review and employee tasks",
        "semantic_index": "resolve symbols, definitions, and references before deciding impact and absorption priority",
    }
    return goals.get(component, "deepen the overlapping implementation behavior")


def _acceptance_for_component(component: str) -> str:
    return f"Retort has executable, tested {component} behavior in the absorption or PR-review path."


def _evidence_for_component(component: str) -> list[str]:
    common = ["source diff", "behavior test", "gate output"]
    if component in {"diff_hunk_review", "review_pipeline"}:
        return common + ["review JSON with stages and comments"]
    if component == "benchmark_eval":
        return common + ["precision or false-positive benchmark counters"]
    if component in {"static_analysis", "semantic_index"}:
        return common + ["machine-readable findings"]
    if component == "context_packaging":
        return common + ["bounded context manifest"]
    return common


def _employee_task_for_component(component: str) -> dict[str, Any]:
    return {
        "task_id": f"retort-depth-{component.replace('_', '-')}",
        "title": f"Deepen {component}",
        "dimension": _dimension_for_component(component),
        "priority": "P0" if component in {"review_pipeline", "diff_hunk_review", "file_grouping", "codebase_graph", "static_analysis", "context_packaging", "semantic_index"} else "P1",
        "acceptance": _acceptance_for_component(component),
        "evidence_required": _evidence_for_component(component),
        "owner_hint": "fhd-core-maintainer",
    }


def _marketplace_candidate(rejected_component: dict[str, Any]) -> dict[str, Any]:
    component = str(rejected_component.get("component") or "")
    return {
        "component": component,
        "route": "ai_employee_marketplace",
        "marketplace_employee_type": _marketplace_employee_type(component),
        "core_absorption": "blocked_for_early_phase_depth_only",
        "source_files": list(rejected_component.get("source_files") or [])[:5],
        "evidence_required": ["external capability summary", "target user workflow", "sandboxed employee task", "market listing acceptance test"],
        "acceptance": f"{component} is packaged as an AI employee candidate instead of widening Retort core.",
    }


def _deferred_breadth_component(rejected_component: dict[str, Any]) -> dict[str, Any]:
    component = str(rejected_component.get("component") or "")
    return {
        "component": component,
        "status": "closed_until_similarity_saturation",
        "reason": "early_phase_retort_self_deepening_only",
        "source_files": list(rejected_component.get("source_files") or [])[:5],
        "next_open_condition": "Retort finishes absorbing same-direction projects and core depth gates stay green.",
    }


def _marketplace_employee_type(component: str) -> str:
    mapping = {
        "provider_surface": "model-provider-integration-employee",
        "plugin_surface": "plugin-packaging-employee",
    }
    return mapping.get(component, "specialized-capability-employee")


def _dimension_for_component(component: str) -> str:
    if component in {"review_pipeline", "diff_hunk_review", "file_grouping", "codebase_graph"}:
        return "comparative_analysis_depth"
    if component == "benchmark_eval":
        return "feedback_loop_closure"
    if component in {"safety_policy", "workflow_ci"}:
        return "operational_readiness"
    return "product_operability"


def _benchmark_metrics(component_gaps: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> dict[str, int]:
    covered = {str(item.get("component")) for item in component_gaps[:8]}
    task_dimensions = {str(task.get("dimension") or "") for task in tasks}
    return {
        "component_gap_count": len(component_gaps),
        "prioritized_component_count": len(covered),
        "task_dimension_count": len(task_dimensions),
        "minimum_expected_behavior_tests": max(3, min(12, len(covered) + len(task_dimensions))),
    }


def _project_files(root: Path) -> list[Path]:
    files: list[Path] = []
    if not root.is_dir():
        return files
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        parts = set(path.relative_to(root).parts)
        if parts & SKIP_PARTS:
            continue
        if path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        files.append(path)
    return files


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
