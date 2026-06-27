"""Runtime behavior absorbed from external review tools.

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


ABSORBED_CAPABILITY_STATE: dict[str, Any] = json.loads('{\n  "benchmark": {\n    "component_gap_count": 3,\n    "minimum_expected_behavior_tests": 7,\n    "prioritized_component_count": 3,\n    "task_dimension_count": 4\n  },\n  "component_gaps": [\n    {\n      "component": "provider_surface",\n      "external_files": 12,\n      "file_gap": 0,\n      "marker_gap": 14402,\n      "own_files": 12,\n      "representative_external_files": [\n        "HISTORY.md",\n        "README.md",\n        "benchmark/over_time.py",\n        "benchmark/benchmark.py",\n        "benchmark/problem_stats.py"\n      ]\n    },\n    {\n      "component": "workflow_ci",\n      "external_files": 12,\n      "file_gap": 0,\n      "marker_gap": 10892,\n      "own_files": 12,\n      "representative_external_files": [\n        ".pre-commit-config.yaml",\n        "HISTORY.md",\n        "pyproject.toml",\n        "README.md",\n        "CONTRIBUTING.md"\n      ]\n    },\n    {\n      "component": "benchmark_eval",\n      "external_files": 12,\n      "file_gap": 0,\n      "marker_gap": 960,\n      "own_files": 12,\n      "representative_external_files": [\n        "HISTORY.md",\n        "README.md",\n        "CONTRIBUTING.md",\n        "benchmark/over_time.py",\n        "benchmark/benchmark.py"\n      ]\n    }\n  ],\n  "depth_absorption_workflow": {\n    "deferred_breadth_components": [\n      {\n        "component": "provider_surface",\n        "next_open_condition": "Retort finishes absorbing same-direction projects and core depth gates stay green.",\n        "reason": "early_phase_retort_self_deepening_only",\n        "source_files": [\n          "HISTORY.md",\n          "README.md",\n          "benchmark/over_time.py",\n          "benchmark/benchmark.py",\n          "benchmark/problem_stats.py"\n        ],\n        "status": "closed_until_similarity_saturation"\n      },\n      {\n        "component": "plugin_surface",\n        "next_open_condition": "Retort finishes absorbing same-direction projects and core depth gates stay green.",\n        "reason": "early_phase_retort_self_deepening_only",\n        "source_files": [\n          "HISTORY.md",\n          "CONTRIBUTING.md",\n          "benchmark/benchmark.py",\n          "aider/repomap.py",\n          "aider/utils.py"\n        ],\n        "status": "closed_until_similarity_saturation"\n      }\n    ],\n    "employee_tasks": [\n      {\n        "acceptance": "Retort has executable, tested review_pipeline behavior in the absorption or PR-review path.",\n        "dimension": "comparative_analysis_depth",\n        "evidence_required": [\n          "source diff",\n          "behavior test",\n          "gate output",\n          "review JSON with stages and comments"\n        ],\n        "owner_hint": "fhd-core-maintainer",\n        "priority": "P0",\n        "task_id": "retort-depth-review-pipeline",\n        "title": "Deepen review_pipeline"\n      },\n      {\n        "acceptance": "Retort has executable, tested file_grouping behavior in the absorption or PR-review path.",\n        "dimension": "comparative_analysis_depth",\n        "evidence_required": [\n          "source diff",\n          "behavior test",\n          "gate output"\n        ],\n        "owner_hint": "fhd-core-maintainer",\n        "priority": "P0",\n        "task_id": "retort-depth-file-grouping",\n        "title": "Deepen file_grouping"\n      },\n      {\n        "acceptance": "Retort has executable, tested safety_policy behavior in the absorption or PR-review path.",\n        "dimension": "operational_readiness",\n        "evidence_required": [\n          "source diff",\n          "behavior test",\n          "gate output"\n        ],\n        "owner_hint": "fhd-core-maintainer",\n        "priority": "P1",\n        "task_id": "retort-depth-safety-policy",\n        "title": "Deepen safety_policy"\n      },\n      {\n        "acceptance": "Retort has executable, tested benchmark_eval behavior in the absorption or PR-review path.",\n        "dimension": "feedback_loop_closure",\n        "evidence_required": [\n          "source diff",\n          "behavior test",\n          "gate output",\n          "precision or false-positive benchmark counters"\n        ],\n        "owner_hint": "fhd-core-maintainer",\n        "priority": "P1",\n        "task_id": "retort-depth-benchmark-eval",\n        "title": "Deepen benchmark_eval"\n      },\n      {\n        "acceptance": "Retort has executable, tested workflow_ci behavior in the absorption or PR-review path.",\n        "dimension": "operational_readiness",\n        "evidence_required": [\n          "source diff",\n          "behavior test",\n          "gate output"\n        ],\n        "owner_hint": "fhd-core-maintainer",\n        "priority": "P1",\n        "task_id": "retort-depth-workflow-ci",\n        "title": "Deepen workflow_ci"\n      }\n    ],\n    "focus_mode": "similar_function_depth_only",\n    "focused_components": [\n      {\n        "absorption_goal": "turn external review stages into Retort discovery, localization, reflection, and task dispatch",\n        "acceptance": "Retort has executable, tested review_pipeline behavior in the absorption or PR-review path.",\n        "component": "review_pipeline",\n        "depth_gap": 0,\n        "employee_task": {\n          "acceptance": "Retort has executable, tested review_pipeline behavior in the absorption or PR-review path.",\n          "dimension": "comparative_analysis_depth",\n          "evidence_required": [\n            "source diff",\n            "behavior test",\n            "gate output",\n            "review JSON with stages and comments"\n          ],\n          "owner_hint": "fhd-core-maintainer",\n          "priority": "P0",\n          "task_id": "retort-depth-review-pipeline",\n          "title": "Deepen review_pipeline"\n        },\n        "evidence_required": [\n          "source diff",\n          "behavior test",\n          "gate output",\n          "review JSON with stages and comments"\n        ],\n        "external_marker_hits": 602,\n        "own_marker_hits": 1693,\n        "priority": "P0",\n        "similarity_score": 100,\n        "source_files": [\n          ".pre-commit-config.yaml",\n          "HISTORY.md",\n          "CONTRIBUTING.md",\n          "benchmark/over_time.py",\n          "benchmark/README.md"\n        ]\n      },\n      {\n        "absorption_goal": "group related changed files before expensive reasoning so depth is spent on the same feature area",\n        "acceptance": "Retort has executable, tested file_grouping behavior in the absorption or PR-review path.",\n        "component": "file_grouping",\n        "depth_gap": 0,\n        "employee_task": {\n          "acceptance": "Retort has executable, tested file_grouping behavior in the absorption or PR-review path.",\n          "dimension": "comparative_analysis_depth",\n          "evidence_required": [\n            "source diff",\n            "behavior test",\n            "gate output"\n          ],\n          "owner_hint": "fhd-core-maintainer",\n          "priority": "P0",\n          "task_id": "retort-depth-file-grouping",\n          "title": "Deepen file_grouping"\n        },\n        "evidence_required": [\n          "source diff",\n          "behavior test",\n          "gate output"\n        ],\n        "external_marker_hits": 16,\n        "own_marker_hits": 60,\n        "priority": "P0",\n        "similarity_score": 100,\n        "source_files": [\n          "aider/repo.py",\n          "aider/watch.py",\n          "aider/website/docs/usage.md",\n          "tests/fixtures/chat-history.md"\n        ]\n      },\n      {\n        "absorption_goal": "keep license, secret, permission, and rollback checks in the absorption path",\n        "acceptance": "Retort has executable, tested safety_policy behavior in the absorption or PR-review path.",\n        "component": "safety_policy",\n        "depth_gap": 0,\n        "employee_task": {\n          "acceptance": "Retort has executable, tested safety_policy behavior in the absorption or PR-review path.",\n          "dimension": "operational_readiness",\n          "evidence_required": [\n            "source diff",\n            "behavior test",\n            "gate output"\n          ],\n          "owner_hint": "fhd-core-maintainer",\n          "priority": "P1",\n          "task_id": "retort-depth-safety-policy",\n          "title": "Deepen safety_policy"\n        },\n        "evidence_required": [\n          "source diff",\n          "behavior test",\n          "gate output"\n        ],\n        "external_marker_hits": 198,\n        "own_marker_hits": 320,\n        "priority": "P0",\n        "similarity_score": 100,\n        "source_files": [\n          "HISTORY.md",\n          "pyproject.toml",\n          "CONTRIBUTING.md",\n          "benchmark/benchmark.py",\n          "aider/io.py"\n        ]\n      },\n      {\n        "absorption_goal": "measure whether absorbed review behavior improves precision instead of just increasing comments",\n        "acceptance": "Retort has executable, tested benchmark_eval behavior in the absorption or PR-review path.",\n        "component": "benchmark_eval",\n        "depth_gap": 960,\n        "employee_task": {\n          "acceptance": "Retort has executable, tested benchmark_eval behavior in the absorption or PR-review path.",\n          "dimension": "feedback_loop_closure",\n          "evidence_required": [\n            "source diff",\n            "behavior test",\n            "gate output",\n            "precision or false-positive benchmark counters"\n          ],\n          "owner_hint": "fhd-core-maintainer",\n          "priority": "P1",\n          "task_id": "retort-depth-benchmark-eval",\n          "title": "Deepen benchmark_eval"\n        },\n        "evidence_required": [\n          "source diff",\n          "behavior test",\n          "gate output",\n          "precision or false-positive benchmark counters"\n        ],\n        "external_marker_hits": 1372,\n        "own_marker_hits": 412,\n        "priority": "P0",\n        "similarity_score": 89,\n        "source_files": [\n          "HISTORY.md",\n          "README.md",\n          "CONTRIBUTING.md",\n          "benchmark/over_time.py",\n          "benchmark/benchmark.py"\n        ]\n      },\n      {\n        "absorption_goal": "prove absorption with repeatable local gates and replay commands",\n        "acceptance": "Retort has executable, tested workflow_ci behavior in the absorption or PR-review path.",\n        "component": "workflow_ci",\n        "depth_gap": 10892,\n        "employee_task": {\n          "acceptance": "Retort has executable, tested workflow_ci behavior in the absorption or PR-review path.",\n          "dimension": "operational_readiness",\n          "evidence_required": [\n            "source diff",\n            "behavior test",\n            "gate output"\n          ],\n          "owner_hint": "fhd-core-maintainer",\n          "priority": "P1",\n          "task_id": "retort-depth-workflow-ci",\n          "title": "Deepen workflow_ci"\n        },\n        "evidence_required": [\n          "source diff",\n          "behavior test",\n          "gate output"\n        ],\n        "external_marker_hits": 12990,\n        "own_marker_hits": 2098,\n        "priority": "P0",\n        "similarity_score": 87,\n        "source_files": [\n          ".pre-commit-config.yaml",\n          "HISTORY.md",\n          "pyproject.toml",\n          "README.md",\n          "CONTRIBUTING.md"\n        ]\n      }\n    ],\n    "marketplace_candidates": [],\n    "marketplace_candidates_enabled": false,\n    "quality_gate": {\n      "all_employee_tasks_have_acceptance": true,\n      "deferred_breadth_component_count": 2,\n      "focused_component_count": 5,\n      "kept_breadth_component_count": 0,\n      "marketplace_candidate_count": 0,\n      "marketplace_candidates_enabled": false,\n      "minimum_focused_component_count": 3,\n      "passed": true,\n      "rejected_breadth_component_count": 2\n    },\n    "rejected_breadth_components": [\n      {\n        "component": "provider_surface",\n        "external_marker_hits": 14586,\n        "reason": "breadth_only_for_current_phase",\n        "source_files": [\n          "HISTORY.md",\n          "README.md",\n          "benchmark/over_time.py",\n          "benchmark/benchmark.py",\n          "benchmark/problem_stats.py"\n        ]\n      },\n      {\n        "component": "plugin_surface",\n        "external_marker_hits": 219,\n        "reason": "breadth_only_for_current_phase",\n        "source_files": [\n          "HISTORY.md",\n          "CONTRIBUTING.md",\n          "benchmark/benchmark.py",\n          "aider/repomap.py",\n          "aider/utils.py"\n        ]\n      }\n    ]\n  },\n  "external_path": "/Users/a4243342/.codex/worktrees/retort-live/XCMAX/packages/retort_engine/.retort/cache/github/aider-ai/aider",\n  "prioritized_absorptions": [\n    {\n      "acceptance": "Retort has a tested provider_surface behavior, not only a recorded signal.",\n      "component": "provider_surface",\n      "priority": "P0",\n      "source_files": [\n        "HISTORY.md",\n        "README.md",\n        "benchmark/over_time.py",\n        "benchmark/benchmark.py",\n        "benchmark/problem_stats.py"\n      ]\n    },\n    {\n      "acceptance": "Retort has a tested workflow_ci behavior, not only a recorded signal.",\n      "component": "workflow_ci",\n      "priority": "P0",\n      "source_files": [\n        ".pre-commit-config.yaml",\n        "HISTORY.md",\n        "pyproject.toml",\n        "README.md",\n        "CONTRIBUTING.md"\n      ]\n    },\n    {\n      "acceptance": "Retort has a tested benchmark_eval behavior, not only a recorded signal.",\n      "component": "benchmark_eval",\n      "priority": "P0",\n      "source_files": [\n        "HISTORY.md",\n        "README.md",\n        "CONTRIBUTING.md",\n        "benchmark/over_time.py",\n        "benchmark/benchmark.py"\n      ]\n    }\n  ],\n  "run_id": "20260627171538-da950c021d",\n  "signal_evidence": {\n    "benchmarking": [\n      "HISTORY.md",\n      "README.md",\n      "CONTRIBUTING.md",\n      "benchmark/over_time.py",\n      "benchmark/benchmark.py"\n    ],\n    "multi_provider": [\n      "HISTORY.md",\n      "README.md",\n      "benchmark/over_time.py",\n      "benchmark/benchmark.py",\n      "benchmark/problem_stats.py"\n    ],\n    "plugin_surface": [\n      "HISTORY.md",\n      "README.md",\n      "CONTRIBUTING.md",\n      "aider/io.py",\n      "aider/copypaste.py"\n    ],\n    "review_pipeline": [\n      "aider/gui.py",\n      "aider/coders/base_coder.py",\n      "aider/coders/context_coder.py",\n      "aider/website/_posts/2024-06-02-main-swe-bench.md",\n      "aider/website/_posts/2024-05-22-swe-bench-lite.md"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "benchmarking",\n    "plugin_surface",\n    "multi_provider"\n  ],\n  "source": "https://github.com/aider-ai/aider",\n  "tasks": [\n    {\n      "dimension": "comparative_analysis_depth",\n      "priority": "P1",\n      "task_id": "retort-absorb-depth",\n      "title": "Absorb stronger implementation depth",\n      "why": "Compare implementation patterns from https://github.com/aider-ai/aider."\n    },\n    {\n      "dimension": "product_operability",\n      "priority": "P1",\n      "task_id": "retort-absorb-ux",\n      "title": "Absorb better user experience",\n      "why": "Extract usable UX improvements from https://github.com/aider-ai/aider."\n    },\n    {\n      "dimension": "operational_readiness",\n      "priority": "P2",\n      "task_id": "retort-absorb-ops",\n      "title": "Absorb better operational gates",\n      "why": "Adapt CI and release checks from https://github.com/aider-ai/aider."\n    },\n    {\n      "dimension": "comparative_analysis_depth",\n      "priority": "P1",\n      "task_id": "retort-absorb-review-pipeline",\n      "title": "Adopt deterministic review pipeline stages",\n      "why": "External project has explicit review pipeline signals; Retort should turn absorption into staged discovery, localization, reflection, and tasking."\n    },\n    {\n      "dimension": "feedback_loop_closure",\n      "priority": "P2",\n      "task_id": "retort-absorb-benchmarking",\n      "title": "Add absorption quality benchmark counters",\n      "why": "External project has benchmark or precision/recall signals; Retort should measure whether absorbed tasks actually improve later scores."\n    },\n    {\n      "dimension": "product_operability",\n      "priority": "P2",\n      "task_id": "retort-absorb-plugin-surface",\n      "title": "Expose Retort absorption through plugin friendly commands",\n      "why": "External project exposes plugin or CLI surfaces; Retort should keep blackhole UI and automation APIs aligned."\n    }\n  ]\n}')

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
        depth_gate=depth_absorption_plan().get("quality_gate") or {},
        ranked_capabilities=ranked_capabilities(),
    )


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
