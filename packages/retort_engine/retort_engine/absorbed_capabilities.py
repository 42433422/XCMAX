"""Runtime behavior absorbed from external review tools.

This module is rewritten by `retort apply-absorption` when an external project
contributes implementation signals that should affect Retort behavior. Unlike
the audit report, these functions are executable gates used by product code and
tests to decide whether an absorption actually improved Retort.
"""

from __future__ import annotations

import json
from typing import Any


ABSORBED_CAPABILITY_STATE: dict[str, Any] = json.loads('{\n  "benchmark": {\n    "component_gap_count": 6,\n    "minimum_expected_behavior_tests": 11,\n    "prioritized_component_count": 6,\n    "task_dimension_count": 5\n  },\n  "component_gaps": [\n    {\n      "component": "provider_surface",\n      "external_files": 12,\n      "file_gap": 0,\n      "marker_gap": 4206,\n      "own_files": 12,\n      "representative_external_files": [\n        "CHANGELOG.md",\n        "README.md",\n        "RELEASE_NOTES.md",\n        "AGENTS.md",\n        "SECURITY.md"\n      ]\n    },\n    {\n      "component": "workflow_ci",\n      "external_files": 12,\n      "file_gap": 0,\n      "marker_gap": 1836,\n      "own_files": 12,\n      "representative_external_files": [\n        "CODE_OF_CONDUCT.md",\n        "CHANGELOG.md",\n        "pyproject.toml",\n        "README.md",\n        "setup.py"\n      ]\n    },\n    {\n      "component": "review_pipeline",\n      "external_files": 12,\n      "file_gap": 0,\n      "marker_gap": 87,\n      "own_files": 12,\n      "representative_external_files": [\n        "CODE_OF_CONDUCT.md",\n        "action.yaml",\n        "pyproject.toml",\n        "README.md",\n        "CONTRIBUTING.md"\n      ]\n    },\n    {\n      "component": "safety_policy",\n      "external_files": 12,\n      "file_gap": 0,\n      "marker_gap": 38,\n      "own_files": 12,\n      "representative_external_files": [\n        "CODE_OF_CONDUCT.md",\n        "pyproject.toml",\n        "README.md",\n        "AGENTS.md",\n        "SECURITY.md"\n      ]\n    },\n    {\n      "component": "diff_hunk_review",\n      "external_files": 12,\n      "file_gap": 7,\n      "marker_gap": 26,\n      "own_files": 5,\n      "representative_external_files": [\n        "CHANGELOG.md",\n        "pr_agent/settings/pr_custom_labels.toml",\n        "pr_agent/settings/pr_information_from_user_prompts.toml",\n        "pr_agent/settings/pr_reviewer_prompts.toml",\n        "pr_agent/settings/pr_line_questions_prompts.toml"\n      ]\n    },\n    {\n      "component": "plugin_surface",\n      "external_files": 12,\n      "file_gap": 0,\n      "marker_gap": 2,\n      "own_files": 12,\n      "representative_external_files": [\n        "README.md",\n        "RELEASE_NOTES.md",\n        "AGENTS.md",\n        "SECURITY.md",\n        "docker/mosaico/README.md"\n      ]\n    }\n  ],\n  "external_path": "/Users/a4243342/.codex/worktrees/retort-live/XCMAX/packages/retort_engine/.retort/cache/github/The-PR-Agent/pr-agent",\n  "prioritized_absorptions": [\n    {\n      "acceptance": "Retort has a tested provider_surface behavior, not only a recorded signal.",\n      "component": "provider_surface",\n      "priority": "P0",\n      "source_files": [\n        "CHANGELOG.md",\n        "README.md",\n        "RELEASE_NOTES.md",\n        "AGENTS.md",\n        "SECURITY.md"\n      ]\n    },\n    {\n      "acceptance": "Retort has a tested workflow_ci behavior, not only a recorded signal.",\n      "component": "workflow_ci",\n      "priority": "P0",\n      "source_files": [\n        "CODE_OF_CONDUCT.md",\n        "CHANGELOG.md",\n        "pyproject.toml",\n        "README.md",\n        "setup.py"\n      ]\n    },\n    {\n      "acceptance": "Retort has a tested review_pipeline behavior, not only a recorded signal.",\n      "component": "review_pipeline",\n      "priority": "P0",\n      "source_files": [\n        "CODE_OF_CONDUCT.md",\n        "action.yaml",\n        "pyproject.toml",\n        "README.md",\n        "CONTRIBUTING.md"\n      ]\n    },\n    {\n      "acceptance": "Retort has a tested safety_policy behavior, not only a recorded signal.",\n      "component": "safety_policy",\n      "priority": "P0",\n      "source_files": [\n        "CODE_OF_CONDUCT.md",\n        "pyproject.toml",\n        "README.md",\n        "AGENTS.md",\n        "SECURITY.md"\n      ]\n    },\n    {\n      "acceptance": "Retort has a tested diff_hunk_review behavior, not only a recorded signal.",\n      "component": "diff_hunk_review",\n      "priority": "P0",\n      "source_files": [\n        "CHANGELOG.md",\n        "pr_agent/settings/pr_custom_labels.toml",\n        "pr_agent/settings/pr_information_from_user_prompts.toml",\n        "pr_agent/settings/pr_reviewer_prompts.toml",\n        "pr_agent/settings/pr_line_questions_prompts.toml"\n      ]\n    },\n    {\n      "acceptance": "Retort has a tested plugin_surface behavior, not only a recorded signal.",\n      "component": "plugin_surface",\n      "priority": "P1",\n      "source_files": [\n        "README.md",\n        "RELEASE_NOTES.md",\n        "AGENTS.md",\n        "SECURITY.md",\n        "docker/mosaico/README.md"\n      ]\n    }\n  ],\n  "run_id": "20260627144144-dbc443423e",\n  "signal_evidence": {\n    "benchmarking": [\n      "CHANGELOG.md",\n      "pr_agent/settings/pr_evaluate_prompt_response.toml",\n      "pr_agent/settings/code_suggestions/pr_code_suggestions_reflect_prompts.toml",\n      "pr_agent/tools/pr_help_message.py",\n      "pr_agent/algo/token_handler.py"\n    ],\n    "file_grouping": [\n      "pr_agent/settings/pr_reviewer_prompts.toml",\n      "pr_agent/settings/code_suggestions/pr_code_suggestions_prompts_not_decoupled.toml",\n      "pr_agent/git_providers/local_git_provider.py",\n      "pr_agent/git_providers/gerrit_provider.py"\n    ],\n    "multi_provider": [\n      "CHANGELOG.md",\n      "README.md",\n      "RELEASE_NOTES.md",\n      "AGENTS.md",\n      "SECURITY.md"\n    ],\n    "plugin_surface": [\n      "pyproject.toml",\n      "README.md",\n      "RELEASE_NOTES.md",\n      "AGENTS.md",\n      "SECURITY.md"\n    ],\n    "review_pipeline": [\n      "pyproject.toml",\n      "README.md",\n      ".pr_agent.toml",\n      "AGENTS.md",\n      "docker/mosaico/pr-agent-solution-agent.json"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "file_grouping",\n    "benchmarking",\n    "plugin_surface",\n    "multi_provider"\n  ],\n  "source": "https://github.com/The-PR-Agent/pr-agent",\n  "tasks": [\n    {\n      "dimension": "comparative_analysis_depth",\n      "priority": "P1",\n      "task_id": "retort-absorb-depth",\n      "title": "Absorb stronger implementation depth",\n      "why": "Compare implementation patterns from https://github.com/The-PR-Agent/pr-agent."\n    },\n    {\n      "dimension": "product_operability",\n      "priority": "P1",\n      "task_id": "retort-absorb-ux",\n      "title": "Absorb better user experience",\n      "why": "Extract usable UX improvements from https://github.com/The-PR-Agent/pr-agent."\n    },\n    {\n      "dimension": "operational_readiness",\n      "priority": "P2",\n      "task_id": "retort-absorb-ops",\n      "title": "Absorb better operational gates",\n      "why": "Adapt CI and release checks from https://github.com/The-PR-Agent/pr-agent."\n    },\n    {\n      "dimension": "comparative_analysis_depth",\n      "priority": "P1",\n      "task_id": "retort-absorb-review-pipeline",\n      "title": "Adopt deterministic review pipeline stages",\n      "why": "External project has explicit review pipeline signals; Retort should turn absorption into staged discovery, localization, reflection, and tasking."\n    },\n    {\n      "dimension": "external_ingestion",\n      "priority": "P1",\n      "task_id": "retort-absorb-file-grouping",\n      "title": "Add external file grouping before deep comparison",\n      "why": "External project suggests grouping changed or related files before expensive reasoning, improving depth without broad noisy scans."\n    },\n    {\n      "dimension": "feedback_loop_closure",\n      "priority": "P2",\n      "task_id": "retort-absorb-benchmarking",\n      "title": "Add absorption quality benchmark counters",\n      "why": "External project has benchmark or precision/recall signals; Retort should measure whether absorbed tasks actually improve later scores."\n    },\n    {\n      "dimension": "product_operability",\n      "priority": "P2",\n      "task_id": "retort-absorb-plugin-surface",\n      "title": "Expose Retort absorption through plugin friendly commands",\n      "why": "External project exposes plugin or CLI surfaces; Retort should keep blackhole UI and automation APIs aligned."\n    }\n  ]\n}')

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
