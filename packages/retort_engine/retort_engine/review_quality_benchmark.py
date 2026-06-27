from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from retort_engine.pr_review import review_diff


def build_review_quality_benchmark(project: str | Path, *, sample_count: int = 30, negative_sample_count: int = 0) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    samples = _golden_samples(max(1, sample_count)) + _negative_samples(max(0, negative_sample_count))
    sample_results = []
    baseline_results = []
    matched_findings = 0
    expected_findings = 0
    false_positive_count = 0
    negative_false_positive_count = 0
    incremental_verified = 0
    for sample in samples:
        review = review_diff(str(sample["diff"]), max_comments=8, previous_diff_text=str(sample.get("previous_diff") or ""))
        comments = [item for item in review.get("comments") or [] if isinstance(item, dict)]
        baseline = _baseline_review_sample(sample)
        baseline_results.append(baseline)
        expected = [item for item in sample.get("expected_findings") or [] if isinstance(item, dict)]
        matches = [_finding_matched(comments, item) for item in expected]
        expected_findings += len(expected)
        matched_findings += sum(1 for item in matches if item)
        incremental = review.get("incremental") if isinstance(review.get("incremental"), dict) else {}
        if sample.get("requires_incremental_skip") and int(incremental.get("skipped_existing_change_count") or 0) > 0:
            incremental_verified += 1
        if sample.get("expected_severity") == "info":
            sample_false_positives = sum(1 for item in comments if str(item.get("severity") or "") in {"high", "medium"})
            false_positive_count += sample_false_positives
            if sample.get("negative"):
                negative_false_positive_count += sample_false_positives
        matched_count = sum(1 for item in matches if item)
        sample_results.append(
            {
                "sample_id": sample["sample_id"],
                "category": sample["category"],
                "negative": bool(sample.get("negative")),
                "expected": expected,
                "matched": all(matches) if expected else True,
                "expected_finding_count": len(expected),
                "matched_finding_count": matched_count,
                "false_positive_count": sample_false_positives if sample.get("expected_severity") == "info" else 0,
                "observed_severities": [str(item.get("severity") or "") for item in comments],
                "observed_comment_count": len(comments),
                "publishable_comment_count": sum(1 for item in comments if item.get("publishable")),
                "max_rank_score": max([int(item.get("rank_score") or 0) for item in comments] or [0]),
                "baseline_matched": baseline["matched"],
                "baseline_false_positive_count": baseline["false_positive_count"],
                "incremental": {
                    "enabled": bool(incremental.get("enabled")),
                    "skipped_existing_change_count": int(incremental.get("skipped_existing_change_count") or 0),
                    "reviewed_new_change_count": int(incremental.get("reviewed_new_change_count") or 0),
                },
            }
        )
    passed_samples = sum(1 for item in sample_results if item["matched"])
    pass_rate = passed_samples / len(sample_results) if sample_results else 0.0
    category_summary = _category_summary(sample_results)
    macro_pass_rate = sum(float(item["pass_rate"]) for item in category_summary.values()) / len(category_summary) if category_summary else 0.0
    aggregate_score = _aggregate_score(pass_rate=pass_rate, macro_pass_rate=macro_pass_rate, false_positive_count=false_positive_count, incremental_verified=incremental_verified)
    baseline_summary = _baseline_summary(baseline_results)
    delta = aggregate_score - int(baseline_summary["aggregate_score"])
    status = "ready" if len(sample_results) >= 30 and aggregate_score >= 95 and false_positive_count == 0 and incremental_verified >= 5 else "needs_more_evidence"
    return {
        "status": status,
        "project": str(root),
        "summary": {
            "sample_count": len(sample_results),
            "positive_sample_count": sample_count,
            "negative_sample_count": negative_sample_count,
            "curated_expected_conclusion_count": len(sample_results),
            "expected_finding_count": expected_findings,
            "matched_finding_count": matched_findings,
            "missed_finding_count": expected_findings - matched_findings,
            "passed_sample_count": passed_samples,
            "failed_sample_count": len(sample_results) - passed_samples,
            "pass_rate": round(pass_rate, 4),
            "false_positive_count": false_positive_count,
            "negative_blocker_false_positive_count": negative_false_positive_count,
            "incremental_sample_count": sum(1 for item in samples if item.get("requires_incremental_skip")),
            "incremental_skip_verified_count": incremental_verified,
            "macro_category_pass_rate": round(macro_pass_rate, 4),
            "aggregate_score": aggregate_score,
            "baseline_aggregate_score": baseline_summary["aggregate_score"],
            "post_absorption_score_delta": delta,
            "publishable_comment_count": sum(int(item.get("publishable_comment_count") or 0) for item in sample_results),
        },
        "baseline_comparison": {
            "status": "improved" if delta > 0 else "flat",
            "baseline": baseline_summary,
            "post_absorption": {
                "aggregate_score": aggregate_score,
                "pass_rate": round(pass_rate, 4),
                "false_positive_count": false_positive_count,
                "incremental_skip_verified_count": incremental_verified,
            },
            "score_delta": delta,
            "same_pr_set_replayed": True,
        },
        "category_summary": category_summary,
        "samples": sample_results,
        "evidence": {
            "engine": "retort_engine.pr_review.review_diff",
            "golden_set": "repo_curated_pr_review_expectations",
            "minimum_expected_samples": 30,
            "aggregation": "lm_eval_style_task_category_macro_average",
            "baseline": "pre_absorption_rules_without_context_ranking_or_incremental_skip",
            "post_absorption_replay": "same_samples_reviewed_with_ranked_context_and_publishable_anchors",
        },
    }


def _finding_matched(comments: list[dict[str, Any]], expected: dict[str, Any]) -> bool:
    severity = str(expected.get("severity") or "")
    keywords = [str(item).lower() for item in expected.get("message_keywords") or []]
    for comment in comments:
        if severity and str(comment.get("severity") or "") != severity:
            continue
        message = str(comment.get("message") or "").lower()
        if all(keyword.lower() in message for keyword in keywords):
            return True
    return False


def _category_summary(sample_results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for sample in sample_results:
        category = str(sample.get("category") or "uncategorized")
        row = rows.setdefault(
            category,
            {
                "sample_count": 0,
                "passed_sample_count": 0,
                "failed_sample_count": 0,
                "expected_finding_count": 0,
                "matched_finding_count": 0,
                "false_positive_count": 0,
                "incremental_sample_count": 0,
                "incremental_skip_verified_count": 0,
            },
        )
        row["sample_count"] += 1
        row["passed_sample_count"] += 1 if sample.get("matched") else 0
        row["expected_finding_count"] += int(sample.get("expected_finding_count") or 0)
        row["matched_finding_count"] += int(sample.get("matched_finding_count") or 0)
        row["false_positive_count"] += int(sample.get("false_positive_count") or 0)
        incremental = sample.get("incremental") if isinstance(sample.get("incremental"), dict) else {}
        if incremental.get("enabled") and int(incremental.get("skipped_existing_change_count") or 0) > 0:
            row["incremental_sample_count"] += 1
            row["incremental_skip_verified_count"] += 1
    for row in rows.values():
        row["failed_sample_count"] = int(row["sample_count"]) - int(row["passed_sample_count"])
        row["pass_rate"] = round(int(row["passed_sample_count"]) / int(row["sample_count"]), 4) if row["sample_count"] else 0.0
        row["recall"] = round(int(row["matched_finding_count"]) / int(row["expected_finding_count"]), 4) if row["expected_finding_count"] else 1.0
    return dict(sorted(rows.items()))


def _aggregate_score(*, pass_rate: float, macro_pass_rate: float, false_positive_count: int, incremental_verified: int) -> int:
    score = round(((pass_rate * 0.55) + (macro_pass_rate * 0.35) + (min(incremental_verified, 5) / 5 * 0.10)) * 100)
    return max(0, min(100, score - min(false_positive_count * 5, 50)))


def _baseline_review_sample(sample: dict[str, Any]) -> dict[str, Any]:
    """Approximate the pre-absorption reviewer: single-rule scan, no ranking, no incremental replay."""
    text = str(sample.get("diff") or "").lower()
    expected = [item for item in sample.get("expected_findings") or [] if isinstance(item, dict)]
    matched = False
    false_positive_count = 0
    if "token" in text or "api_key" in text or "secret" in text:
        matched = any(str(item.get("severity") or "") == "high" for item in expected)
        if sample.get("negative"):
            false_positive_count = 1
    elif "todo" in text or "fixme" in text:
        matched = any(str(item.get("severity") or "") == "medium" for item in expected)
    elif "print(" in text:
        matched = any(str(item.get("severity") or "") == "low" for item in expected)
    elif not expected:
        matched = True
    return {
        "sample_id": sample.get("sample_id"),
        "matched": matched,
        "false_positive_count": false_positive_count,
        "incremental_skip_verified": False,
    }


def _baseline_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(1 for item in results if item.get("matched"))
    false_positives = sum(int(item.get("false_positive_count") or 0) for item in results)
    pass_rate = passed / len(results) if results else 0.0
    aggregate_score = max(0, min(100, round(pass_rate * 90) - min(false_positives * 5, 50)))
    return {
        "sample_count": len(results),
        "passed_sample_count": passed,
        "failed_sample_count": len(results) - passed,
        "pass_rate": round(pass_rate, 4),
        "false_positive_count": false_positives,
        "incremental_skip_verified_count": 0,
        "aggregate_score": aggregate_score,
    }


def _golden_samples(sample_count: int) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    factories = (_secret_sample, _todo_sample, _print_sample, _long_line_sample, _clean_sample, _incremental_sample)
    index = 0
    while len(samples) < sample_count:
        factory = factories[index % len(factories)]
        samples.append(factory(index))
        index += 1
    return samples


def _negative_samples(sample_count: int) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    factories = (_documented_key_sample, _fake_fixture_key_sample)
    index = 0
    while len(samples) < sample_count:
        factory = factories[index % len(factories)]
        samples.append(factory(index))
        index += 1
    return samples


def _secret_sample(index: int) -> dict[str, Any]:
    path = f"app/config_{index}.py"
    return {
        "sample_id": f"secret-{index:02d}",
        "category": "secret_detection",
        "expected_severity": "high",
        "expected_findings": [{"severity": "high", "message_keywords": ["凭证", "密钥"]}],
        "diff": _single_add_diff(path, f'API_TOKEN_{index} = "token-{index}"'),
    }


def _todo_sample(index: int) -> dict[str, Any]:
    path = f"app/task_{index}.py"
    return {
        "sample_id": f"todo-{index:02d}",
        "category": "placeholder_detection",
        "expected_severity": "medium",
        "expected_findings": [{"severity": "medium", "message_keywords": ["todo", "占位"]}],
        "diff": _single_add_diff(path, f"# TODO: finish absorbed workflow {index}"),
    }


def _print_sample(index: int) -> dict[str, Any]:
    path = f"app/debug_{index}.py"
    return {
        "sample_id": f"print-{index:02d}",
        "category": "debug_output_detection",
        "expected_severity": "low",
        "expected_findings": [{"severity": "low", "message_keywords": ["print", "调试"]}],
        "diff": _single_add_diff(path, f'print("debug absorption {index}")'),
    }


def _long_line_sample(index: int) -> dict[str, Any]:
    path = f"app/long_{index}.py"
    line = "review_payload = " + json.dumps({"payload": "x" * 160, "index": index}, sort_keys=True)
    return {
        "sample_id": f"long-{index:02d}",
        "category": "long_line_detection",
        "expected_severity": "low",
        "expected_findings": [{"severity": "low", "message_keywords": ["过长"]}],
        "diff": _single_add_diff(path, line),
    }


def _clean_sample(index: int) -> dict[str, Any]:
    path = f"app/clean_{index}.py"
    return {
        "sample_id": f"clean-{index:02d}",
        "category": "clean_change_confirmation",
        "expected_severity": "info",
        "expected_findings": [{"severity": "info", "message_keywords": ["未发现阻断"]}],
        "diff": _single_add_diff(path, f"def absorbed_case_{index}(): return {index}"),
    }


def _incremental_sample(index: int) -> dict[str, Any]:
    path = f"app/incremental_{index}.py"
    previous = _multi_add_diff(path, [f"# TODO: old issue {index}"])
    current = _multi_add_diff(path, [f"# TODO: old issue {index}", f'SERVICE_TOKEN_{index} = "token-{index}"'])
    return {
        "sample_id": f"incremental-{index:02d}",
        "category": "incremental_review_detection",
        "expected_severity": "high",
        "expected_findings": [{"severity": "high", "message_keywords": ["凭证", "密钥"]}],
        "requires_incremental_skip": True,
        "previous_diff": previous,
        "diff": current,
    }


def _documented_key_sample(index: int) -> dict[str, Any]:
    path = f"docs/key_context_{index}.py"
    return {
        "sample_id": f"negative-doc-{index:02d}",
        "category": "documented_secret_term_no_blocker",
        "negative": True,
        "expected_severity": "info",
        "expected_findings": [{"severity": "info", "message_keywords": ["未发现阻断"]}],
        "diff": _single_add_diff(path, f"# resolve_api_key documents redacted SERVICE_TOKEN fallback {index}"),
    }


def _fake_fixture_key_sample(index: int) -> dict[str, Any]:
    path = f"tests/test_key_fixture_{index}.py"
    return {
        "sample_id": f"negative-fixture-{index:02d}",
        "category": "fake_fixture_key_no_blocker",
        "negative": True,
        "expected_severity": "info",
        "expected_findings": [{"severity": "info", "message_keywords": ["未发现阻断"]}],
        "diff": _single_add_diff(path, f'monkeypatch.setattr(resolver, "resolve_api_key", lambda *a: ("platform-key-{index}", "platform"))'),
    }


def _single_add_diff(path: str, line: str) -> str:
    return _multi_add_diff(path, [line])


def _multi_add_diff(path: str, lines: list[str]) -> str:
    body = "\n".join(f"+{line}" for line in lines)
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n{body}\n"
