from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ARCHITECTURE_SIGNAL_COMPONENTS = {
    "review_pipeline": ("review_pipeline", "context_localization"),
    "file_grouping": ("context_partitioning", "diff_locality"),
    "diff_hunk_review": ("diff_locality", "patch_reasoning"),
    "benchmarking": ("evaluation_loop", "regression_oracle"),
    "codebase_graph": ("codebase_graph", "context_localization"),
    "plugin_surface": ("automation_surface", "command_contract"),
    "multi_provider": ("provider_boundary", "model_adapter"),
}


def build_architecture_record(
    *,
    run_id: str,
    source: str,
    external_path: Path,
    profile: dict[str, Any],
    review_report: dict[str, Any],
    tasks: list[dict[str, Any]],
    changed_files: list[str],
    gates: list[dict[str, Any]],
    code_graph_proof: dict[str, Any] | None = None,
) -> dict[str, Any]:
    signals = [str(item) for item in profile.get("signals") or []]
    pipeline = review_report.get("review_pipeline") if isinstance(review_report.get("review_pipeline"), dict) else {}
    workflow = pipeline.get("depth_absorption_workflow") if isinstance(pipeline.get("depth_absorption_workflow"), dict) else {}
    components = _architecture_components(source, profile, workflow)
    return {
        "schema_version": 1,
        "run_id": run_id,
        "source": source,
        "external_path": str(external_path),
        "git_revision": str(profile.get("git_revision") or ""),
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "signals": signals,
        "components": components,
        "task_dimensions": sorted({str(task.get("dimension") or "") for task in tasks if task.get("dimension")}),
        "changed_files": [str(item) for item in changed_files],
        "behavior_changed": any(_is_behavior_architecture_file(item) for item in changed_files),
        "gates_passed": bool(gates) and all(bool(gate.get("ok")) for gate in gates),
        "gate_count": len(gates),
        "external_file_count": int(profile.get("file_count") or 0),
        "code_graph_proof": code_graph_proof or {},
        "code_graph_proved": bool((code_graph_proof or {}).get("passed")),
    }


def update_architecture_memory(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    memory = _read_memory(path)
    runs = [run for run in memory.get("runs") or [] if isinstance(run, dict)]
    runs = [run for run in runs if run.get("run_id") != record.get("run_id")]
    runs.append(record)
    memory = {"schema_version": 1, "runs": runs[-80:]}
    memory["component_index"] = _component_index(memory["runs"])
    memory["summary"] = _summary(memory)
    memory["deep_architecture_tasks"] = deep_architecture_tasks(memory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(memory, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return memory


def deep_architecture_tasks(memory: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for name, component in (memory.get("component_index") or {}).items():
        if not isinstance(component, dict):
            continue
        source_count = int(component.get("source_count") or 0)
        if source_count < 2:
            continue
        gate_pass_rate = float(component.get("gate_pass_rate") or 0)
        priority = "P0" if source_count >= 3 and gate_pass_rate >= 0.66 else "P1"
        rows.append(
            {
                "task_id": f"retort-architecture-{_slug(str(name))}",
                "title": f"Implement cumulative architecture pattern: {name}",
                "dimension": "architecture_depth",
                "priority": priority,
                "supporting_source_count": source_count,
                "gate_pass_rate": gate_pass_rate,
                "acceptance": "Behavior source, behavior tests, merge proof, and rollback proof all reference this architecture component.",
                "evidence_required": ["source diff", "behavior test", "passing gates", "merge commit", "rollback rehearsal"],
            }
        )
    return sorted(rows, key=lambda item: (item["priority"], -int(item["supporting_source_count"]), str(item["task_id"])))


def _architecture_components(source: str, profile: dict[str, Any], workflow: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = profile.get("signal_evidence") if isinstance(profile.get("signal_evidence"), dict) else {}
    by_component: dict[str, dict[str, Any]] = {}
    for signal in profile.get("signals") or []:
        for component in ARCHITECTURE_SIGNAL_COMPONENTS.get(str(signal), ()):
            row = by_component.setdefault(component, {"component": component, "signals": [], "evidence_files": []})
            row["signals"].append(str(signal))
            row["evidence_files"].extend(str(item) for item in evidence.get(str(signal), [])[:5])
    for focused in workflow.get("focused_components") or []:
        if not isinstance(focused, dict) or not focused.get("component"):
            continue
        component = str(focused.get("component"))
        row = by_component.setdefault(component, {"component": component, "signals": [], "evidence_files": []})
        row["signals"].append(component)
        row["evidence_files"].extend(str(item) for item in focused.get("source_files") or [])
    for component in _source_specific_components(source):
        by_component.setdefault(component, {"component": component, "signals": ["source_architecture"], "evidence_files": []})
    rows = []
    for row in by_component.values():
        row["signals"] = sorted(set(row["signals"]))
        row["evidence_files"] = sorted(set(row["evidence_files"]))[:8]
        row["depth_score"] = min(100, 35 + 8 * len(row["signals"]) + 3 * len(row["evidence_files"]))
        rows.append(row)
    return sorted(rows, key=lambda item: (int(item["depth_score"]), str(item["component"])), reverse=True)


def _source_specific_components(source: str) -> list[str]:
    lowered = source.lower()
    components: list[str] = []
    if "aider" in lowered:
        components.extend(["repo_map_context", "edit_planning_loop"])
    if "swe-agent" in lowered or "swe_agent" in lowered:
        components.extend(["issue_reproduction_loop", "patch_attempt_loop"])
    if "openhands" in lowered or "software-agent" in lowered:
        components.extend(["agent_runtime_boundary", "sandbox_execution_harness"])
    return components


def _component_index(runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for run in runs:
        source = str(run.get("source") or "")
        run_id = str(run.get("run_id") or "")
        gates_passed = bool(run.get("gates_passed"))
        for component in run.get("components") or []:
            if not isinstance(component, dict) or not component.get("component"):
                continue
            name = str(component.get("component"))
            row = index.setdefault(name, {"component": name, "sources": [], "run_ids": [], "evidence_files": [], "gate_pass_count": 0, "run_count": 0, "code_graph_proof_count": 0})
            row["sources"].append(source)
            row["run_ids"].append(run_id)
            row["evidence_files"].extend(str(item) for item in component.get("evidence_files") or [])
            row["gate_pass_count"] += 1 if gates_passed else 0
            row["run_count"] += 1
            row["code_graph_proof_count"] += 1 if run.get("code_graph_proved") else 0
    for row in index.values():
        sources = sorted({item for item in row["sources"] if item})
        evidence_files = sorted({item for item in row["evidence_files"] if item})[:12]
        row["sources"] = sources
        row["source_count"] = len(sources)
        row["run_ids"] = sorted({item for item in row["run_ids"] if item})
        row["evidence_files"] = evidence_files
        row["gate_pass_rate"] = round(row["gate_pass_count"] / row["run_count"], 3) if row["run_count"] else 0.0
        row["architecture_depth_score"] = min(100, 25 + 15 * row["source_count"] + 5 * row["gate_pass_count"] + 6 * row["code_graph_proof_count"] + min(20, len(evidence_files) * 2))
        row["ready_for_deep_refactor"] = row["source_count"] >= 3 and row["gate_pass_rate"] >= 0.66
    return dict(sorted(index.items(), key=lambda item: (int(item[1]["architecture_depth_score"]), item[0]), reverse=True))


def _summary(memory: dict[str, Any]) -> dict[str, Any]:
    runs = [run for run in memory.get("runs") or [] if isinstance(run, dict)]
    sources = sorted({str(run.get("source") or "") for run in runs if run.get("source")})
    components = [component for component in (memory.get("component_index") or {}).values() if isinstance(component, dict)]
    ready = [component for component in components if component.get("ready_for_deep_refactor")]
    return {
        "run_count": len(runs),
        "source_count": len(sources),
        "gate_passed_run_count": sum(1 for run in runs if run.get("gates_passed")),
        "component_count": len(components),
        "repeated_component_count": sum(1 for component in components if int(component.get("source_count") or 0) >= 2),
        "ready_component_count": len(ready),
        "ready_components": [str(component.get("component")) for component in ready[:8]],
    }


def _read_memory(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": 1, "runs": []}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "runs": []}
    return parsed if isinstance(parsed, dict) else {"schema_version": 1, "runs": []}


def _is_behavior_architecture_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.endswith(".py") and "/tests/" not in normalized and not normalized.endswith("absorbed_capabilities.py")


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in value.lower()).strip("-") or "component"
