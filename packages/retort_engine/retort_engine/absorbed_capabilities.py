"""Runtime behavior absorbed from external review tools.

This module is rewritten by `retort apply-absorption` when an external project
contributes implementation signals that should affect Retort behavior. Unlike
the audit report, these functions are executable gates used by product code and
tests to decide whether an absorption actually improved Retort.
"""

from __future__ import annotations

import json
from typing import Any


ABSORBED_CAPABILITY_STATE: dict[str, Any] = json.loads('{\n  "benchmark": {\n    "component_gap_count": 0,\n    "minimum_expected_behavior_tests": 4,\n    "prioritized_component_count": 0,\n    "task_dimension_count": 4\n  },\n  "component_gaps": [],\n  "external_path": "/Users/a4243342/Desktop/XCMAX/packages/retort_engine/.retort/cache/github/villesau/ai-codereviewer",\n  "prioritized_absorptions": [],\n  "run_id": "20260627085837-f05fa6c2b2",\n  "signal_evidence": {\n    "multi_provider": [\n      "README.md",\n      "package.json",\n      "action.yml",\n      ".github/workflows/code_review.yml",\n      "src/main.ts"\n    ],\n    "plugin_surface": [\n      "README.md"\n    ],\n    "review_pipeline": [\n      "README.md",\n      "package.json",\n      "action.yml",\n      ".github/workflows/code_review.yml"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "plugin_surface",\n    "multi_provider"\n  ],\n  "source": "https://github.com/villesau/ai-codereviewer",\n  "tasks": [\n    {\n      "dimension": "comparative_analysis_depth",\n      "priority": "P1",\n      "task_id": "retort-absorb-depth",\n      "title": "Absorb stronger implementation depth",\n      "why": "Compare implementation patterns from https://github.com/villesau/ai-codereviewer."\n    },\n    {\n      "dimension": "product_operability",\n      "priority": "P1",\n      "task_id": "retort-absorb-ux",\n      "title": "Absorb better user experience",\n      "why": "Extract usable UX improvements from https://github.com/villesau/ai-codereviewer."\n    },\n    {\n      "dimension": "operational_readiness",\n      "priority": "P2",\n      "task_id": "retort-absorb-ops",\n      "title": "Absorb better operational gates",\n      "why": "Adapt CI and release checks from https://github.com/villesau/ai-codereviewer."\n    },\n    {\n      "dimension": "comparative_analysis_depth",\n      "priority": "P1",\n      "task_id": "retort-absorb-review-pipeline",\n      "title": "Adopt deterministic review pipeline stages",\n      "why": "External project has explicit review pipeline signals; Retort should turn absorption into staged discovery, localization, reflection, and tasking."\n    },\n    {\n      "dimension": "feedback_loop_closure",\n      "priority": "P2",\n      "task_id": "retort-absorb-benchmarking",\n      "title": "Add absorption quality benchmark counters",\n      "why": "External project has benchmark or precision/recall signals; Retort should measure whether absorbed tasks actually improve later scores."\n    },\n    {\n      "dimension": "product_operability",\n      "priority": "P2",\n      "task_id": "retort-absorb-plugin-surface",\n      "title": "Expose Retort absorption through plugin friendly commands",\n      "why": "External project exposes plugin or CLI surfaces; Retort should keep blackhole UI and automation APIs aligned."\n    }\n  ]\n}')

SIGNAL_WEIGHTS = {
    "review_pipeline": 24,
    "file_grouping": 20,
    "diff_hunk_review": 18,
    "benchmarking": 16,
    "plugin_surface": 12,
    "multi_provider": 10,
}


def absorbed_capability_plan() -> dict[str, Any]:
    """Return the latest executable capability plan from external absorption."""
    state = dict(ABSORBED_CAPABILITY_STATE)
    state["ranked_capabilities"] = ranked_capabilities()
    state["minimum_behavior_tests"] = int((state.get("benchmark") or {}).get("minimum_expected_behavior_tests") or 3)
    return state


def ranked_capabilities() -> list[dict[str, Any]]:
    """Rank absorbed signals by behavior depth rather than keyword count."""
    state = ABSORBED_CAPABILITY_STATE
    rows: list[dict[str, Any]] = []
    for signal in state.get("signals") or []:
        evidence = list((state.get("signal_evidence") or {}).get(signal) or [])
        gap_hits = sum(1 for gap in state.get("component_gaps") or [] if str(gap.get("component") or "").replace("benchmark_eval", "benchmarking") == signal)
        weight = SIGNAL_WEIGHTS.get(signal, 8) + min(12, len(evidence) * 2) + min(10, gap_hits * 5)
        rows.append({"signal": signal, "weight": weight, "evidence_files": evidence[:5], "gap_hits": gap_hits})
    return sorted(rows, key=lambda row: (int(row["weight"]), row["signal"]), reverse=True)


def capability_progress_from_execution(changed_files: list[str], gates: list[dict[str, Any]]) -> dict[str, Any]:
    """Measure whether an absorption changed behavior and proved it with tests."""
    source_files = [path for path in changed_files if path.endswith((".py", ".js", ".ts", ".tsx", ".jsx", ".go")) and "/tests/" not in path and not path.endswith("absorbed_external_patterns.py")]
    test_files = [path for path in changed_files if "/tests/" in path or path.rsplit("/", 1)[-1].startswith("test_")]
    gate_count = len(gates)
    passed_gates = sum(1 for gate in gates if bool(gate.get("ok")))
    ready = bool(source_files and test_files and gate_count and passed_gates == gate_count)
    return {
        "behavior_source_files": source_files,
        "behavior_test_files": test_files,
        "gate_count": gate_count,
        "passed_gates": passed_gates,
        "ready_for_90": ready,
    }


def explain_missing_absorption_evidence(changed_files: list[str], gates: list[dict[str, Any]]) -> list[str]:
    """Explain why a run should not be allowed to score as real absorption."""
    progress = capability_progress_from_execution(changed_files, gates)
    missing: list[str] = []
    if not progress["behavior_source_files"]:
        missing.append("missing_behavior_source_diff")
    if not progress["behavior_test_files"]:
        missing.append("missing_behavior_test_diff")
    if not progress["gate_count"]:
        missing.append("missing_post_absorption_gate")
    elif progress["passed_gates"] != progress["gate_count"]:
        missing.append("post_absorption_gate_failed")
    return missing
