"""Runtime behavior absorbed from external review tools.

This module is rewritten by `retort apply-absorption` when an external project
contributes implementation signals that should affect Retort behavior. Unlike
the audit report, these functions are executable gates used by product code and
tests to decide whether an absorption actually improved Retort.
"""

from __future__ import annotations

import json
from typing import Any


ABSORBED_CAPABILITY_STATE: dict[str, Any] = json.loads('{\n  "benchmark": {\n    "component_gap_count": 1,\n    "minimum_expected_behavior_tests": 6,\n    "prioritized_component_count": 1,\n    "task_dimension_count": 5\n  },\n  "component_gaps": [\n    {\n      "component": "provider_surface",\n      "external_files": 12,\n      "file_gap": 0,\n      "marker_gap": 485,\n      "own_files": 12,\n      "representative_external_files": [\n        "README.it.md",\n        "review.py",\n        "README.md",\n        "SECURITY.it.md",\n        "SECURITY.md"\n      ]\n    }\n  ],\n  "depth_absorption_workflow": {\n    "deferred_breadth_components": [\n      {\n        "component": "provider_surface",\n        "next_open_condition": "Retort finishes absorbing same-direction projects and core depth gates stay green.",\n        "reason": "early_phase_retort_self_deepening_only",\n        "source_files": [\n          "README.it.md",\n          "review.py",\n          "README.md",\n          "SECURITY.it.md",\n          "SECURITY.md"\n        ],\n        "status": "closed_until_similarity_saturation"\n      },\n      {\n        "component": "plugin_surface",\n        "next_open_condition": "Retort finishes absorbing same-direction projects and core depth gates stay green.",\n        "reason": "early_phase_retort_self_deepening_only",\n        "source_files": [\n          "README.it.md",\n          "pyproject.toml",\n          "review.py",\n          "README.md",\n          "docs/ARCHITECTURE.md"\n        ],\n        "status": "closed_until_similarity_saturation"\n      }\n    ],\n    "employee_tasks": [\n      {\n        "acceptance": "Retort has executable, tested review_pipeline behavior in the absorption or PR-review path.",\n        "dimension": "comparative_analysis_depth",\n        "evidence_required": [\n          "source diff",\n          "behavior test",\n          "gate output",\n          "review JSON with stages and comments"\n        ],\n        "owner_hint": "fhd-core-maintainer",\n        "priority": "P0",\n        "task_id": "retort-depth-review-pipeline",\n        "title": "Deepen review_pipeline"\n      },\n      {\n        "acceptance": "Retort has executable, tested file_grouping behavior in the absorption or PR-review path.",\n        "dimension": "comparative_analysis_depth",\n        "evidence_required": [\n          "source diff",\n          "behavior test",\n          "gate output"\n        ],\n        "owner_hint": "fhd-core-maintainer",\n        "priority": "P0",\n        "task_id": "retort-depth-file-grouping",\n        "title": "Deepen file_grouping"\n      },\n      {\n        "acceptance": "Retort has executable, tested benchmark_eval behavior in the absorption or PR-review path.",\n        "dimension": "feedback_loop_closure",\n        "evidence_required": [\n          "source diff",\n          "behavior test",\n          "gate output",\n          "precision or false-positive benchmark counters"\n        ],\n        "owner_hint": "fhd-core-maintainer",\n        "priority": "P1",\n        "task_id": "retort-depth-benchmark-eval",\n        "title": "Deepen benchmark_eval"\n      },\n      {\n        "acceptance": "Retort has executable, tested safety_policy behavior in the absorption or PR-review path.",\n        "dimension": "operational_readiness",\n        "evidence_required": [\n          "source diff",\n          "behavior test",\n          "gate output"\n        ],\n        "owner_hint": "fhd-core-maintainer",\n        "priority": "P1",\n        "task_id": "retort-depth-safety-policy",\n        "title": "Deepen safety_policy"\n      },\n      {\n        "acceptance": "Retort has executable, tested workflow_ci behavior in the absorption or PR-review path.",\n        "dimension": "operational_readiness",\n        "evidence_required": [\n          "source diff",\n          "behavior test",\n          "gate output"\n        ],\n        "owner_hint": "fhd-core-maintainer",\n        "priority": "P1",\n        "task_id": "retort-depth-workflow-ci",\n        "title": "Deepen workflow_ci"\n      }\n    ],\n    "focus_mode": "similar_function_depth_only",\n    "focused_components": [\n      {\n        "absorption_goal": "turn external review stages into Retort discovery, localization, reflection, and task dispatch",\n        "acceptance": "Retort has executable, tested review_pipeline behavior in the absorption or PR-review path.",\n        "component": "review_pipeline",\n        "depth_gap": 0,\n        "employee_task": {\n          "acceptance": "Retort has executable, tested review_pipeline behavior in the absorption or PR-review path.",\n          "dimension": "comparative_analysis_depth",\n          "evidence_required": [\n            "source diff",\n            "behavior test",\n            "gate output",\n            "review JSON with stages and comments"\n          ],\n          "owner_hint": "fhd-core-maintainer",\n          "priority": "P0",\n          "task_id": "retort-depth-review-pipeline",\n          "title": "Deepen review_pipeline"\n        },\n        "evidence_required": [\n          "source diff",\n          "behavior test",\n          "gate output",\n          "review JSON with stages and comments"\n        ],\n        "external_marker_hits": 303,\n        "own_marker_hits": 1340,\n        "priority": "P0",\n        "similarity_score": 100,\n        "source_files": [\n          "README.it.md",\n          "pyproject.toml",\n          "review.py",\n          "README.md",\n          "SECURITY.it.md"\n        ]\n      },\n      {\n        "absorption_goal": "group related changed files before expensive reasoning so depth is spent on the same feature area",\n        "acceptance": "Retort has executable, tested file_grouping behavior in the absorption or PR-review path.",\n        "component": "file_grouping",\n        "depth_gap": 0,\n        "employee_task": {\n          "acceptance": "Retort has executable, tested file_grouping behavior in the absorption or PR-review path.",\n          "dimension": "comparative_analysis_depth",\n          "evidence_required": [\n            "source diff",\n            "behavior test",\n            "gate output"\n          ],\n          "owner_hint": "fhd-core-maintainer",\n          "priority": "P0",\n          "task_id": "retort-depth-file-grouping",\n          "title": "Deepen file_grouping"\n        },\n        "evidence_required": [\n          "source diff",\n          "behavior test",\n          "gate output"\n        ],\n        "external_marker_hits": 1,\n        "own_marker_hits": 51,\n        "priority": "P0",\n        "similarity_score": 100,\n        "source_files": [\n          "reviewer/prompt.py"\n        ]\n      },\n      {\n        "absorption_goal": "measure whether absorbed review behavior improves precision instead of just increasing comments",\n        "acceptance": "Retort has executable, tested benchmark_eval behavior in the absorption or PR-review path.",\n        "component": "benchmark_eval",\n        "depth_gap": 0,\n        "employee_task": {\n          "acceptance": "Retort has executable, tested benchmark_eval behavior in the absorption or PR-review path.",\n          "dimension": "feedback_loop_closure",\n          "evidence_required": [\n            "source diff",\n            "behavior test",\n            "gate output",\n            "precision or false-positive benchmark counters"\n          ],\n          "owner_hint": "fhd-core-maintainer",\n          "priority": "P1",\n          "task_id": "retort-depth-benchmark-eval",\n          "title": "Deepen benchmark_eval"\n        },\n        "evidence_required": [\n          "source diff",\n          "behavior test",\n          "gate output",\n          "precision or false-positive benchmark counters"\n        ],\n        "external_marker_hits": 1,\n        "own_marker_hits": 341,\n        "priority": "P0",\n        "similarity_score": 100,\n        "source_files": [\n          "README.it.md"\n        ]\n      },\n      {\n        "absorption_goal": "keep license, secret, permission, and rollback checks in the absorption path",\n        "acceptance": "Retort has executable, tested safety_policy behavior in the absorption or PR-review path.",\n        "component": "safety_policy",\n        "depth_gap": 0,\n        "employee_task": {\n          "acceptance": "Retort has executable, tested safety_policy behavior in the absorption or PR-review path.",\n          "dimension": "operational_readiness",\n          "evidence_required": [\n            "source diff",\n            "behavior test",\n            "gate output"\n          ],\n          "owner_hint": "fhd-core-maintainer",\n          "priority": "P1",\n          "task_id": "retort-depth-safety-policy",\n          "title": "Deepen safety_policy"\n        },\n        "evidence_required": [\n          "source diff",\n          "behavior test",\n          "gate output"\n        ],\n        "external_marker_hits": 64,\n        "own_marker_hits": 282,\n        "priority": "P0",\n        "similarity_score": 100,\n        "source_files": [\n          "README.it.md",\n          "pyproject.toml",\n          "README.md",\n          "SECURITY.it.md",\n          "SECURITY.md"\n        ]\n      },\n      {\n        "absorption_goal": "prove absorption with repeatable local gates and replay commands",\n        "acceptance": "Retort has executable, tested workflow_ci behavior in the absorption or PR-review path.",\n        "component": "workflow_ci",\n        "depth_gap": 0,\n        "employee_task": {\n          "acceptance": "Retort has executable, tested workflow_ci behavior in the absorption or PR-review path.",\n          "dimension": "operational_readiness",\n          "evidence_required": [\n            "source diff",\n            "behavior test",\n            "gate output"\n          ],\n          "owner_hint": "fhd-core-maintainer",\n          "priority": "P1",\n          "task_id": "retort-depth-workflow-ci",\n          "title": "Deepen workflow_ci"\n        },\n        "evidence_required": [\n          "source diff",\n          "behavior test",\n          "gate output"\n        ],\n        "external_marker_hits": 477,\n        "own_marker_hits": 1652,\n        "priority": "P0",\n        "similarity_score": 100,\n        "source_files": [\n          "README.it.md",\n          "CHANGELOG.md",\n          "pyproject.toml",\n          "README.md",\n          "SECURITY.it.md"\n        ]\n      }\n    ],\n    "marketplace_candidates": [],\n    "marketplace_candidates_enabled": false,\n    "quality_gate": {\n      "all_employee_tasks_have_acceptance": true,\n      "deferred_breadth_component_count": 2,\n      "focused_component_count": 5,\n      "kept_breadth_component_count": 0,\n      "marketplace_candidate_count": 0,\n      "marketplace_candidates_enabled": false,\n      "minimum_focused_component_count": 3,\n      "passed": true,\n      "rejected_breadth_component_count": 2\n    },\n    "rejected_breadth_components": [\n      {\n        "component": "provider_surface",\n        "external_marker_hits": 635,\n        "reason": "breadth_only_for_current_phase",\n        "source_files": [\n          "README.it.md",\n          "review.py",\n          "README.md",\n          "SECURITY.it.md",\n          "SECURITY.md"\n        ]\n      },\n      {\n        "component": "plugin_surface",\n        "external_marker_hits": 10,\n        "reason": "breadth_only_for_current_phase",\n        "source_files": [\n          "README.it.md",\n          "pyproject.toml",\n          "review.py",\n          "README.md",\n          "docs/ARCHITECTURE.md"\n        ]\n      }\n    ]\n  },\n  "external_path": "/Users/a4243342/.codex/worktrees/retort-live/XCMAX/packages/retort_engine/.retort/cache/github/AndreaBonn/ai-pr-reviewer",\n  "prioritized_absorptions": [\n    {\n      "acceptance": "Retort has a tested provider_surface behavior, not only a recorded signal.",\n      "component": "provider_surface",\n      "priority": "P0",\n      "source_files": [\n        "README.it.md",\n        "review.py",\n        "README.md",\n        "SECURITY.it.md",\n        "SECURITY.md"\n      ]\n    }\n  ],\n  "run_id": "20260627150611-310a494b4a",\n  "signal_evidence": {\n    "benchmarking": [\n      "README.it.md"\n    ],\n    "file_grouping": [\n      "reviewer/prompt.py"\n    ],\n    "multi_provider": [\n      "README.it.md",\n      "review.py",\n      "README.md",\n      "SECURITY.it.md",\n      "SECURITY.md"\n    ],\n    "plugin_surface": [\n      "README.it.md",\n      "pyproject.toml",\n      "review.py",\n      "README.md",\n      "reviewer/github_client.py"\n    ],\n    "review_pipeline": [\n      "README.it.md",\n      "pyproject.toml",\n      "review.py",\n      "README.md",\n      "SECURITY.it.md"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "file_grouping",\n    "benchmarking",\n    "plugin_surface",\n    "multi_provider"\n  ],\n  "source": "https://github.com/AndreaBonn/ai-pr-reviewer",\n  "tasks": [\n    {\n      "dimension": "comparative_analysis_depth",\n      "priority": "P1",\n      "task_id": "retort-absorb-depth",\n      "title": "Absorb stronger implementation depth",\n      "why": "Compare implementation patterns from https://github.com/AndreaBonn/ai-pr-reviewer."\n    },\n    {\n      "dimension": "product_operability",\n      "priority": "P1",\n      "task_id": "retort-absorb-ux",\n      "title": "Absorb better user experience",\n      "why": "Extract usable UX improvements from https://github.com/AndreaBonn/ai-pr-reviewer."\n    },\n    {\n      "dimension": "operational_readiness",\n      "priority": "P2",\n      "task_id": "retort-absorb-ops",\n      "title": "Absorb better operational gates",\n      "why": "Adapt CI and release checks from https://github.com/AndreaBonn/ai-pr-reviewer."\n    },\n    {\n      "dimension": "comparative_analysis_depth",\n      "priority": "P1",\n      "task_id": "retort-absorb-review-pipeline",\n      "title": "Adopt deterministic review pipeline stages",\n      "why": "External project has explicit review pipeline signals; Retort should turn absorption into staged discovery, localization, reflection, and tasking."\n    },\n    {\n      "dimension": "external_ingestion",\n      "priority": "P1",\n      "task_id": "retort-absorb-file-grouping",\n      "title": "Add external file grouping before deep comparison",\n      "why": "External project suggests grouping changed or related files before expensive reasoning, improving depth without broad noisy scans."\n    },\n    {\n      "dimension": "feedback_loop_closure",\n      "priority": "P2",\n      "task_id": "retort-absorb-benchmarking",\n      "title": "Add absorption quality benchmark counters",\n      "why": "External project has benchmark or precision/recall signals; Retort should measure whether absorbed tasks actually improve later scores."\n    },\n    {\n      "dimension": "product_operability",\n      "priority": "P2",\n      "task_id": "retort-absorb-plugin-surface",\n      "title": "Expose Retort absorption through plugin friendly commands",\n      "why": "External project exposes plugin or CLI surfaces; Retort should keep blackhole UI and automation APIs aligned."\n    }\n  ]\n}')

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
    state["depth_absorption_plan"] = depth_absorption_plan()
    state["minimum_behavior_tests"] = int((state.get("benchmark") or {}).get("minimum_expected_behavior_tests") or 3)
    return state


def depth_absorption_plan() -> dict[str, Any]:
    """Return the depth-only plan that decides what Retort should actually absorb."""
    workflow = dict(ABSORBED_CAPABILITY_STATE.get("depth_absorption_workflow") or {})
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


def advantage_diff_map(changed_files: list[str]) -> list[dict[str, Any]]:
    """Map external advantages to concrete project-local behavior diffs."""
    plan = absorbed_capability_plan()
    rows: list[dict[str, Any]] = []
    for capability in plan.get("ranked_capabilities") or []:
        signal = str(capability.get("signal") or "")
        matched = [path for path in changed_files if signal.replace("_", "-") in path or "absorbed_capabilities" in path or "test_absorbed_capabilities" in path]
        rows.append({"signal": signal, "weight": capability.get("weight", 0), "changed_files": matched, "has_behavior_diff": bool(matched)})
    return rows


def absorption_quality_gate(changed_files: list[str], gates: list[dict[str, Any]], *, minimum_behavior_tests: int | None = None) -> dict[str, Any]:
    """Turn weak absorption evidence into a blocking product gate."""
    plan = absorbed_capability_plan()
    minimum = int(minimum_behavior_tests or plan.get("minimum_behavior_tests") or 3)
    missing = explain_missing_absorption_evidence(changed_files, gates)
    depth_gate = (depth_absorption_plan().get("quality_gate") or {})
    if depth_gate and not depth_gate.get("passed"):
        missing.append("depth_absorption_gate_failed")
    test_gate = next((gate for gate in gates if "test_absorbed_capabilities.py" in " ".join(str(part) for part in gate.get("command") or [])), {})
    stdout = str(test_gate.get("stdout_tail") or "")
    passed_count = 0
    for token in stdout.split():
        if token.isdigit():
            passed_count = max(passed_count, int(token))
    if passed_count < minimum:
        missing.append("insufficient_behavior_test_count")
    return {"passed": not missing, "missing": missing, "minimum_behavior_tests": minimum, "observed_behavior_tests": passed_count}


def review_strategy_for_file(path: str) -> dict[str, Any]:
    """Pick a review strategy from absorbed external signals and file shape."""
    suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    capabilities = [item["signal"] for item in ranked_capabilities()]
    strategy = "semantic_review"
    if suffix in {"ts", "tsx", "js", "jsx", "go", "py"} and "diff_hunk_review" in capabilities:
        strategy = "diff_hunk_review"
    elif suffix in {"md", "json", "yml", "yaml"}:
        strategy = "policy_and_contract_review"
    return {"path": path, "strategy": strategy, "capabilities": capabilities[:5]}


def multi_project_reproduction_index(sources: list[str]) -> dict[str, Any]:
    """Score whether the same absorption behavior has been reproduced across projects."""
    unique = sorted({source for source in sources if source})
    return {"unique_source_count": len(unique), "ready_for_product_score": len(unique) >= 3, "sources": unique[:5]}
