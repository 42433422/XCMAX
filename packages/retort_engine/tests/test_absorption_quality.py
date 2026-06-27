from __future__ import annotations

import pytest

from retort_engine.absorption_quality import absorption_quality_gate, advantage_diff_map, capability_progress_from_execution, explain_missing_absorption_evidence


@pytest.mark.parametrize(
    ("changed_files", "gates", "expected_sources", "expected_tests", "expected_generated", "ready"),
    [
        (
            ["retort_engine/pr_review.py", "tests/test_pr_review.py"],
            [{"ok": True}],
            ["retort_engine/pr_review.py"],
            ["tests/test_pr_review.py"],
            [],
            True,
        ),
        (
            ["packages/retort_engine/retort_engine/review_context_bias.py", "packages/retort_engine/tests/test_review_context_bias.py"],
            [{"ok": True}, {"ok": True}],
            ["packages/retort_engine/retort_engine/review_context_bias.py"],
            ["packages/retort_engine/tests/test_review_context_bias.py"],
            [],
            True,
        ),
        (
            ["retort_engine/absorbed_capabilities.py", "tests/test_absorbed_capabilities.py"],
            [{"ok": True}],
            [],
            [],
            ["retort_engine/absorbed_capabilities.py", "tests/test_absorbed_capabilities.py"],
            False,
        ),
        (
            ["docs/retort_external_review_report.json", "docs/retort_absorption_log.md"],
            [{"ok": True}],
            [],
            [],
            ["docs/retort_external_review_report.json", "docs/retort_absorption_log.md"],
            False,
        ),
        (
            ["retort_engine/pr_review.py", "tests/test_pr_review.py"],
            [{"ok": True}, {"ok": False}],
            ["retort_engine/pr_review.py"],
            ["tests/test_pr_review.py"],
            [],
            False,
        ),
        (
            ["retort_engine/pr_review.py"],
            [{"ok": True}],
            ["retort_engine/pr_review.py"],
            [],
            [],
            False,
        ),
        (
            ["tests/test_pr_review.py"],
            [{"ok": True}],
            [],
            ["tests/test_pr_review.py"],
            [],
            False,
        ),
    ],
)
def test_capability_progress_matrix(
    changed_files: list[str],
    gates: list[dict[str, object]],
    expected_sources: list[str],
    expected_tests: list[str],
    expected_generated: list[str],
    ready: bool,
) -> None:
    progress = capability_progress_from_execution(changed_files, gates)

    assert progress["behavior_source_files"] == expected_sources
    assert progress["behavior_test_files"] == expected_tests
    assert progress["generated_evidence_files"] == expected_generated
    assert progress["gate_count"] == len(gates)
    assert progress["passed_gates"] == sum(1 for gate in gates if gate["ok"])
    assert progress["ready_for_90"] is ready


@pytest.mark.parametrize(
    ("changed_files", "gates", "expected_missing"),
    [
        (
            [],
            [],
            {"missing_behavior_source_diff", "missing_behavior_test_diff", "missing_post_absorption_gate"},
        ),
        (
            ["retort_engine/pr_review.py"],
            [{"ok": True}],
            {"missing_behavior_test_diff"},
        ),
        (
            ["tests/test_pr_review.py"],
            [{"ok": True}],
            {"missing_behavior_source_diff"},
        ),
        (
            ["retort_engine/pr_review.py", "tests/test_pr_review.py"],
            [],
            {"missing_post_absorption_gate"},
        ),
        (
            ["retort_engine/pr_review.py", "tests/test_pr_review.py"],
            [{"ok": True}, {"ok": False}],
            {"post_absorption_gate_failed"},
        ),
        (
            ["docs/retort_external_review_report.json"],
            [{"ok": True}],
            {"missing_behavior_source_diff", "missing_behavior_test_diff"},
        ),
    ],
)
def test_missing_absorption_evidence_matrix(changed_files: list[str], gates: list[dict[str, object]], expected_missing: set[str]) -> None:
    missing = set(explain_missing_absorption_evidence(changed_files, gates))

    assert expected_missing <= missing


def test_advantage_diff_map_matches_each_signal_to_behavior_surface() -> None:
    capabilities = [
        {"signal": "review_pipeline", "weight": 30},
        {"signal": "file_grouping", "weight": 25},
        {"signal": "diff_hunk_review", "weight": 20},
        {"signal": "benchmarking", "weight": 15},
        {"signal": "plugin_surface", "weight": 10},
        {"signal": "multi_provider", "weight": 8},
        {"signal": "safety_policy", "weight": 6},
    ]
    changed_files = [
        "retort_engine/pr_review.py",
        "retort_engine/review_context_bias.py",
        "retort_engine/review_quality_benchmark.py",
        "retort_engine/swe_bench_oracle.py",
        "retort_engine/cli.py",
        "retort_engine/paibi_llm.py",
        "retort_engine/license_gate.py",
        "tests/test_pr_review.py",
        "tests/test_review_context_bias.py",
    ]

    rows = advantage_diff_map(changed_files, capabilities)

    by_signal = {row["signal"]: row for row in rows}
    assert by_signal["review_pipeline"]["has_behavior_diff"] is True
    assert by_signal["file_grouping"]["has_behavior_diff"] is True
    assert by_signal["diff_hunk_review"]["has_behavior_diff"] is True
    assert by_signal["benchmarking"]["has_behavior_diff"] is True
    assert by_signal["plugin_surface"]["has_behavior_diff"] is True
    assert by_signal["multi_provider"]["has_behavior_diff"] is True
    assert by_signal["safety_policy"]["has_behavior_diff"] is True
    assert by_signal["review_pipeline"]["changed_files"] == ["retort_engine/pr_review.py", "tests/test_pr_review.py"]
    assert "retort_engine/review_context_bias.py" in by_signal["file_grouping"]["changed_files"]
    assert "tests/test_review_context_bias.py" in by_signal["file_grouping"]["changed_files"]
    assert by_signal["benchmarking"]["changed_files"] == ["retort_engine/review_quality_benchmark.py", "retort_engine/swe_bench_oracle.py"]


def test_advantage_diff_map_treats_swe_bench_oracle_as_benchmark_eval_behavior() -> None:
    rows = advantage_diff_map(
        ["retort_engine/swe_bench_oracle.py", "tests/test_swe_bench_oracle.py"],
        [{"signal": "benchmark_eval", "weight": 30}],
    )

    assert rows == [
        {
            "signal": "benchmark_eval",
            "weight": 30,
            "changed_files": ["retort_engine/swe_bench_oracle.py", "tests/test_swe_bench_oracle.py"],
            "has_behavior_diff": True,
        }
    ]


def test_advantage_diff_map_ignores_generated_registry_and_reports() -> None:
    rows = advantage_diff_map(
        [
            "retort_engine/absorbed_capabilities.py",
            "tests/test_absorbed_capabilities.py",
            "docs/retort_external_review_report.json",
            ".retort/real_absorption_runs/run.json",
        ],
        [{"signal": "review_pipeline", "weight": 30}],
    )

    assert rows == [{"signal": "review_pipeline", "weight": 30, "changed_files": [], "has_behavior_diff": False}]


@pytest.mark.parametrize(
    ("gates", "expected_observed"),
    [
        (
            [{"ok": True, "command": ["python", "-m", "pytest", "tests/test_pr_review.py", "-q"], "stdout_tail": "12 passed in 0.2s"}],
            12,
        ),
        (
            [{"ok": True, "command": ["pytest", "tests"], "stdout_tail": "134 tests collected\n133 passed"}],
            134,
        ),
        (
            [{"ok": True, "command": ["pytest", "tests/test_pr_review.py"], "stdout_tail": "1 failed, 5 passed"}],
            5,
        ),
        (
            [{"ok": True, "command": ["python", "-c", "print('ok')"], "stdout_tail": "ok"}],
            0,
        ),
    ],
)
def test_absorption_quality_gate_counts_observed_behavior_tests(gates: list[dict[str, object]], expected_observed: int) -> None:
    gate = absorption_quality_gate(
        ["retort_engine/pr_review.py", "tests/test_pr_review.py"],
        gates,
        minimum_behavior_tests=1,
        ranked_capabilities=[{"signal": "review_pipeline", "weight": 30}],
    )

    assert gate["observed_behavior_tests"] == expected_observed


def test_absorption_quality_gate_passes_only_when_all_depth_evidence_exists() -> None:
    gate = absorption_quality_gate(
        ["retort_engine/pr_review.py", "tests/test_pr_review.py"],
        [{"ok": True, "command": ["pytest", "tests/test_pr_review.py"], "stdout_tail": "9 passed"}],
        minimum_behavior_tests=3,
        depth_gate={"passed": True},
        ranked_capabilities=[{"signal": "review_pipeline", "weight": 30}],
    )

    assert gate["passed"] is True
    assert gate["missing"] == []
    assert gate["progress"]["ready_for_90"] is True
    assert gate["advantage_diff_map"][0]["has_behavior_diff"] is True


def test_absorption_quality_gate_fails_when_depth_gate_fails_even_with_tests() -> None:
    gate = absorption_quality_gate(
        ["retort_engine/pr_review.py", "tests/test_pr_review.py"],
        [{"ok": True, "command": ["pytest", "tests/test_pr_review.py"], "stdout_tail": "9 passed"}],
        minimum_behavior_tests=3,
        depth_gate={"passed": False},
        ranked_capabilities=[{"signal": "review_pipeline", "weight": 30}],
    )

    assert gate["passed"] is False
    assert "depth_absorption_gate_failed" in gate["missing"]


def test_absorption_quality_gate_fails_when_ranked_advantage_has_no_matching_behavior_diff() -> None:
    gate = absorption_quality_gate(
        ["retort_engine/review_context_bias.py", "tests/test_review_context_bias.py"],
        [{"ok": True, "command": ["pytest", "tests/test_review_context_bias.py"], "stdout_tail": "3 passed"}],
        minimum_behavior_tests=1,
        ranked_capabilities=[{"signal": "safety_policy", "weight": 30}],
    )

    assert gate["passed"] is False
    assert "missing_advantage_to_behavior_mapping" in gate["missing"]


def test_absorption_quality_gate_fails_closed_for_report_only_with_passing_pytest() -> None:
    gate = absorption_quality_gate(
        ["retort_engine/absorbed_capabilities.py", "tests/test_absorbed_capabilities.py"],
        [{"ok": True, "command": ["pytest", "tests/test_absorbed_capabilities.py"], "stdout_tail": "20 passed"}],
        minimum_behavior_tests=1,
        depth_gate={"passed": True},
        ranked_capabilities=[{"signal": "review_pipeline", "weight": 30}],
    )

    assert gate["passed"] is False
    assert "missing_behavior_source_diff" in gate["missing"]
    assert "missing_behavior_test_diff" in gate["missing"]
    assert "missing_advantage_to_behavior_mapping" in gate["missing"]
