from __future__ import annotations

from pathlib import Path
from typing import Any


SOURCE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".md", ".json", ".yml", ".yaml", ".toml"}
SKIP_PARTS = {".git", ".retort", "__pycache__", "node_modules", ".venv", ".pytest_cache", ".ruff_cache", "dist", "build"}
PIPELINE_STAGES = (
    "materialize_external_snapshot",
    "group_related_files",
    "extract_review_signals",
    "compare_component_gaps",
    "rank_absorption_tasks",
    "verify_feedback_loop",
)
COMPONENT_MARKERS = {
    "review_pipeline": ("review", "reflection", "localization", "diff hunk", "patch set", "code review"),
    "file_grouping": ("file group", "group files", "changed files", "related files", "pathspec"),
    "benchmark_eval": ("benchmark", "precision", "recall", "evaluation", "eval"),
    "provider_surface": ("provider", "model", "openai", "anthropic", "ollama", "multi-provider"),
    "plugin_surface": ("plugin", "extension", "github action", "codex", "vsix"),
    "safety_policy": ("license", "security", "policy", "permission", "sandbox"),
    "workflow_ci": ("workflow", "pipeline", "ci", "gate", "test"),
}


def build_absorption_review_report(own_project: str | Path, external_project: str | Path, tasks: list[dict[str, Any]]) -> dict[str, Any]:
    own = Path(own_project)
    external = Path(external_project)
    own_groups = group_review_files(own)
    external_groups = group_review_files(external)
    component_gaps = compare_component_gaps(own_groups, external_groups)
    return {
        "pipeline_stages": list(PIPELINE_STAGES),
        "own_file_groups": own_groups,
        "external_file_groups": external_groups,
        "component_gaps": component_gaps,
        "prioritized_absorptions": _prioritize_absorptions(component_gaps, tasks),
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
