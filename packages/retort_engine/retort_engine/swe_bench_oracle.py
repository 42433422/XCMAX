from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any


PASS_VALUES = {"pass", "passed", "ok", "success", "true", "1", True}


def evaluate_issue_patch_case(case: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one SWE-bench-style issue patch prediction."""
    expected_patch = str(case.get("gold_patch") or case.get("expected_patch") or "")
    predicted_patch = str(case.get("predicted_patch") or case.get("patch") or "")
    test_results = {str(key): value for key, value in dict(case.get("test_results") or {}).items()}
    fail_to_pass = [str(item) for item in case.get("fail_to_pass") or []]
    pass_to_pass = [str(item) for item in case.get("pass_to_pass") or []]
    expected_files = touched_files_from_patch(expected_patch)
    predicted_files = touched_files_from_patch(predicted_patch)
    fail_passed = [test for test in fail_to_pass if _passed(test_results.get(test))]
    pass_preserved = [test for test in pass_to_pass if _passed(test_results.get(test))]
    missing_fail_to_pass = sorted(set(fail_to_pass) - set(fail_passed))
    regressed_tests = sorted(set(pass_to_pass) - set(pass_preserved))
    has_patch = bool(predicted_files) and bool(_meaningful_added_lines(predicted_patch))
    overlap = sorted(set(expected_files) & set(predicted_files))
    patch_overlap = len(overlap) / len(expected_files) if expected_files else (1.0 if predicted_files else 0.0)
    resolved = has_patch and not missing_fail_to_pass and not regressed_tests and (not expected_files or bool(overlap))
    return {
        "case_id": str(case.get("instance_id") or case.get("case_id") or ""),
        "repo": str(case.get("repo") or ""),
        "status": _case_status(has_patch, missing_fail_to_pass, regressed_tests, expected_files, overlap),
        "resolved": resolved,
        "has_patch": has_patch,
        "expected_files": expected_files,
        "predicted_files": predicted_files,
        "overlap_files": overlap,
        "patch_overlap": round(patch_overlap, 4),
        "fail_to_pass": {
            "total": len(fail_to_pass),
            "passed": len(fail_passed),
            "missing": missing_fail_to_pass,
        },
        "pass_to_pass": {
            "total": len(pass_to_pass),
            "passed": len(pass_preserved),
            "regressed": regressed_tests,
        },
    }


def build_issue_patch_benchmark(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate SWE-bench-style issue patch outcomes for Retort gates."""
    results = [evaluate_issue_patch_case(case) for case in cases]
    fail_total = sum(int(item["fail_to_pass"]["total"]) for item in results)
    fail_passed = sum(int(item["fail_to_pass"]["passed"]) for item in results)
    pass_total = sum(int(item["pass_to_pass"]["total"]) for item in results)
    pass_passed = sum(int(item["pass_to_pass"]["passed"]) for item in results)
    regression_count = sum(1 for item in results if item["pass_to_pass"]["regressed"])
    resolved_count = sum(1 for item in results if item["resolved"])
    no_patch_count = sum(1 for item in results if item["status"] == "no_patch")
    return {
        "status": "ready" if results and resolved_count == len(results) and regression_count == 0 else "needs_attention",
        "summary": {
            "case_count": len(results),
            "resolved_count": resolved_count,
            "unresolved_count": len(results) - resolved_count,
            "regression_count": regression_count,
            "no_patch_count": no_patch_count,
            "fail_to_pass_pass_rate": round(fail_passed / fail_total, 4) if fail_total else 1.0,
            "pass_to_pass_pass_rate": round(pass_passed / pass_total, 4) if pass_total else 1.0,
            "average_patch_overlap": round(sum(float(item["patch_overlap"]) for item in results) / len(results), 4) if results else 0.0,
        },
        "cases": results,
        "evidence": {
            "style": "swe_bench_issue_patch_oracle",
            "requires_fail_to_pass": True,
            "requires_pass_to_pass_regression_guard": True,
            "requires_patch_file_overlap": True,
        },
    }


def touched_files_from_patch(patch: str) -> list[str]:
    files: list[str] = []
    for line in patch.splitlines():
        match = re.match(r"diff --git a/(.*?) b/(.*)$", line)
        if match:
            path = _clean_path(match.group(2))
            if path and path not in files:
                files.append(path)
            continue
        if line.startswith("+++ b/"):
            path = _clean_path(line.removeprefix("+++ b/"))
            if path and path not in files:
                files.append(path)
    return files


def _case_status(
    has_patch: bool,
    missing_fail_to_pass: list[str],
    regressed_tests: list[str],
    expected_files: list[str],
    overlap: list[str],
) -> str:
    if not has_patch:
        return "no_patch"
    if regressed_tests:
        return "regressed"
    if missing_fail_to_pass:
        return "incomplete"
    if expected_files and not overlap:
        return "off_target_patch"
    return "resolved"


def _clean_path(path: str) -> str:
    normalized = path.strip()
    if normalized == "/dev/null":
        return ""
    return PurePosixPath(normalized).as_posix()


def _meaningful_added_lines(patch: str) -> list[str]:
    return [line for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++") and line[1:].strip()]


def _passed(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in PASS_VALUES
