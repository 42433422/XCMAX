from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from retort_engine.pr_review import review_diff


COMPETITOR_BEHAVIOR_CASES: tuple[dict[str, Any], ...] = (
    {
        "case_id": "mopemope-runtime-output-parser",
        "source_project": "mopemope/pr-ai-review-bot",
        "absorbed_signal": "typescript_patch_output_parsing",
        "expected_context": "runtime",
        "expected_severity": "medium",
        "issue_context": "Compare external output parsing patch behavior.",
        "diff": "diff --git a/src/main.ts b/src/main.ts\n--- a/src/main.ts\n+++ b/src/main.ts\n@@ -2,6 +2,7 @@ import {\n   getInput,\n+  debug,\n   info,\n@@ -79,7 +80,10 @@ export async function run(): Promise<void> {\n+    info(\"done\");\n+    debug(\"error\");\n",
    },
    {
        "case_id": "qodo-security-secret-review",
        "source_project": "qodo-ai/pr-agent",
        "absorbed_signal": "security_ranked_pr_review",
        "expected_context": "security",
        "expected_severity": "high",
        "issue_context": "Secret and credential review should block publishable PR comments.",
        "diff": "diff --git a/pr_agent/settings.py b/pr_agent/settings.py\n--- a/pr_agent/settings.py\n+++ b/pr_agent/settings.py\n@@ -0,0 +1,2 @@\n+OPENAI_API_TOKEN = \"live-secret-value\"\n+debug=True\n",
    },
    {
        "case_id": "reviewdog-ci-token-publisher",
        "source_project": "reviewdog/reviewdog",
        "absorbed_signal": "ci_review_publisher_safety",
        "expected_context": "ci_config",
        "expected_severity": "high",
        "issue_context": "CI review publisher must detect unsafe workflow token usage.",
        "diff": "diff --git a/.github/workflows/review.yml b/.github/workflows/review.yml\n--- a/.github/workflows/review.yml\n+++ b/.github/workflows/review.yml\n@@ -0,0 +1,3 @@\n+env:\n+  REVIEWDOG_TOKEN: \"review-token-value\"\n+  DEBUG: true\n",
    },
)


def build_competitor_behavior_regression(
    project: str | Path,
    *,
    min_cases: int = 3,
    output: str | Path = "",
    cases: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    started = time.monotonic()
    selected = list(cases or COMPETITOR_BEHAVIOR_CASES)
    rows = [_run_case(case) for case in selected]
    ready_rows = [row for row in rows if row["ready"]]
    source_projects = sorted({row["source_project"] for row in rows if row.get("source_project")})
    summary = {
        "case_count": len(rows),
        "min_case_count": min_cases,
        "ready_case_count": len(ready_rows),
        "source_project_count": len(source_projects),
        "source_projects": source_projects,
        "all_cases_direct_review_execution": bool(rows) and all(row["direct_review_execution"] for row in rows),
        "all_competitor_signals_regressed": bool(rows) and len(ready_rows) == len(rows),
        "publishable_case_count": sum(1 for row in rows if row["publishable_comment_count"] > 0),
        "context_matched_case_count": sum(1 for row in rows if row["context_matched"]),
        "severity_matched_case_count": sum(1 for row in rows if row["severity_matched"]),
        "behavior_assertion_count": sum(len(row["assertions"]) for row in rows),
        "duration_sec": round(time.monotonic() - started, 3),
    }
    ready = (
        summary["case_count"] >= min_cases
        and summary["ready_case_count"] >= min_cases
        and summary["source_project_count"] >= min_cases
        and summary["all_cases_direct_review_execution"]
        and summary["all_competitor_signals_regressed"]
    )
    result = {
        "status": "ready" if ready else "needs_competitor_behavior_regression",
        "project": str(root),
        "summary": summary,
        "cases": rows,
        "evidence": {
            "style": "competitor_difference_to_core_behavior_regression",
            "runtime": "retort_engine.pr_review.review_diff",
            "source": "competitor_runtime_comparison_and_blind_adjudication_findings",
            "acceptance": "each_competitor_signal_has_direct_review_diff_behavior_assertions",
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _run_case(case: dict[str, Any]) -> dict[str, Any]:
    review = review_diff(str(case["diff"]), max_comments=8, issue_context=str(case["issue_context"]))
    comments = [item for item in review.get("comments") or [] if isinstance(item, dict)]
    summary = review.get("summary") if isinstance(review.get("summary"), dict) else {}
    extension_policy = summary.get("extension_policy") if isinstance(summary.get("extension_policy"), dict) else {}
    expected_context = str(case["expected_context"])
    expected_severity = str(case["expected_severity"])
    contexts = {str(item.get("review_context") or "") for item in comments if item.get("review_context")}
    contexts.update(str(item) for item in extension_policy.get("review_contexts") or [] if str(item))
    severities = {str(item.get("severity") or "") for item in comments if item.get("severity")}
    publishable_count = sum(1 for item in comments if item.get("publishable"))
    anchors = {(str(item.get("file") or ""), int(item.get("line") or 0)) for item in comments if item.get("file") and item.get("line")}
    assertions = {
        "reviewed": review.get("status") == "reviewed",
        "expected_context_present": expected_context in contexts,
        "expected_severity_present": expected_severity in severities,
        "publishable_comment_present": publishable_count > 0,
        "anchored_comment_present": bool(anchors),
        "direct_review_execution": True,
    }
    return {
        "case_id": str(case["case_id"]),
        "source_project": str(case["source_project"]),
        "absorbed_signal": str(case["absorbed_signal"]),
        "expected_context": expected_context,
        "expected_severity": expected_severity,
        "review_status": str(review.get("status") or ""),
        "comment_count": len(comments),
        "publishable_comment_count": publishable_count,
        "context_matched": assertions["expected_context_present"],
        "severity_matched": assertions["expected_severity_present"],
        "anchor_count": len(anchors),
        "task_group_count": int(summary.get("task_group_count") or 0),
        "direct_review_execution": True,
        "assertions": assertions,
        "ready": all(assertions.values()),
    }
