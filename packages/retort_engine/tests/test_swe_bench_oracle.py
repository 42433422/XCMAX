from __future__ import annotations

from retort_engine.swe_bench_oracle import build_issue_patch_benchmark, evaluate_issue_patch_case, touched_files_from_patch


def test_issue_patch_case_resolves_when_fail_to_pass_and_regression_tests_pass() -> None:
    case = {
        "instance_id": "retort__benchmark-1",
        "repo": "retort_engine",
        "gold_patch": _patch("retort_engine/review_quality_benchmark.py", "return {'status': 'ready'}"),
        "predicted_patch": _patch("retort_engine/review_quality_benchmark.py", "return {'status': 'ready'}"),
        "fail_to_pass": ["tests/test_review_quality_benchmark.py::test_quality_gate"],
        "pass_to_pass": ["tests/test_pr_review.py::test_secret_detection"],
        "test_results": {
            "tests/test_review_quality_benchmark.py::test_quality_gate": "passed",
            "tests/test_pr_review.py::test_secret_detection": "passed",
        },
    }

    result = evaluate_issue_patch_case(case)

    assert result["status"] == "resolved"
    assert result["resolved"] is True
    assert result["patch_overlap"] == 1.0
    assert result["fail_to_pass"]["missing"] == []
    assert result["pass_to_pass"]["regressed"] == []


def test_issue_patch_case_blocks_regressions_before_counting_resolution() -> None:
    case = {
        "instance_id": "retort__benchmark-2",
        "repo": "retort_engine",
        "gold_patch": _patch("retort_engine/absorption_quality.py", "return True"),
        "predicted_patch": _patch("retort_engine/absorption_quality.py", "return True"),
        "fail_to_pass": ["tests/test_absorption_quality.py::test_new_oracle"],
        "pass_to_pass": ["tests/test_absorption_quality.py::test_existing_gate"],
        "test_results": {
            "tests/test_absorption_quality.py::test_new_oracle": True,
            "tests/test_absorption_quality.py::test_existing_gate": "failed",
        },
    }

    result = evaluate_issue_patch_case(case)

    assert result["status"] == "regressed"
    assert result["resolved"] is False
    assert result["pass_to_pass"]["regressed"] == ["tests/test_absorption_quality.py::test_existing_gate"]


def test_issue_patch_benchmark_aggregates_resolution_and_overlap() -> None:
    cases = [
        {
            "instance_id": "retort__benchmark-good",
            "repo": "retort_engine",
            "gold_patch": _patch("retort_engine/review_quality_benchmark.py", "ok = True"),
            "predicted_patch": _patch("retort_engine/review_quality_benchmark.py", "ok = True"),
            "fail_to_pass": ["tests/test_review_quality_benchmark.py::test_quality_gate"],
            "pass_to_pass": ["tests/test_pr_review.py::test_secret_detection"],
            "test_results": {
                "tests/test_review_quality_benchmark.py::test_quality_gate": "passed",
                "tests/test_pr_review.py::test_secret_detection": "passed",
            },
        },
        {
            "instance_id": "retort__benchmark-off-target",
            "repo": "retort_engine",
            "gold_patch": _patch("retort_engine/absorption_quality.py", "ok = True"),
            "predicted_patch": _patch("docs/notes.md", "ok = True"),
            "fail_to_pass": ["tests/test_absorption_quality.py::test_quality_gate"],
            "pass_to_pass": ["tests/test_pr_review.py::test_secret_detection"],
            "test_results": {
                "tests/test_absorption_quality.py::test_quality_gate": "passed",
                "tests/test_pr_review.py::test_secret_detection": "passed",
            },
        },
    ]

    report = build_issue_patch_benchmark(cases)

    assert report["status"] == "needs_attention"
    assert report["summary"]["case_count"] == 2
    assert report["summary"]["resolved_count"] == 1
    assert report["summary"]["unresolved_count"] == 1
    assert report["summary"]["fail_to_pass_pass_rate"] == 1.0
    assert report["summary"]["pass_to_pass_pass_rate"] == 1.0
    assert report["summary"]["average_patch_overlap"] == 0.5
    assert report["evidence"]["style"] == "swe_bench_issue_patch_oracle"


def test_touched_files_from_patch_supports_diff_and_plus_plus_plus_headers() -> None:
    patch = "\n".join(
        [
            "diff --git a/old.py b/new.py",
            "--- a/old.py",
            "+++ b/new.py",
            "@@ -1 +1 @@",
            "+print('ok')",
            "+++ b/extra.py",
        ]
    )

    assert touched_files_from_patch(patch) == ["new.py", "extra.py"]


def _patch(path: str, line: str) -> str:
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -0,0 +1 @@\n+{line}\n"
