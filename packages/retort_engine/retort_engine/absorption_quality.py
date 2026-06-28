from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any


BEHAVIOR_SOURCE_SUFFIXES = (".py", ".js", ".ts", ".tsx", ".jsx", ".go")
GENERATED_ABSORPTION_NAMES = {
    "absorbed_capabilities.py",
    "absorbed_external_patterns.py",
    "retort_absorbed_patterns.py",
    "test_absorbed_capabilities.py",
    "retort_absorption_log.md",
    "retort_external_review_report.json",
}
SIGNAL_BEHAVIOR_HINTS = {
    "review_pipeline": ("pr_review", "review_pipeline", "employee_runtime_worker", "pr_dry_run", "pr_publish"),
    "file_grouping": ("pr_review", "review_context", "file_grouping", "context_group", "review_context_bias"),
    "diff_hunk_review": ("pr_review", "diff_hunk", "hunk", "review_diff"),
    "benchmarking": ("benchmark", "quality_benchmark", "eval", "precision"),
    "plugin_surface": ("cli", "api", "plugin", "server"),
    "multi_provider": ("provider", "llm", "paibi", "model"),
    "safety_policy": ("license_gate", "safety", "secret", "policy"),
}
FALLBACK_SIGNALS = ("review_pipeline", "file_grouping", "diff_hunk_review", "benchmarking", "plugin_surface", "multi_provider", "safety_policy", "workflow_ci", "benchmark_eval")


def capability_progress_from_execution(changed_files: list[str], gates: list[dict[str, Any]]) -> dict[str, Any]:
    """Measure whether absorption changed runtime behavior and proved it."""
    behavior_source_files = [path for path in changed_files if _is_behavior_source_file(path)]
    behavior_test_files = [path for path in changed_files if _is_behavior_test_file(path)]
    generated_evidence_files = [path for path in changed_files if _is_generated_absorption_file(path)]
    gate_count = len(gates)
    passed_gates = sum(1 for gate in gates if bool(gate.get("ok")))
    ready = bool(behavior_source_files and behavior_test_files and gate_count and passed_gates == gate_count)
    return {
        "behavior_source_files": behavior_source_files,
        "behavior_test_files": behavior_test_files,
        "generated_evidence_files": generated_evidence_files,
        "gate_count": gate_count,
        "passed_gates": passed_gates,
        "ready_for_90": ready,
    }


def explain_missing_absorption_evidence(changed_files: list[str], gates: list[dict[str, Any]]) -> list[str]:
    """Explain why a run cannot be counted as real deep absorption."""
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


def advantage_diff_map(changed_files: list[str], ranked_capabilities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map each external advantage to project-local behavior diffs only."""
    behavior_files = [path for path in changed_files if _is_behavior_source_file(path) or _is_behavior_test_file(path)]
    rows: list[dict[str, Any]] = []
    ranked_signal_names = {str(item.get("signal") or "") for item in ranked_capabilities}
    for capability in ranked_capabilities:
        signal = str(capability.get("signal") or "")
        hints = SIGNAL_BEHAVIOR_HINTS.get(signal, (signal, signal.replace("_", "-")))
        matched = [path for path in behavior_files if _matches_signal(path, signal, hints)]
        rows.append(
            {
                "signal": signal,
                "weight": capability.get("weight", 0),
                "changed_files": matched,
                "has_behavior_diff": bool(matched),
            }
        )
    if not rows:
        ranked_signal_names = set(FALLBACK_SIGNALS)
    for fallback_signal in FALLBACK_SIGNALS:
        if fallback_signal in ranked_signal_names:
            continue
        fallback_hints = SIGNAL_BEHAVIOR_HINTS.get(fallback_signal, (fallback_signal,))
        fallback_matched = sorted(
            {
                path for path in behavior_files if _matches_signal(path, fallback_signal, fallback_hints)
            }
        )
        if fallback_matched:
            rows.append(
                {
                    "signal": fallback_signal,
                    "weight": 0,
                    "changed_files": fallback_matched,
                    "has_behavior_diff": True,
                }
            )
            ranked_signal_names.add(fallback_signal)
    return rows


def absorption_quality_gate(
    changed_files: list[str],
    gates: list[dict[str, Any]],
    *,
    minimum_behavior_tests: int,
    depth_gate: dict[str, Any] | None = None,
    ranked_capabilities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Block report-only absorption even when generated registry tests pass."""
    progress = capability_progress_from_execution(changed_files, gates)
    missing = explain_missing_absorption_evidence(changed_files, gates)
    if depth_gate and not depth_gate.get("passed"):
        missing.append("depth_absorption_gate_failed")
    observed_tests = _observed_behavior_tests(gates, progress["behavior_test_files"])
    if observed_tests < minimum_behavior_tests:
        missing.append("insufficient_behavior_test_count")
    mapped = advantage_diff_map(changed_files, ranked_capabilities or [])
    if mapped and not any(row["has_behavior_diff"] for row in mapped):
        missing.append("missing_advantage_to_behavior_mapping")
    return {
        "passed": not missing,
        "missing": sorted(set(missing)),
        "minimum_behavior_tests": minimum_behavior_tests,
        "observed_behavior_tests": observed_tests,
        "progress": progress,
        "advantage_diff_map": mapped,
    }


def _is_behavior_source_file(path: str) -> bool:
    normalized = _normalize(path)
    name = PurePosixPath(normalized).name
    if name in GENERATED_ABSORPTION_NAMES or "/tests/" in f"/{normalized}":
        return False
    return normalized.endswith(BEHAVIOR_SOURCE_SUFFIXES)


def _is_behavior_test_file(path: str) -> bool:
    normalized = _normalize(path)
    name = PurePosixPath(normalized).name
    if name in GENERATED_ABSORPTION_NAMES:
        return False
    return "/tests/" in f"/{normalized}" or name.startswith("test_")


def _is_generated_absorption_file(path: str) -> bool:
    return PurePosixPath(_normalize(path)).name in GENERATED_ABSORPTION_NAMES


def _matches_signal(path: str, signal: str, hints: tuple[str, ...]) -> bool:
    normalized = _normalize(path).lower()
    compact = normalized.replace("-", "_")
    signal_forms = {signal, signal.replace("_", "-"), signal.replace("_", "")}
    return any(form and form in compact for form in signal_forms) or any(hint and hint in compact for hint in hints)


def _observed_behavior_tests(gates: list[dict[str, Any]], behavior_test_files: list[str]) -> int:
    if not behavior_test_files:
        return 0
    observed = 0
    for gate in gates:
        command_text = " ".join(str(part) for part in gate.get("command") or [])
        if "pytest" not in command_text:
            continue
        if not _gate_covers_behavior_test(command_text, behavior_test_files):
            continue
        stdout = str(gate.get("stdout_tail") or "")
        for value in re.findall(r"\b(\d+)\s+passed\b|\b(\d+)\s+tests?\b", stdout):
            observed = max(observed, max(int(part) for part in value if part))
        for token in stdout.split():
            if token.isdigit():
                observed = max(observed, int(token))
    return observed


def _gate_covers_behavior_test(command_text: str, behavior_test_files: list[str]) -> bool:
    normalized_command = _normalize(command_text)
    if re.search(r"(^|\s)tests($|\s)", normalized_command):
        return True
    return any(_normalize(path) in normalized_command for path in behavior_test_files)


def _normalize(path: str) -> str:
    return str(path).replace("\\", "/")
