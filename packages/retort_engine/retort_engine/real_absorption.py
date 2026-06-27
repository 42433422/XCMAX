from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retort_engine.architecture_memory import build_architecture_record, update_architecture_memory
from retort_engine.architecture_refactor import build_core_refactor_plan, write_core_refactor_plan
from retort_engine.feedback_audit import audit_feedback_closure
from retort_engine.license_gate import license_gate
from retort_engine.review_pipeline import build_absorption_review_report


SOURCE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".md", ".toml", ".yml", ".yaml", ".json", ".go"}
SKIP_PARTS = {".git", ".retort", "__pycache__", "node_modules", ".venv", ".pytest_cache", ".ruff_cache", "dist", "build"}
CAPABILITY_MODEL_SIGNALS = {"review_pipeline", "file_grouping", "diff_hunk_review", "benchmarking", "plugin_surface"}


def apply_real_absorption(payload: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    root = Path(str(payload.get("own_project") or payload.get("project") or ".")).expanduser().resolve()
    external_path = Path(str(payload.get("external_path") or "")).expanduser().resolve()
    source = str(payload.get("source") or payload.get("github_url") or payload.get("external_path") or "")
    tasks = [item for item in payload.get("tasks") or [] if isinstance(item, dict)]
    if not external_path.is_dir():
        return _execution_result("skipped_no_external_project", root, source, started, [], [], [], "External project was not materialized locally.")
    if not tasks:
        return _execution_result("skipped_no_tasks", root, source, started, [], [], [], "No absorption tasks were generated.")

    run_id = _run_id(source)
    external_profile = _external_profile(external_path)
    semantic_review = _semantic_review(root, external_path)
    absorption_quality_path = _absorption_quality_target(root)
    module_path = _implementation_target(root)
    capability_path = _capability_target(root)
    capability_test_path = _capability_test_target(root)
    review_context_bias_path = _review_context_bias_target(root)
    review_context_bias_test_path = _review_context_bias_test_target(root)
    architecture_memory_path = _architecture_memory_target(root)
    core_refactor_plan_path = _core_refactor_plan_target(root)
    frontend_app_path = _frontend_app_target(root)
    frontend_visual_test_path = _frontend_visual_test_target(root)
    log_path = root / "docs" / "retort_absorption_log.md"
    report_path = root / "docs" / "retort_external_review_report.json"
    writes_capability_model = _should_absorb_capability_model(external_profile)
    writes_frontend_visual = _should_absorb_frontend_visual(external_profile)
    tracked_paths = [
        absorption_quality_path,
        module_path,
        review_context_bias_path,
        review_context_bias_test_path,
        architecture_memory_path,
        core_refactor_plan_path,
        log_path,
        report_path,
    ]
    if writes_capability_model:
        tracked_paths.extend([capability_path, capability_test_path])
    if writes_frontend_visual:
        tracked_paths.extend([frontend_app_path, frontend_visual_test_path])
    before = _snapshot(tracked_paths)
    review_report = _review_report(root, run_id, source, external_path, tasks, external_profile, semantic_review)
    _write_absorption_quality_helper(absorption_quality_path)
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text(_module_content(run_id, source, external_path, tasks, external_profile), encoding="utf-8")
    if writes_capability_model:
        capability_path.parent.mkdir(parents=True, exist_ok=True)
        capability_path.write_text(_capability_module_content(run_id, source, external_path, tasks, external_profile, review_report), encoding="utf-8")
        capability_test_path.parent.mkdir(parents=True, exist_ok=True)
        capability_test_path.write_text(_capability_test_content(_capability_import_name(root, capability_path), source), encoding="utf-8")
    writes_review_context_bias = _should_absorb_review_context_bias(external_profile)
    if writes_review_context_bias:
        review_context_bias_path.parent.mkdir(parents=True, exist_ok=True)
        review_context_bias_path.write_text(_review_context_bias_content(run_id, source, external_path, external_profile), encoding="utf-8")
        review_context_bias_test_path.parent.mkdir(parents=True, exist_ok=True)
        review_context_bias_test_path.write_text(_review_context_bias_test_content(_capability_import_name(root, review_context_bias_path), source), encoding="utf-8")
    if writes_frontend_visual:
        _write_frontend_visual_profile(frontend_app_path, run_id, source, external_path, external_profile)
        frontend_visual_test_path.parent.mkdir(parents=True, exist_ok=True)
        frontend_visual_test_path.write_text(_frontend_visual_test_content(source), encoding="utf-8")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _append_log(log_path, run_id, source, external_path, tasks, external_profile)
    report_path.write_text(json.dumps(review_report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    changed_files = _changed_files(before, tracked_paths)
    gates = [
        _run_command([_python(payload), "-c", "import ast,pathlib,sys; ast.parse(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))", str(absorption_quality_path)], root, timeout=60),
        _run_command([_python(payload), "-c", "import ast,pathlib,sys; ast.parse(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))", str(module_path)], root, timeout=60),
    ]
    if writes_capability_model:
        gates.extend(
            [
                _run_command([_python(payload), "-c", "import ast,pathlib,sys; ast.parse(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))", str(capability_path)], root, timeout=60),
                _run_command([_python(payload), "-m", "pytest", str(capability_test_path.relative_to(root)), "-q"], root, timeout=120),
            ]
        )
    elif capability_path.is_file() and capability_test_path.is_file():
        gates.extend(
            [
                _run_command([_python(payload), "-c", "import ast,pathlib,sys; ast.parse(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))", str(capability_path)], root, timeout=60),
                _run_command([_python(payload), "-m", "pytest", str(capability_test_path.relative_to(root)), "-q"], root, timeout=120),
            ]
        )
    if writes_review_context_bias:
        gates.extend(
            [
                _run_command([_python(payload), "-c", "import ast,pathlib,sys; ast.parse(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))", str(review_context_bias_path)], root, timeout=60),
                _run_command([_python(payload), "-m", "pytest", str(review_context_bias_test_path.relative_to(root)), "-q"], root, timeout=120),
            ]
        )
    if writes_frontend_visual:
        gates.append(_run_command([_python(payload), "-m", "pytest", str(frontend_visual_test_path.relative_to(root)), "-q"], root, timeout=120))
    if payload.get("run_local_gates"):
        gates.extend(_local_gate_commands(root, payload))
    changed_files = _changed_files(before, tracked_paths)
    architecture_record = build_architecture_record(
        run_id=run_id,
        source=source,
        external_path=external_path,
        profile=external_profile,
        review_report=review_report,
        tasks=tasks,
        changed_files=changed_files,
        gates=gates,
    )
    architecture_memory = update_architecture_memory(architecture_memory_path, architecture_record)
    gates.append(_run_command([_python(payload), "-c", "import json,pathlib,sys; data=json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')); assert data.get('summary')", str(architecture_memory_path)], root, timeout=60))
    core_refactor_plan = build_core_refactor_plan(architecture_memory, project_root=root)
    write_core_refactor_plan(core_refactor_plan_path, core_refactor_plan)
    gates.append(
        _run_command(
            [
                _python(payload),
                "-c",
                "import json,pathlib,sys; data=json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')); assert data.get('gate', {}).get('passed')",
                str(core_refactor_plan_path),
            ],
            root,
            timeout=60,
        )
    )
    changed_files = _changed_files(before, tracked_paths)
    diff_summary = _git_diff_summary(root, changed_files)
    result = _execution_result(
        "applied" if changed_files else "noop",
        root,
        source,
        started,
        changed_files,
        gates,
        diff_summary,
        "CLI absorption applied project-local code and evidence artifacts.",
    )
    result["run_id"] = run_id
    result["external_profile"] = external_profile
    result["semantic_review"] = semantic_review
    result["capability_module_path"] = str(capability_path) if writes_capability_model else ""
    result["capability_test_path"] = str(capability_test_path) if writes_capability_model else ""
    result["capability_model_preserved"] = not writes_capability_model
    result["architecture_memory_path"] = str(architecture_memory_path)
    result["architecture_memory_summary"] = architecture_memory.get("summary") or {}
    result["core_refactor_plan_path"] = str(core_refactor_plan_path)
    result["core_refactor_plan_summary"] = core_refactor_plan.get("summary") or {}
    result["review_context_bias_path"] = str(review_context_bias_path) if writes_review_context_bias else ""
    result["review_context_bias_test_path"] = str(review_context_bias_test_path) if writes_review_context_bias else ""
    result["frontend_visual_absorption_path"] = str(frontend_app_path) if writes_frontend_visual else ""
    result["frontend_visual_absorption_test_path"] = str(frontend_visual_test_path) if writes_frontend_visual else ""
    result["review_report_path"] = str(report_path)
    result["reproducibility"] = {"command": f"retort absorb --own-project {root} --external-path {external_path} --run-local-gates --branch-workflow --merge-after"}
    result["queue_records_written"] = _write_execution_queue_records(str(payload.get("employee_queue") or ""), run_id, source, tasks)
    employee_results_path = _write_employee_results(root, run_id, source, tasks, result, payload)
    result["employee_results_path"] = str(employee_results_path)
    result["feedback_audit"] = audit_feedback_closure(queue_path=str(payload.get("employee_queue") or ""), history_store=str(payload.get("history_store") or ""), employee_results_dir=employee_results_path.parent)
    _record_execution(root, result)
    return result


def _implementation_target(root: Path) -> Path:
    retort_package = root / "retort_engine"
    if retort_package.is_dir() and (retort_package / "__init__.py").is_file():
        return retort_package / "absorbed_external_patterns.py"
    packages = [path for path in root.iterdir() if path.is_dir() and (path / "__init__.py").is_file() and not path.name.startswith(".") and path.name != "tests"]
    if len(packages) == 1:
        return packages[0] / "retort_absorbed_patterns.py"
    return root / "retort_absorbed_patterns.py"


def _absorption_quality_target(root: Path) -> Path:
    retort_package = root / "retort_engine"
    if retort_package.is_dir() and (retort_package / "__init__.py").is_file():
        return retort_package / "absorption_quality.py"
    packages = [path for path in root.iterdir() if path.is_dir() and (path / "__init__.py").is_file() and not path.name.startswith(".") and path.name != "tests"]
    if len(packages) == 1:
        return packages[0] / "absorption_quality.py"
    return root / "absorption_quality.py"


def _write_absorption_quality_helper(target: Path) -> None:
    source = Path(__file__).with_name("absorption_quality.py").resolve()
    if target.resolve() == source:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_read(source), encoding="utf-8")


def _capability_target(root: Path) -> Path:
    retort_package = root / "retort_engine"
    if retort_package.is_dir() and (retort_package / "__init__.py").is_file():
        return retort_package / "absorbed_capabilities.py"
    packages = [path for path in root.iterdir() if path.is_dir() and (path / "__init__.py").is_file() and not path.name.startswith(".") and path.name != "tests"]
    if len(packages) == 1:
        return packages[0] / "absorbed_capabilities.py"
    return root / "absorbed_capabilities.py"


def _capability_test_target(root: Path) -> Path:
    return root / "tests" / "test_absorbed_capabilities.py"


def _architecture_memory_target(root: Path) -> Path:
    return root / "docs" / "retort_architecture_memory.json"


def _core_refactor_plan_target(root: Path) -> Path:
    return root / "docs" / "retort_core_refactor_plan.json"


def _review_context_bias_target(root: Path) -> Path:
    retort_package = root / "retort_engine"
    if retort_package.is_dir() and (retort_package / "__init__.py").is_file():
        return retort_package / "review_context_bias.py"
    packages = [path for path in root.iterdir() if path.is_dir() and (path / "__init__.py").is_file() and not path.name.startswith(".") and path.name != "tests"]
    if len(packages) == 1:
        return packages[0] / "review_context_bias.py"
    return root / "review_context_bias.py"


def _review_context_bias_test_target(root: Path) -> Path:
    return root / "tests" / "test_review_context_bias.py"


def _frontend_app_target(root: Path) -> Path:
    return root / "retort_engine" / "frontend" / "app.js"


def _frontend_visual_test_target(root: Path) -> Path:
    return root / "tests" / "test_frontend_visual_absorption.py"


def _capability_import_name(root: Path, capability_path: Path) -> str:
    rel = capability_path.relative_to(root)
    parts = list(rel.with_suffix("").parts)
    if parts and parts[0] == "tests":
        parts = parts[1:]
    return ".".join(parts)


def _module_content(run_id: str, source: str, external_path: Path, tasks: list[dict[str, Any]], profile: dict[str, Any]) -> str:
    payload = {
        "run_id": run_id,
        "source": source,
        "external_path": str(external_path),
        "external_profile": profile,
        "tasks": [
            {
                "task_id": str(task.get("task_id") or ""),
                "title": str(task.get("title") or ""),
                "dimension": str(task.get("dimension") or ""),
                "priority": str(task.get("priority") or ""),
                "why": str(task.get("why") or ""),
            }
            for task in tasks
        ],
    }
    payload_text = repr(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    return f'''"""Retort-applied external absorption patterns.

This file is generated by `retort apply-absorption`. It records project-local
implementation signals adapted from an external repository without copying
license-sensitive source code.
"""

from __future__ import annotations

import json
from typing import Any


ABSORBED_EXTERNAL_PATTERNS: dict[str, Any] = json.loads({payload_text})


def absorbed_external_patterns() -> dict[str, Any]:
    """Return the latest externally absorbed implementation signals."""
    return dict(ABSORBED_EXTERNAL_PATTERNS)
'''


def _should_absorb_review_context_bias(profile: dict[str, Any]) -> bool:
    signals = set(profile.get("signals") or [])
    return bool(signals & {"review_pipeline", "file_grouping", "diff_hunk_review"})


def _should_absorb_capability_model(profile: dict[str, Any]) -> bool:
    signals = set(profile.get("signals") or [])
    return bool(signals & CAPABILITY_MODEL_SIGNALS)


def _should_absorb_frontend_visual(profile: dict[str, Any]) -> bool:
    signals = set(profile.get("signals") or [])
    return bool(signals & {"planet_frontend", "atmosphere_shader", "procedural_surface", "webgl_scene"})


def _review_context_bias_content(run_id: str, source: str, external_path: Path, profile: dict[str, Any]) -> str:
    signals = list(profile.get("signals") or [])
    signal_evidence = dict(profile.get("signal_evidence") or {})
    focus = _context_focus_from_signals(signals)
    payload = {
        "run_id": run_id,
        "enabled": bool(signals),
        "source": source,
        "external_path": str(external_path),
        "signals": signals,
        "signal_evidence": signal_evidence,
        "context_focus": focus,
        "reason": "absorbed external file grouping and review pipeline signals",
    }
    payload_text = repr(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    return f'''from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads({payload_text})


def review_context_bias() -> dict[str, Any]:
    """Return the absorbed context grouping profile used by PR review."""
    return dict(REVIEW_CONTEXT_BIAS)


def file_grouping_enabled() -> bool:
    """Tell PR review whether absorbed external evidence supports context grouping."""
    signals = set(REVIEW_CONTEXT_BIAS.get("signals") or [])
    return bool(REVIEW_CONTEXT_BIAS.get("enabled")) and bool(signals & {{"file_grouping", "review_pipeline", "diff_hunk_review"}})


def context_signal_strength() -> int:
    """Score how much absorbed evidence should influence review grouping."""
    signals = set(REVIEW_CONTEXT_BIAS.get("signals") or [])
    return min(100, 20 * len(signals & {{"file_grouping", "review_pipeline", "diff_hunk_review", "benchmarking", "safety_policy"}}))
'''


def _review_context_bias_test_content(import_name: str, source: str) -> str:
    source_text = repr(source)
    return f'''from __future__ import annotations

from {import_name} import context_signal_strength, file_grouping_enabled, review_context_bias

EXPECTED_ABSORPTION_SOURCE = {source_text}


def test_review_context_bias_exposes_absorbed_file_grouping() -> None:
    bias = review_context_bias()

    assert bias["enabled"] is True
    assert bias["source"] == EXPECTED_ABSORPTION_SOURCE
    assert set(bias["signals"]) & {{"file_grouping", "review_pipeline", "diff_hunk_review"}}
    assert file_grouping_enabled() is True
    assert context_signal_strength() >= 20
'''


def _context_focus_from_signals(signals: list[str]) -> list[str]:
    focus: list[str] = []
    if "safety_policy" in signals:
        focus.append("security")
    if "file_grouping" in signals or "review_pipeline" in signals:
        focus.extend(["runtime", "tests", "ci_config"])
    if "benchmarking" in signals:
        focus.append("tests")
    if "plugin_surface" in signals:
        focus.append("config")
    if "multi_provider" in signals:
        focus.append("config")
    focus.append("docs")
    return list(dict.fromkeys(focus))


def _write_frontend_visual_profile(app_path: Path, run_id: str, source: str, external_path: Path, profile: dict[str, Any]) -> None:
    if not app_path.is_file():
        return
    signals = set(str(item) for item in profile.get("signals") or [])
    visual_profile = {
        "source": source,
        "enabled": True,
        "visual_family": "absorbed-procedural-planet",
        "run_id": run_id,
        "external_path": str(external_path),
        "absorbed_signals": sorted(signals & {"planet_frontend", "atmosphere_shader", "procedural_surface", "webgl_scene"}),
        "palette": _planet_palette(signals),
        "layers": {
            "atmospheric_rim": "atmosphere_shader" in signals or "planet_frontend" in signals,
            "procedural_landmasses": "procedural_surface" in signals or "planet_frontend" in signals,
            "translucent_clouds": "atmosphere_shader" in signals or "webgl_scene" in signals,
            "orbital_rings": "webgl_scene" in signals or "planet_frontend" in signals,
            "terminator_shadow": True,
        },
        "license_boundary": "visual principles only; no external source or texture copied",
    }
    replacement = "const ABSORBED_PLANET_VISUAL_PROFILE = " + json.dumps(visual_profile, ensure_ascii=False, indent=2, sort_keys=True) + ";"
    text = _read(app_path)
    updated, count = re.subn(r"const ABSORBED_PLANET_VISUAL_PROFILE = \{.*?\n\};", replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError("Could not update ABSORBED_PLANET_VISUAL_PROFILE in frontend app.js")
    app_path.write_text(updated, encoding="utf-8")


def _planet_palette(signals: set[str]) -> dict[str, str]:
    if "atmosphere_shader" in signals and "procedural_surface" in signals:
        return {
            "ocean": "#102c5f",
            "shallow": "#37d6cf",
            "land": "#cda96b",
            "highland": "#fff0bd",
            "cloud": "#f7fbff",
            "rim": "#95f4ff",
            "ring": "#f4ca78",
            "night": "#02050d",
        }
    return {
        "ocean": "#17345c",
        "shallow": "#56d8db",
        "land": "#b6c878",
        "highland": "#fff3c7",
        "cloud": "#f7fbff",
        "rim": "#8ee8ff",
        "ring": "#d8c17a",
        "night": "#030711",
    }


def _frontend_visual_test_content(source: str) -> str:
    source_text = repr(source)
    return f'''from __future__ import annotations

import json
import re
from pathlib import Path


EXPECTED_VISUAL_SOURCE = {source_text}


def _app_text() -> str:
    return (Path(__file__).resolve().parents[1] / "retort_engine" / "frontend" / "app.js").read_text(encoding="utf-8")


def _absorbed_profile() -> dict[str, object]:
    text = _app_text()
    match = re.search(r"const ABSORBED_PLANET_VISUAL_PROFILE = (\\{{.*?\\n\\}});", text, re.S)
    assert match, "absorbed planet visual profile is missing"
    return json.loads(match.group(1))


def test_absorbed_planet_visual_profile_references_external_source() -> None:
    profile = _absorbed_profile()

    assert profile["enabled"] is True
    assert profile["source"] == EXPECTED_VISUAL_SOURCE
    assert profile["visual_family"] == "absorbed-procedural-planet"
    assert profile["license_boundary"] == "visual principles only; no external source or texture copied"
    assert set(profile["absorbed_signals"]) & {{"planet_frontend", "atmosphere_shader", "procedural_surface", "webgl_scene"}}


def test_planet_renderer_uses_absorbed_visual_layers() -> None:
    text = _app_text()

    assert "planetVisualProfile()" in text
    assert "procedural_landmasses" in text
    assert "translucent_clouds" in text
    assert "terminator_shadow" in text
    assert "atmospheric_rim" in text
    assert "rgbaHex(palette.rim" in text
'''


def _capability_module_content(run_id: str, source: str, external_path: Path, tasks: list[dict[str, Any]], profile: dict[str, Any], review_report: dict[str, Any]) -> str:
    capability_payload = {
        "run_id": run_id,
        "source": source,
        "external_path": str(external_path),
        "signals": list(profile.get("signals") or []),
        "signal_evidence": dict(profile.get("signal_evidence") or {}),
        "component_gaps": list((review_report.get("review_pipeline") or {}).get("component_gaps") or [])[:12],
        "prioritized_absorptions": list((review_report.get("review_pipeline") or {}).get("prioritized_absorptions") or [])[:12],
        "depth_absorption_workflow": dict((review_report.get("review_pipeline") or {}).get("depth_absorption_workflow") or {}),
        "benchmark": dict((review_report.get("review_pipeline") or {}).get("benchmark") or {}),
        "tasks": [
            {
                "task_id": str(task.get("task_id") or ""),
                "title": str(task.get("title") or ""),
                "dimension": str(task.get("dimension") or ""),
                "priority": str(task.get("priority") or ""),
                "why": str(task.get("why") or ""),
            }
            for task in tasks
        ],
    }
    payload_text = repr(json.dumps(capability_payload, ensure_ascii=True, indent=2, sort_keys=True))
    return f'''"""Runtime behavior absorbed from external review tools.

This module is rewritten by `retort apply-absorption` when an external project
contributes implementation signals that should affect Retort behavior. Unlike
the audit report, these functions are executable gates used by product code and
tests to decide whether an absorption actually improved Retort.
"""

from __future__ import annotations

import json
from typing import Any

from retort_engine.absorption_quality import (
    absorption_quality_gate as _absorption_quality_gate,
    advantage_diff_map as _advantage_diff_map,
    capability_progress_from_execution as _capability_progress_from_execution,
    explain_missing_absorption_evidence as _explain_missing_absorption_evidence,
)


ABSORBED_CAPABILITY_STATE: dict[str, Any] = json.loads({payload_text})

SIGNAL_WEIGHTS = {{
    "review_pipeline": 24,
    "file_grouping": 20,
    "diff_hunk_review": 18,
    "benchmarking": 16,
    "plugin_surface": 12,
    "multi_provider": 10,
}}


def absorbed_capability_plan() -> dict[str, Any]:
    """Return the latest executable capability plan from external absorption."""
    state = dict(ABSORBED_CAPABILITY_STATE)
    state["ranked_capabilities"] = ranked_capabilities()
    state["depth_absorption_plan"] = depth_absorption_plan()
    state["minimum_behavior_tests"] = int((state.get("benchmark") or {{}}).get("minimum_expected_behavior_tests") or 3)
    return state


def depth_absorption_plan() -> dict[str, Any]:
    """Return the depth-only plan that decides what Retort should actually absorb."""
    workflow = dict(ABSORBED_CAPABILITY_STATE.get("depth_absorption_workflow") or {{}})
    focused = list(workflow.get("focused_components") or [])
    workflow["ranked_focus_components"] = sorted(
        focused,
        key=lambda item: (str(item.get("priority") or "P9") == "P0", int(item.get("similarity_score") or 0), int(item.get("depth_gap") or 0)),
        reverse=True,
    )
    workflow["breadth_rejected"] = [item for item in workflow.get("rejected_breadth_components") or [] if item.get("reason") == "breadth_only_for_current_phase"]
    return workflow


def depth_first_task_queue() -> list[dict[str, Any]]:
    """Expose employee tasks that deepen overlapping behavior before broadening scope."""
    workflow = depth_absorption_plan()
    return [dict(task) for task in workflow.get("employee_tasks") or []]


def marketplace_candidate_queue() -> list[dict[str, Any]]:
    """Expose broad-but-useful external capabilities for AI employee marketplace packaging."""
    workflow = depth_absorption_plan()
    if not workflow.get("marketplace_candidates_enabled", False):
        return []
    return [dict(candidate) for candidate in workflow.get("marketplace_candidates") or []]


def deferred_breadth_queue() -> list[dict[str, Any]]:
    """Record broad capabilities that stay closed until Retort finishes same-direction absorption."""
    workflow = depth_absorption_plan()
    return [dict(candidate) for candidate in workflow.get("deferred_breadth_components") or []]


def ranked_capabilities() -> list[dict[str, Any]]:
    """Rank absorbed signals by behavior depth rather than keyword count."""
    state = ABSORBED_CAPABILITY_STATE
    rows: list[dict[str, Any]] = []
    for signal in state.get("signals") or []:
        evidence = list((state.get("signal_evidence") or {{}}).get(signal) or [])
        gap_hits = sum(1 for gap in state.get("component_gaps") or [] if str(gap.get("component") or "").replace("benchmark_eval", "benchmarking") == signal)
        weight = SIGNAL_WEIGHTS.get(signal, 8) + min(12, len(evidence) * 2) + min(10, gap_hits * 5)
        rows.append({{"signal": signal, "weight": weight, "evidence_files": evidence[:5], "gap_hits": gap_hits}})
    return sorted(rows, key=lambda row: (int(row["weight"]), row["signal"]), reverse=True)


def capability_progress_from_execution(changed_files: list[str], gates: list[dict[str, Any]]) -> dict[str, Any]:
    """Measure whether an absorption changed behavior and proved it with tests."""
    return _capability_progress_from_execution(changed_files, gates)


def explain_missing_absorption_evidence(changed_files: list[str], gates: list[dict[str, Any]]) -> list[str]:
    """Explain why a run should not be allowed to score as real absorption."""
    return _explain_missing_absorption_evidence(changed_files, gates)


def advantage_diff_map(changed_files: list[str]) -> list[dict[str, Any]]:
    """Map external advantages to concrete project-local behavior diffs."""
    return _advantage_diff_map(changed_files, ranked_capabilities())


def absorption_quality_gate(changed_files: list[str], gates: list[dict[str, Any]], *, minimum_behavior_tests: int | None = None) -> dict[str, Any]:
    """Turn weak absorption evidence into a blocking product gate."""
    plan = absorbed_capability_plan()
    minimum = int(minimum_behavior_tests or plan.get("minimum_behavior_tests") or 3)
    return _absorption_quality_gate(
        changed_files,
        gates,
        minimum_behavior_tests=minimum,
        depth_gate=depth_absorption_plan().get("quality_gate") or {{}},
        ranked_capabilities=ranked_capabilities(),
    )


def review_strategy_for_file(path: str) -> dict[str, Any]:
    """Pick a review strategy from absorbed external signals and file shape."""
    suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    capabilities = [item["signal"] for item in ranked_capabilities()]
    strategy = "semantic_review"
    if suffix in {{"ts", "tsx", "js", "jsx", "go", "py"}} and "diff_hunk_review" in capabilities:
        strategy = "diff_hunk_review"
    elif suffix in {{"md", "json", "yml", "yaml"}}:
        strategy = "policy_and_contract_review"
    return {{"path": path, "strategy": strategy, "capabilities": capabilities[:5]}}


def multi_project_reproduction_index(sources: list[str]) -> dict[str, Any]:
    """Score whether the same absorption behavior has been reproduced across projects."""
    unique = sorted({{source for source in sources if source}})
    return {{"unique_source_count": len(unique), "ready_for_product_score": len(unique) >= 3, "sources": unique[:5]}}
'''


def _capability_test_content(import_name: str, source: str) -> str:
    source_text = repr(source)
    return f'''from __future__ import annotations

from {import_name} import absorbed_capability_plan, absorption_quality_gate, advantage_diff_map, capability_progress_from_execution, deferred_breadth_queue, depth_absorption_plan, depth_first_task_queue, explain_missing_absorption_evidence, marketplace_candidate_queue, multi_project_reproduction_index, ranked_capabilities, review_strategy_for_file

EXPECTED_ABSORPTION_SOURCE = {source_text}


def test_absorbed_capability_plan_has_ranked_behavior_signals() -> None:
    plan = absorbed_capability_plan()
    assert plan["run_id"]
    assert plan["source"] == EXPECTED_ABSORPTION_SOURCE
    assert isinstance(plan["tasks"], list)
    assert plan["minimum_behavior_tests"] >= 3
    assert ranked_capabilities()
    assert plan["depth_absorption_plan"]["focus_mode"] == "similar_function_depth_only"


def test_depth_absorption_plan_keeps_depth_before_breadth() -> None:
    workflow = depth_absorption_plan()
    focused_components = {{item["component"] for item in workflow["focused_components"]}}
    assert workflow["quality_gate"]["passed"] is True
    assert focused_components
    assert not (focused_components & {{"provider_surface", "plugin_surface"}})
    assert workflow["breadth_rejected"]
    assert all(task["acceptance"] and task["evidence_required"] for task in depth_first_task_queue())


def test_breadth_candidates_stay_closed_until_similarity_saturation() -> None:
    assert marketplace_candidate_queue() == []
    deferred = deferred_breadth_queue()
    assert deferred
    assert all(item["status"] == "closed_until_similarity_saturation" for item in deferred)
    assert all(item["next_open_condition"] for item in deferred)


def test_capability_progress_requires_behavior_code_tests_and_gates() -> None:
    progress = capability_progress_from_execution(
        ["retort_engine/review_context_bias.py", "tests/test_review_context_bias.py"],
        [{{"ok": True}}, {{"ok": True}}],
    )
    assert progress["ready_for_90"] is True
    assert progress["behavior_source_files"] == ["retort_engine/review_context_bias.py"]
    assert progress["behavior_test_files"] == ["tests/test_review_context_bias.py"]


def test_capability_progress_rejects_registry_only_absorption() -> None:
    progress = capability_progress_from_execution(
        ["retort_engine/absorbed_capabilities.py", "tests/test_absorbed_capabilities.py"],
        [{{"ok": True}}, {{"ok": True}}],
    )

    assert progress["ready_for_90"] is False
    assert progress["behavior_source_files"] == []
    assert progress["behavior_test_files"] == []
    assert progress["generated_evidence_files"] == ["retort_engine/absorbed_capabilities.py", "tests/test_absorbed_capabilities.py"]


def test_missing_absorption_evidence_blocks_report_only_runs() -> None:
    missing = explain_missing_absorption_evidence(["docs/retort_absorption_log.md"], [{{"ok": True}}])
    assert "missing_behavior_source_diff" in missing
    assert "missing_behavior_test_diff" in missing


def test_advantage_diff_map_points_to_behavior_files() -> None:
    rows = advantage_diff_map(["retort_engine/pr_review.py", "tests/test_pr_review.py"])
    assert rows
    assert any(row["has_behavior_diff"] for row in rows)


def test_advantage_diff_map_ignores_registry_files() -> None:
    rows = advantage_diff_map(["retort_engine/absorbed_capabilities.py", "tests/test_absorbed_capabilities.py"])
    assert rows
    assert not any(row["has_behavior_diff"] for row in rows)


def test_absorption_quality_gate_blocks_too_few_behavior_tests() -> None:
    gate = absorption_quality_gate(
        ["retort_engine/review_context_bias.py", "tests/test_review_context_bias.py"],
        [{{"ok": True, "command": ["pytest", "tests/test_review_context_bias.py"], "stdout_tail": "3 passed"}}],
        minimum_behavior_tests=5,
    )
    assert gate["passed"] is False
    assert "insufficient_behavior_test_count" in gate["missing"]


def test_absorption_quality_gate_passes_with_behavior_depth() -> None:
    gate = absorption_quality_gate(
        ["retort_engine/pr_review.py", "tests/test_pr_review.py", "retort_engine/review_context_bias.py", "tests/test_review_context_bias.py"],
        [
            {{"ok": True, "command": ["pytest", "tests/test_pr_review.py"], "stdout_tail": "8 passed"}},
            {{"ok": True, "command": ["pytest", "tests/test_review_context_bias.py"], "stdout_tail": "1 passed"}},
        ],
        minimum_behavior_tests=1,
    )
    assert gate["passed"] is True


def test_review_strategy_for_source_file_uses_absorbed_capabilities() -> None:
    strategy = review_strategy_for_file("src/review.ts")
    assert strategy["strategy"] in {{"diff_hunk_review", "semantic_review"}}
    assert strategy["capabilities"]


def test_multi_project_reproduction_index_requires_three_sources() -> None:
    index = multi_project_reproduction_index(["a", "b", "a", "c"])
    assert index["unique_source_count"] == 3
    assert index["ready_for_product_score"] is True
'''


def _append_log(log_path: Path, run_id: str, source: str, external_path: Path, tasks: list[dict[str, Any]], profile: dict[str, Any]) -> None:
    lines = [
        "",
        f"## {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {run_id}",
        "",
        f"- Source: `{source}`",
        f"- Local path: `{external_path}`",
        f"- External files scanned: `{profile['file_count']}`",
        f"- Absorbed signals: `{', '.join(profile['signals']) or 'none'}`",
        "- Applied tasks:",
    ]
    for task in tasks:
        lines.append(f"  - `{task.get('task_id', '')}` {task.get('title', '')} [{task.get('dimension', '')}]")
    log_path.write_text((_read(log_path) + "\n".join(lines) + "\n").lstrip(), encoding="utf-8")


def _external_profile(root: Path) -> dict[str, Any]:
    files = _project_files(root)
    text_parts: list[str] = []
    suffix_counts: dict[str, int] = {}
    signal_evidence: dict[str, list[str]] = {}
    for path in files[:600]:
        suffix = path.suffix.lower() or "<none>"
        suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1
        if path.suffix.lower() in SOURCE_SUFFIXES:
            text = _read(path)[:20000]
            text_parts.append(text)
            lowered_file = text.lower()
            rel = str(path.relative_to(root))
            for signal, markers in {
                "review_pipeline": ("code review", "review pipeline", "reviewer", "reflection", "localization"),
                "file_grouping": ("file group", "group files", "changed files", "diff hunk", "patch set"),
                "benchmarking": ("benchmark", "precision", "recall", "eval", "evaluation"),
                "plugin_surface": ("plugin", "cli", "github action", "codex"),
                "multi_provider": ("provider", "model", "openai", "anthropic", "ollama"),
                "planet_frontend": ("planet", "spheregeometry", "procedural planet", "terrain", "cloud layer"),
                "atmosphere_shader": ("atmosphere", "fresnel", "rim light", "shader", "cloud"),
                "procedural_surface": ("noise", "texture", "height map", "landmass", "terrain"),
                "webgl_scene": ("webgl", "three.js", "threejs", "renderer", "scene", "camera", "orbit"),
            }.items():
                if any(marker in lowered_file for marker in markers):
                    signal_evidence.setdefault(signal, [])
                    if len(signal_evidence[signal]) < 5:
                        signal_evidence[signal].append(rel)
    lowered = "\n".join(text_parts).lower()
    signal_map = {
        "review_pipeline": ("code review", "review pipeline", "reviewer", "reflection", "localization"),
        "file_grouping": ("file group", "group files", "changed files", "diff hunk", "patch set"),
        "benchmarking": ("benchmark", "precision", "recall", "eval", "evaluation"),
        "plugin_surface": ("plugin", "cli", "github action", "codex"),
        "multi_provider": ("provider", "model", "openai", "anthropic", "ollama"),
        "planet_frontend": ("planet", "spheregeometry", "procedural planet", "terrain", "cloud layer"),
        "atmosphere_shader": ("atmosphere", "fresnel", "rim light", "shader", "cloud"),
        "procedural_surface": ("noise", "texture", "height map", "landmass", "terrain"),
        "webgl_scene": ("webgl", "three.js", "threejs", "renderer", "scene", "camera", "orbit"),
    }
    signals = [name for name, markers in signal_map.items() if any(marker in lowered for marker in markers)]
    return {"file_count": len(files), "suffix_counts": suffix_counts, "signals": signals, "signal_evidence": signal_evidence, "git_revision": _git_revision(root)}


def _semantic_review(own: Path, external: Path) -> dict[str, Any]:
    own_profile = _code_profile(own)
    external_profile = _code_profile(external)
    gaps = []
    for key in sorted(external_profile):
        gap = int(external_profile[key]) - int(own_profile.get(key, 0))
        if gap > 0:
            gaps.append({"metric": key, "external_advantage": gap})
    return {"own": own_profile, "external": external_profile, "gaps": gaps[:12]}


def _code_profile(root: Path) -> dict[str, int]:
    profile = {"source_files": 0, "functions": 0, "classes": 0, "cli_markers": 0, "test_markers": 0, "workflow_markers": 0}
    for path in _project_files(root)[:800]:
        if path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        text = _read(path)
        profile["source_files"] += 1
        profile["functions"] += text.count("def ") + text.count("function ") + text.count("func ")
        profile["classes"] += text.count("class ") + text.count("type ")
        profile["cli_markers"] += text.count("add_parser(") + text.lower().count("cobra.command") + text.lower().count("commander")
        profile["test_markers"] += text.count("def test_") + text.count("it(") + text.count("describe(")
        profile["workflow_markers"] += text.lower().count("workflow") + text.lower().count("pipeline") + text.lower().count("review")
    return profile


def _review_report(root: Path, run_id: str, source: str, external_path: Path, tasks: list[dict[str, Any]], profile: dict[str, Any], semantic_review: dict[str, Any]) -> dict[str, Any]:
    pipeline_report = build_absorption_review_report(root, external_path, tasks)
    return {
        "run_id": run_id,
        "source": source,
        "external_path": str(external_path),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "external_snapshot": {"git_revision": profile.get("git_revision"), "file_count": profile.get("file_count"), "suffix_counts": profile.get("suffix_counts")},
        "license_review": license_gate(external_path, enforce=True).to_dict(),
        "absorbed_signals": profile.get("signals", []),
        "signal_evidence": profile.get("signal_evidence", {}),
        "semantic_review": semantic_review,
        "review_pipeline": pipeline_report,
        "tasks": tasks,
        "replay": {"command": f"retort absorb --own-project <main-project> --external-path {external_path} --run-local-gates --branch-workflow --merge-after"},
    }


def _project_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if set(path.relative_to(root).parts) & SKIP_PARTS:
            continue
        files.append(path)
    return files


def _local_gate_commands(root: Path, payload: dict[str, Any]) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    python = _python(payload)
    if (root / "tests").is_dir():
        commands.append(_run_command([python, "-m", "pytest", "tests", "-q"], root, timeout=int(payload.get("gate_timeout_sec") or 600)))
    return commands


def _run_command(cmd: list[str], cwd: Path, *, timeout: int) -> dict[str, Any]:
    started = time.monotonic()
    try:
        result = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout, check=False)
        return {
            "command": cmd,
            "cwd": str(cwd),
            "exit_code": result.returncode,
            "ok": result.returncode == 0,
            "duration_sec": round(time.monotonic() - started, 3),
            "stdout_tail": result.stdout[-4000:],
            "stderr_tail": result.stderr[-4000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": cmd,
            "cwd": str(cwd),
            "exit_code": 124,
            "ok": False,
            "duration_sec": round(time.monotonic() - started, 3),
            "stdout_tail": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-4000:] if isinstance(exc.stderr, str) else "",
            "timeout": True,
        }


def _snapshot(paths: list[Path]) -> dict[str, bytes | None]:
    return {str(path): path.read_bytes() if path.is_file() else None for path in paths}


def _changed_files(before: dict[str, bytes | None], paths: list[Path]) -> list[str]:
    changed: list[str] = []
    for path in paths:
        current = path.read_bytes() if path.is_file() else None
        if before.get(str(path)) != current:
            changed.append(str(path))
    return changed


def _git_diff_summary(root: Path, changed_files: list[str]) -> list[str]:
    git_root = _git_root(root)
    if git_root is None or not changed_files:
        return []
    rels = [str(Path(path).resolve().relative_to(git_root)) for path in changed_files if Path(path).resolve().is_relative_to(git_root)]
    if not rels:
        return []
    result = subprocess.run(["git", "diff", "--stat", "--", *rels], cwd=git_root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=30, check=False)
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if lines:
        return lines
    fallback = []
    for rel in rels:
        path = git_root / rel
        if path.is_file():
            fallback.append(f"{rel} | {_line_count(path)} lines")
    return fallback


def _employee_diff_text(root: Path, changed_files: list[str]) -> str:
    git_root = _git_root(root)
    rels: list[str] = []
    if git_root is not None:
        for item in changed_files:
            path = Path(item).resolve()
            if path.is_relative_to(git_root):
                rels.append(str(path.relative_to(git_root)))
        if rels:
            result = subprocess.run(["git", "diff", "--", *rels], cwd=git_root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=30, check=False)
            if result.stdout.strip():
                return result.stdout
    return "\n".join(filter(None, (_synthetic_file_diff(root, Path(item)) for item in changed_files)))


def _synthetic_file_diff(root: Path, path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        rel = str(path.resolve().relative_to(root.resolve()))
    except (OSError, ValueError):
        rel = str(path)
    lines = _read(path).splitlines()[:240]
    if not lines:
        return ""
    body = "\n".join(f"+{line}" for line in lines)
    return f"diff --git a/{rel} b/{rel}\n--- /dev/null\n+++ b/{rel}\n@@ -0,0 +1,{len(lines)} @@\n{body}\n"


def _git_root(path: Path) -> Path | None:
    result = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=path, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5, check=False)
    return Path(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else None


def _record_execution(root: Path, result: dict[str, Any]) -> None:
    path = root / ".retort" / "real_absorption_runs" / f"{result.get('run_id', 'run')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_employee_results(root: Path, run_id: str, source: str, tasks: list[dict[str, Any]], result: dict[str, Any], payload: dict[str, Any]) -> Path:
    path = root / ".retort" / "employee_results" / f"{run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    queue_path = str(payload.get("employee_queue") or "")
    history_store = str(payload.get("history_store") or "")
    worker_payload_path = root / ".retort" / "employee_runtime_requests" / f"{run_id}.json"
    worker_payload_path.parent.mkdir(parents=True, exist_ok=True)
    worker_payload = {
        "run_id": run_id,
        "source": source,
        "tasks": tasks,
        "gates_passed": bool(result.get("gates_passed")),
        "changed_files": result.get("changed_files") or [],
        "review_report_path": result.get("review_report_path"),
        "diff_text": _employee_diff_text(root, result.get("changed_files") or []),
        "queue_path": queue_path,
        "history_store": history_store,
        "output_path": str(path),
    }
    worker_payload_path.write_text(json.dumps(worker_payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    package_root = str(Path(__file__).resolve().parents[1])
    worker_code = f"import sys; sys.path.insert(0, {package_root!r}); from retort_engine.employee_runtime_worker import main; raise SystemExit(main())"
    worker = _run_command([_python(payload), "-c", worker_code, "--payload-file", str(worker_payload_path)], root, timeout=120)
    if not path.is_file():
        fallback = {
            "run_id": run_id,
            "source": source,
            "execution_mode": "employee_runtime_worker_failed",
            "runtime_evidence": {"worker": worker, "worker_payload": str(worker_payload_path), "result_path": str(path)},
            "results": [],
        }
        path.write_text(json.dumps(fallback, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _write_execution_queue_records(queue_path: str, run_id: str, source: str, tasks: list[dict[str, Any]]) -> int:
    if not queue_path:
        return 0
    path = Path(queue_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("a", encoding="utf-8") as handle:
        for task in tasks:
            handle.write(json.dumps({"queue_id": str(uuid.uuid4()), "run_id": run_id, "source": source, "status": "executing", "task": task}, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def _execution_result(status: str, root: Path, source: str, started: float, changed_files: list[str], gates: list[dict[str, Any]], diff_summary: list[str], summary: str) -> dict[str, Any]:
    return {
        "status": status,
        "source": source,
        "project": str(root),
        "summary": summary,
        "changed_files": changed_files,
        "commands": [gate["command"] for gate in gates],
        "gates": gates,
        "gates_passed": bool(gates) and all(bool(gate.get("ok")) for gate in gates),
        "git_diff_summary": diff_summary,
        "duration_sec": round(time.monotonic() - started, 3),
        "finished_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _run_id(source: str) -> str:
    digest = hashlib.sha1(source.encode("utf-8", errors="ignore")).hexdigest()[:10]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{stamp}-{digest}"


def _python(payload: dict[str, Any]) -> str:
    return str(payload.get("python") or "python")


def _git_revision(root: Path) -> str:
    git_root = _git_root(root)
    if git_root is None:
        return ""
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=git_root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def _line_count(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
    except OSError:
        return 0


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
