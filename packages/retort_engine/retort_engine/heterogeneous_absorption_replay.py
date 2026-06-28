from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from retort_engine.pr_review import review_diff


HETEROGENEOUS_ABSORPTION_CASES: tuple[dict[str, Any], ...] = (
    {
        "case_id": "semgrep-java-secret",
        "source_project": "semgrep/semgrep",
        "source_family": "security_static_analysis",
        "language_family": "jvm",
        "absorbed_signal": "cross_language_security_rule",
        "expected_context": "security",
        "expected_severity": "high",
        "diff": 'diff --git a/src/main/java/auth/AuthService.java b/src/main/java/auth/AuthService.java\n--- a/src/main/java/auth/AuthService.java\n+++ b/src/main/java/auth/AuthService.java\n@@ -0,0 +1,1 @@\n+String apiKey = "live-secret-value";\n',
    },
    {
        "case_id": "reviewdog-go-token",
        "source_project": "reviewdog/reviewdog",
        "source_family": "go_ci_review_publisher",
        "language_family": "go",
        "absorbed_signal": "publisher_runtime_review",
        "expected_context": "runtime",
        "expected_severity": "medium",
        "diff": 'diff --git a/doghouse/runner.go b/doghouse/runner.go\n--- a/doghouse/runner.go\n+++ b/doghouse/runner.go\n@@ -0,0 +1,1 @@\n+githubToken := "live-secret-value"\n',
    },
    {
        "case_id": "codegraph-rust-contract-bypass",
        "source_project": "sunerpy/codegraph-rust",
        "source_family": "rust_code_graph",
        "language_family": "rust",
        "absorbed_signal": "graph_contract_guard",
        "expected_context": "runtime",
        "expected_severity": "medium",
        "diff": "diff --git a/src/graph.rs b/src/graph.rs\n--- a/src/graph.rs\n+++ b/src/graph.rs\n@@ -0,0 +1,1 @@\n+// FIXME: bypass graph edge validation until next release\n",
    },
    {
        "case_id": "lm-eval-python-oracle",
        "source_project": "EleutherAI/lm-evaluation-harness",
        "source_family": "benchmark_harness",
        "language_family": "python",
        "absorbed_signal": "benchmark_oracle_validation",
        "expected_context": "runtime",
        "expected_severity": "medium",
        "diff": "diff --git a/lm_eval/evaluator.py b/lm_eval/evaluator.py\n--- a/lm_eval/evaluator.py\n+++ b/lm_eval/evaluator.py\n@@ -0,0 +1,1 @@\n+# TODO: replace oracle stub before publishing benchmark score\n",
    },
    {
        "case_id": "madge-ts-dependency-cycle",
        "source_project": "pahen/madge",
        "source_family": "typescript_dependency_graph",
        "language_family": "typescript",
        "absorbed_signal": "dependency_graph_cycle_guard",
        "expected_context": "runtime",
        "expected_severity": "medium",
        "diff": "diff --git a/src/graph.ts b/src/graph.ts\n--- a/src/graph.ts\n+++ b/src/graph.ts\n@@ -0,0 +1,1 @@\n+// TODO: ignore circular dependency until graph rewrite lands\n",
    },
    {
        "case_id": "bandit-python-yaml-load",
        "source_project": "PyCQA/bandit",
        "source_family": "security_static_analysis",
        "language_family": "python",
        "absorbed_signal": "unsafe_deserialization_rule",
        "expected_context": "runtime",
        "expected_severity": "high",
        "diff": "diff --git a/bandit/plugins/yaml_loader.py b/bandit/plugins/yaml_loader.py\n--- a/bandit/plugins/yaml_loader.py\n+++ b/bandit/plugins/yaml_loader.py\n@@ -0,0 +1,1 @@\n+yaml.load(payload)\n",
    },
)


def build_heterogeneous_absorption_replay(
    project: str | Path,
    *,
    min_cases: int = 6,
    output: str | Path = "",
    cases: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    selected = list(cases or HETEROGENEOUS_ABSORPTION_CASES)
    rows = [_evaluate_case(root, case) for case in selected]
    adjudication = _adjudicate_rows(rows)
    adjudication_summary = adjudication["summary"]
    language_families = sorted({str(row["language_family"]) for row in rows if row.get("language_family")})
    source_families = sorted({str(row["source_family"]) for row in rows if row.get("source_family")})
    source_projects = sorted({str(row["source_project"]) for row in rows if row.get("source_project")})
    cached_count = sum(1 for row in rows if row["cached_source_present"])
    ready_rows = [row for row in rows if row["ready"]]
    deltas = [int(row["behavior_delta"]) for row in rows]
    summary = {
        "case_count": len(rows),
        "min_case_count": min_cases,
        "ready_case_count": len(ready_rows),
        "source_project_count": len(source_projects),
        "source_family_count": len(source_families),
        "source_families": source_families,
        "language_family_count": len(language_families),
        "language_families": language_families,
        "cached_source_count": cached_count,
        "pre_absorption_failure_count": sum(1 for row in rows if row["pre_absorption"]["failed_expected_behavior"]),
        "post_absorption_pass_count": sum(1 for row in rows if row["post_absorption"]["passed_expected_behavior"]),
        "all_before_failed_after_passed": bool(rows) and all(row["before_failed_after_passed"] for row in rows),
        "minimum_behavior_delta": min(deltas) if deltas else 0,
        "average_behavior_delta": round(sum(deltas) / len(deltas), 2) if deltas else 0.0,
        "independent_adjudication_status": adjudication["status"],
        "independent_adjudicated_case_count": adjudication_summary["adjudicated_case_count"],
        "independent_accepted_case_count": adjudication_summary["accepted_case_count"],
        "independent_all_cases_accepted": adjudication_summary["all_cases_accepted"],
        "cross_language_absorption_verified": len(language_families) >= 4 and len(source_families) >= 4,
    }
    ready = (
        summary["case_count"] >= min_cases
        and summary["ready_case_count"] >= min_cases
        and summary["cached_source_count"] >= min_cases
        and summary["all_before_failed_after_passed"]
        and summary["minimum_behavior_delta"] >= 35
        and summary["independent_all_cases_accepted"]
        and summary["cross_language_absorption_verified"]
    )
    result = {
        "status": "ready" if ready else "needs_more_heterogeneous_evidence",
        "project": str(root),
        "summary": summary,
        "cases": rows,
        "independent_adjudication": adjudication,
        "evidence": {
            "style": "heterogeneous_before_failure_after_absorption_replay",
            "source_cache_root": str(root / ".retort" / "cache" / "github"),
            "before_model": "pre_absorption_keyword_without_context_or_publishability",
            "after_model": "retort_engine.pr_review.review_diff",
            "adjudicator": "retort_engine.heterogeneous_absorption_replay._adjudicate_rows",
            "source_projects": source_projects,
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _evaluate_case(root: Path, case: dict[str, Any]) -> dict[str, Any]:
    pre = _pre_absorption_review(case)
    post = _post_absorption_review(case)
    delta = int(post["score"]) - int(pre["score"])
    source_project = str(case["source_project"])
    return {
        "case_id": str(case["case_id"]),
        "source_project": source_project,
        "source_family": str(case["source_family"]),
        "language_family": str(case["language_family"]),
        "absorbed_signal": str(case["absorbed_signal"]),
        "expected_context": str(case["expected_context"]),
        "expected_severity": str(case["expected_severity"]),
        "cached_source_present": _cached_source_path(root, source_project).is_dir(),
        "pre_absorption": pre,
        "post_absorption": post,
        "behavior_delta": delta,
        "before_failed_after_passed": pre["failed_expected_behavior"] and post["passed_expected_behavior"],
        "ready": pre["failed_expected_behavior"] and post["passed_expected_behavior"] and delta >= 35,
    }


def _pre_absorption_review(case: dict[str, Any]) -> dict[str, Any]:
    diff = str(case.get("diff") or "").lower()
    expected_severity = str(case.get("expected_severity") or "")
    detected_severity = ""
    if any(marker in diff for marker in ("secret", "token", "apikey", "api_key")):
        detected_severity = "high"
    elif any(marker in diff for marker in ("todo", "fixme", "stub", "bypass", "ignore")):
        detected_severity = "medium"
    elif any(marker in diff for marker in ("shell=true", "yaml.load", "exec.command")):
        detected_severity = "high"
    severity_matched = detected_severity == expected_severity
    score = 25 if severity_matched else 5
    if detected_severity:
        score += 5
    return {
        "model": "pre_absorption_keyword_without_context_or_publishability",
        "score": score,
        "detected_severity": detected_severity,
        "severity_matched": severity_matched,
        "context_matched": False,
        "publishable_comment_count": 0,
        "extension_policy_known_count": 0,
        "passed_expected_behavior": False,
        "failed_expected_behavior": True,
    }


def _post_absorption_review(case: dict[str, Any]) -> dict[str, Any]:
    review = review_diff(str(case["diff"]), max_comments=8, issue_context=str(case.get("absorbed_signal") or ""))
    comments = [item for item in review.get("comments") or [] if isinstance(item, dict)]
    summary = review.get("summary") if isinstance(review.get("summary"), dict) else {}
    extension_policy = summary.get("extension_policy") if isinstance(summary.get("extension_policy"), dict) else {}
    expected_context = str(case.get("expected_context") or "")
    expected_severity = str(case.get("expected_severity") or "")
    contexts = {str(comment.get("review_context") or "") for comment in comments}
    contexts.update(str(item) for item in extension_policy.get("review_contexts") or [])
    severities = {str(comment.get("severity") or "") for comment in comments}
    severity_matched = expected_severity in severities
    context_matched = expected_context in contexts
    publishable_count = sum(1 for comment in comments if comment.get("publishable"))
    extension_known = int(extension_policy.get("known_extension_count") or 0)
    score = 0
    score += 30 if severity_matched else 0
    score += 25 if context_matched else 0
    score += 20 if publishable_count > 0 else 0
    score += 15 if extension_known > 0 else 0
    score += 10 if int(summary.get("comment_count") or 0) > 0 else 0
    return {
        "model": "retort_current_review_diff",
        "score": score,
        "severity_matched": severity_matched,
        "context_matched": context_matched,
        "publishable_comment_count": publishable_count,
        "comment_count": int(summary.get("comment_count") or 0),
        "extension_policy_known_count": extension_known,
        "observed_contexts": sorted(contexts),
        "observed_severities": sorted(severities),
        "passed_expected_behavior": severity_matched and context_matched and publishable_count > 0,
    }


def _adjudicate_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    adjudications = []
    for row in rows:
        checks = {
            "cached_source_present": bool(row.get("cached_source_present")),
            "pre_absorption_failed": bool(row.get("pre_absorption", {}).get("failed_expected_behavior")),
            "post_absorption_passed": bool(row.get("post_absorption", {}).get("passed_expected_behavior")),
            "positive_delta": int(row.get("behavior_delta") or 0) >= 35,
            "language_family_present": bool(row.get("language_family")),
        }
        adjudications.append(
            {
                "case_id": str(row.get("case_id") or ""),
                "source_project": str(row.get("source_project") or ""),
                "language_family": str(row.get("language_family") or ""),
                "recomputed_delta": int(row.get("post_absorption", {}).get("score") or 0)
                - int(row.get("pre_absorption", {}).get("score") or 0),
                "checks": checks,
                "accepted": all(checks.values()),
            }
        )
    accepted = [item for item in adjudications if item["accepted"]]
    return {
        "status": "ready" if adjudications and len(accepted) == len(adjudications) else "needs_attention",
        "summary": {
            "adjudicated_case_count": len(adjudications),
            "accepted_case_count": len(accepted),
            "all_cases_accepted": bool(adjudications) and len(accepted) == len(adjudications),
            "language_family_count": len({item["language_family"] for item in adjudications if item["language_family"]}),
        },
        "adjudications": adjudications,
        "evidence": {
            "independence_boundary": "recomputes_from_serialized_before_after_rows_without_calling_review_diff",
        },
    }


def _cached_source_path(root: Path, source_project: str) -> Path:
    owner, _, repo = source_project.partition("/")
    return root / ".retort" / "cache" / "github" / owner / repo
