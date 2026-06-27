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
DIFF_REPLAY_STAGES = (
    "parse_unified_diff",
    "group_related_files",
    "map_diff_hunk_context",
    "rank_publishable_comments",
    "dispatch_employee_task",
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


def build_diff_pipeline_replay(
    diff_text: str,
    *,
    issue_context: str = "",
    previous_diff_text: str = "",
    max_comments: int = 20,
    max_files_per_chunk: int = 8,
    max_chars_per_chunk: int = 30000,
) -> dict[str, Any]:
    """Run the absorbed review pipeline against a real diff and return proof data."""
    from retort_engine.pr_review import review_diff

    chunks = chunk_unified_diff_by_review_context(
        diff_text,
        max_files_per_chunk=max_files_per_chunk,
        max_chars_per_chunk=max_chars_per_chunk,
    )
    reviews = [
        review_diff(
            str(chunk["diff_text"]),
            issue_context=issue_context,
            previous_diff_text=previous_diff_text,
            max_comments=max_comments,
        )
        for chunk in chunks
    ]
    if not reviews:
        reviews = [review_diff(diff_text, issue_context=issue_context, previous_diff_text=previous_diff_text, max_comments=max_comments)]
    summary = _merge_review_summaries(reviews)
    context_groups = _merge_context_groups(reviews)
    comments = [item for review in reviews for item in review.get("comments") or [] if isinstance(item, dict)]
    task_groups = _merge_task_groups(reviews)
    publishable_comments = [item for item in comments if item.get("publishable") is not False]
    selected_comments = publishable_comments[:max_comments]
    replay_summary = {
        "file_count": int(summary.get("file_count") or 0),
        "hunk_count": int(summary.get("hunk_count") or 0),
        "context_group_count": len(context_groups),
        "comment_count": len(selected_comments),
        "candidate_comment_count": len(comments),
        "publishable_comment_count": len(selected_comments),
        "task_group_count": len(task_groups),
        "absorbed_context_signal_strength": int(summary.get("absorbed_context_signal_strength") or 0),
        "diff_grouping_depth_score": _diff_grouping_depth_score(summary, context_groups, selected_comments, task_groups, chunks),
        "ready_for_employee_tasking": bool(summary.get("ready_for_employee_tasking")),
        "chunk_count": len(chunks),
        "large_diff_chunking": len(chunks) > 1,
        "max_files_per_chunk": max_files_per_chunk,
        "max_chars_per_chunk": max_chars_per_chunk,
        "largest_chunk_file_count": max([int(chunk.get("file_count") or 0) for chunk in chunks] or [0]),
    }
    return {
        "status": "ready" if any(review.get("status") == "reviewed" for review in reviews) and replay_summary["context_group_count"] else str(reviews[0].get("status") or "empty"),
        "pipeline_stages": list(DIFF_REPLAY_STAGES),
        "summary": replay_summary,
        "chunks": [{key: value for key, value in chunk.items() if key != "diff_text"} for chunk in chunks],
        "context_groups": context_groups,
        "comments": [_comment_replay_payload(item) for item in selected_comments],
        "task_groups": task_groups,
        "evidence": {
            "source": "retort_engine.pr_review.review_diff",
            "issue_context_supplied": bool(issue_context.strip()),
            "previous_diff_supplied": bool(previous_diff_text.strip()),
            "core_behavior": "diff_grouping_to_publishable_review_and_employee_tasking",
        },
    }


def chunk_unified_diff_by_review_context(diff_text: str, *, max_files_per_chunk: int = 8, max_chars_per_chunk: int = 30000) -> list[dict[str, Any]]:
    from retort_engine.pr_review import review_context_for_file

    sections = _diff_file_sections(diff_text)
    if not sections:
        return []
    ordered = sorted(
        sections,
        key=lambda item: (_context_priority(review_context_for_file(str(item["path"]))), int(item["index"])),
    )
    chunks: list[dict[str, Any]] = []
    current_sections: list[dict[str, Any]] = []
    current_context = ""
    for section in ordered:
        context = review_context_for_file(str(section["path"]))
        section_text = str(section["diff_text"])
        current_text_len = sum(len(str(item["diff_text"])) for item in current_sections)
        should_flush = bool(
            current_sections
            and (
                context != current_context
                or len(current_sections) >= max(1, max_files_per_chunk)
                or current_text_len + len(section_text) > max(1, max_chars_per_chunk)
            )
        )
        if should_flush:
            chunks.append(_diff_chunk(len(chunks), current_context, current_sections))
            current_sections = []
        current_context = context
        current_sections.append(section)
    if current_sections:
        chunks.append(_diff_chunk(len(chunks), current_context, current_sections))
    return chunks


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


def _diff_grouping_depth_score(summary: dict[str, Any], context_groups: list[dict[str, Any]], publishable_comments: list[dict[str, Any]], task_groups: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> int:
    score = 0
    if int(summary.get("file_count") or 0) > 0:
        score += 15
    if int(summary.get("hunk_count") or 0) > 0:
        score += 15
    score += min(25, len(context_groups) * 8)
    score += min(20, len(publishable_comments) * 5)
    if task_groups:
        score += 15
    if int(summary.get("absorbed_context_signal_strength") or 0) >= 80:
        score += 10
    if len(chunks) > 1:
        score += 10
    return min(100, score)


def _diff_file_sections(diff_text: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current: list[str] = []
    current_path = ""
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            if current:
                sections.append({"index": len(sections), "path": current_path or _path_from_section(current), "diff_text": "\n".join(current) + "\n"})
            current = [line]
            current_path = _path_from_diff_header(line)
            continue
        if current:
            if line.startswith("+++ b/"):
                current_path = line[6:]
            current.append(line)
    if current:
        sections.append({"index": len(sections), "path": current_path or _path_from_section(current), "diff_text": "\n".join(current) + "\n"})
    return sections


def _path_from_diff_header(line: str) -> str:
    parts = line.split()
    if len(parts) >= 4 and parts[3].startswith("b/"):
        return parts[3][2:]
    return ""


def _path_from_section(lines: list[str]) -> str:
    for line in lines:
        if line.startswith("+++ b/"):
            return line[6:]
    return ""


def _context_priority(context: str) -> int:
    order = ("security", "ci_config", "tests", "runtime", "config", "frontend", "docs", "other")
    return order.index(context) if context in order else len(order)


def _diff_chunk(index: int, context: str, sections: list[dict[str, Any]]) -> dict[str, Any]:
    files = [str(item.get("path") or "") for item in sections if item.get("path")]
    diff_text = "".join(str(item.get("diff_text") or "") for item in sections)
    return {
        "chunk_id": f"chunk-{index + 1}",
        "context": context,
        "priority": _context_priority(context),
        "files": files,
        "file_count": len(files),
        "char_count": len(diff_text),
        "diff_text": diff_text,
    }


def _merge_review_summaries(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    summaries = [review.get("summary") for review in reviews if isinstance(review.get("summary"), dict)]
    return {
        "file_count": sum(int(item.get("file_count") or 0) for item in summaries),
        "hunk_count": sum(int(item.get("hunk_count") or 0) for item in summaries),
        "absorbed_context_signal_strength": max([int(item.get("absorbed_context_signal_strength") or 0) for item in summaries] or [0]),
        "ready_for_employee_tasking": any(bool(item.get("ready_for_employee_tasking")) for item in summaries),
    }


def _merge_context_groups(reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for review in reviews:
        for group in review.get("context_groups") or []:
            if not isinstance(group, dict):
                continue
            context = str(group.get("context") or "other")
            row = merged.setdefault(context, {"context": context, "files": [], "file_count": 0, "hunk_count": 0, "added_change_count": 0, "review_focus": group.get("review_focus")})
            row["files"].extend(str(item) for item in group.get("files") or [])
            row["file_count"] = int(row["file_count"]) + int(group.get("file_count") or 0)
            row["hunk_count"] = int(row["hunk_count"]) + int(group.get("hunk_count") or 0)
            row["added_change_count"] = int(row["added_change_count"]) + int(group.get("added_change_count") or 0)
    return sorted(merged.values(), key=lambda group: (_context_priority(str(group["context"])), str(group["context"])))


def _merge_task_groups(reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for review in reviews:
        for group in review.get("task_groups") or []:
            if not isinstance(group, dict):
                continue
            key = str(group.get("review_context") or group.get("task_id") or "task")
            row = rows.setdefault(key, {**group, "comment_count": 0})
            row["comment_count"] = int(row.get("comment_count") or 0) + int(group.get("comment_count") or 0)
    return sorted(rows.values(), key=lambda group: (_context_priority(str(group.get("review_context") or "other")), str(group.get("task_id") or "")))


def _comment_replay_payload(comment: dict[str, Any]) -> dict[str, Any]:
    return {
        "file": str(comment.get("file") or ""),
        "line": int(comment.get("line") or 0),
        "severity": str(comment.get("severity") or ""),
        "review_stage": str(comment.get("review_stage") or ""),
        "review_context": str(comment.get("review_context") or ""),
        "publishable": bool(comment.get("publishable", True)),
    }


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
