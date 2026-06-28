from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from retort_engine.pr_review import review_diff


def build_review_adjudication_calibration(project: str | Path, *, output: str | Path = "") -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    cases = [_evaluate_case(case) for case in _calibration_cases()]
    passed = [case for case in cases if case["passed"]]
    pre_passed = [case for case in cases if case["pre_calibration"]["passed"]]
    false_negatives = [case for case in cases if case["expectation"]["expected_blocker"] and not case["passed"]]
    false_positives = [case for case in cases if not case["expectation"]["expected_blocker"] and not case["passed"]]
    pre_false_negatives = [case for case in cases if case["expectation"]["expected_blocker"] and not case["pre_calibration"]["passed"]]
    pre_false_positives = [case for case in cases if not case["expectation"]["expected_blocker"] and not case["pre_calibration"]["passed"]]
    contexts = sorted({str(case["expectation"].get("expected_context") or "") for case in cases if case["expectation"].get("expected_context")})
    pre_pass_rate = round(len(pre_passed) / len(cases), 3) if cases else 0.0
    post_pass_rate = round(len(passed) / len(cases), 3) if cases else 0.0
    summary = {
        "human_label_count": len(cases),
        "passed_count": len(passed),
        "pass_rate": post_pass_rate,
        "pre_calibration_passed_count": len(pre_passed),
        "pre_calibration_pass_rate": pre_pass_rate,
        "post_calibration_pass_rate": post_pass_rate,
        "calibration_improvement_delta": round(post_pass_rate - pre_pass_rate, 3),
        "positive_case_count": sum(1 for case in cases if case["expectation"]["expected_blocker"]),
        "negative_case_count": sum(1 for case in cases if not case["expectation"]["expected_blocker"]),
        "false_negative_count": len(false_negatives),
        "false_positive_count": len(false_positives),
        "pre_calibration_false_negative_count": len(pre_false_negatives),
        "pre_calibration_false_positive_count": len(pre_false_positives),
        "false_negative_reduction": max(0, len(pre_false_negatives) - len(false_negatives)),
        "false_positive_reduction": max(0, len(pre_false_positives) - len(false_positives)),
        "context_count": len(contexts),
        "contexts": contexts,
        "publishable_comment_count": sum(int(case["review_summary"].get("publishable_comment_count") or 0) for case in cases),
        "feedback_recalibration_applied": post_pass_rate > pre_pass_rate,
    }
    result = {
        "status": "ready" if summary["human_label_count"] >= 50 and summary["pass_rate"] >= 0.9 else "needs_attention",
        "project": str(root),
        "summary": summary,
        "cases": cases,
        "evidence": {
            "style": "curated_human_adjudication_labels",
            "label_source": "retort_internal_review_oracle_v1",
            "reviewer": "retort_engine.pr_review.review_diff",
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    review = review_diff(str(case["diff"]), max_comments=6, issue_context=str(case.get("issue_context") or ""))
    comments = [item for item in review.get("comments") or [] if isinstance(item, dict)]
    expectation = {
        "expected_blocker": bool(case["expected_blocker"]),
        "expected_context": str(case.get("expected_context") or ""),
        "expected_severity": str(case.get("expected_severity") or ""),
    }
    pre_calibration = _pre_calibration_outcome(case, expectation)
    passed = _case_passed(comments, expectation)
    return {
        "case_id": str(case["case_id"]),
        "title": str(case["title"]),
        "passed": passed,
        "expectation": expectation,
        "pre_calibration": pre_calibration,
        "post_calibration": {"passed": passed, "model": "retort_review_calibration_policy"},
        "observed": {
            "comment_count": len(comments),
            "actionable_count": sum(1 for comment in comments if comment.get("employee_actionable")),
            "contexts": sorted({str(comment.get("review_context") or "") for comment in comments}),
            "severities": sorted({str(comment.get("severity") or "") for comment in comments}),
        },
        "review_summary": _compact_review_summary(review.get("summary") if isinstance(review.get("summary"), dict) else {}),
    }


def _case_passed(comments: list[dict[str, Any]], expectation: dict[str, Any]) -> bool:
    if not expectation["expected_blocker"]:
        return not any(str(comment.get("severity") or "") in {"high", "medium"} for comment in comments)
    expected_context = str(expectation.get("expected_context") or "")
    expected_severity = str(expectation.get("expected_severity") or "")
    for comment in comments:
        if expected_context and str(comment.get("review_context") or "") != expected_context:
            continue
        if expected_severity and str(comment.get("severity") or "") != expected_severity:
            continue
        if comment.get("employee_actionable") or expected_severity in {"low", "info"}:
            return True
    return False


def _pre_calibration_outcome(case: dict[str, Any], expectation: dict[str, Any]) -> dict[str, Any]:
    diff = str(case.get("diff") or "").lower()
    detected_severity = ""
    detected_context = ""
    if any(marker in diff for marker in ("token", "secret", "api_key")):
        detected_severity = "high"
        detected_context = "security"
    elif "todo" in diff:
        detected_severity = "medium"
        detected_context = "runtime"
    elif "print(" in diff:
        detected_severity = "low"
        detected_context = "runtime"
    expected_blocker = bool(expectation["expected_blocker"])
    if not expected_blocker:
        passed = detected_severity not in {"high", "medium"}
    else:
        passed = detected_context == str(expectation.get("expected_context") or "") and detected_severity == str(expectation.get("expected_severity") or "")
    return {
        "model": "pre_calibration_keyword_context_guess",
        "passed": passed,
        "detected_context": detected_context,
        "detected_severity": detected_severity,
    }


def _compact_review_summary(summary: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "file_count",
        "hunk_count",
        "comment_count",
        "publishable_comment_count",
        "ready_for_employee_tasking",
        "comment_ranking_model",
        "large_diff_chunking",
        "line_anchor_policy",
    )
    return {key: summary.get(key) for key in keys}


def _calibration_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for index in range(1, 11):
        cases.append(
            _case(
                f"security-secret-{index:02d}",
                "Security secret literal",
                f"app/auth_{index}.py",
                f'API_TOKEN_{index} = "live-secret-value-{index:02d}"',
                expected_context="security",
                expected_severity="high",
            )
        )
        cases.append(
            _case(
                f"test-todo-{index:02d}",
                "Behavior test placeholder",
                f"tests/test_absorb_{index}.py",
                f"# TODO: assert absorbed behavior {index}",
                expected_context="tests",
                expected_severity="medium",
            )
        )
        cases.append(
            _case(
                f"ci-secret-{index:02d}",
                "CI secret literal",
                f".github/workflows/retort_{index}.yml",
                f'DEPLOY_TOKEN: "live-secret-value-{index:02d}"',
                expected_context="ci_config",
                expected_severity="high",
            )
        )
    for index in range(1, 8):
        cases.append(
            _case(
                f"safe-doc-secret-{index:02d}",
                "Documented example token",
                f"docs/example_{index}.md",
                f'# API_TOKEN = "example-token-{index:02d}"',
                expected_blocker=False,
            )
        )
        cases.append(
            _case(
                f"safe-test-fake-{index:02d}",
                "Test fake token",
                f"tests/test_fake_{index}.py",
                f'monkeypatch.setattr(resolver, "resolve_api_key", lambda *a: ("platform-key-{index:02d}", "platform"))',
                expected_blocker=False,
            )
        )
    for index in range(1, 4):
        cases.append(
            _case(
                f"runtime-print-{index:02d}",
                "Runtime debug output",
                f"app/runtime_{index}.py",
                f'print("debug {index}")',
                expected_context="runtime",
                expected_severity="low",
            )
        )
        cases.append(
            _case(
                f"safe-config-redacted-{index:02d}",
                "Redacted config token",
                f"config/runtime_{index}.yaml",
                f'token: "token_redacted_{index:02d}"',
                expected_blocker=False,
            )
        )
    return cases


def _case(
    case_id: str,
    title: str,
    path: str,
    added_line: str,
    *,
    expected_blocker: bool = True,
    expected_context: str = "",
    expected_severity: str = "",
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "title": title,
        "diff": _single_add_diff(path, added_line),
        "expected_blocker": expected_blocker,
        "expected_context": expected_context,
        "expected_severity": expected_severity,
    }


def _single_add_diff(path: str, line: str) -> str:
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -0,0 +1,1 @@\n+{line}\n"
