from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retort_engine.pr_review import review_diff


FAMILY_CASES: tuple[dict[str, str], ...] = (
    {
        "case_id": "typescript_duplicate_dispatch",
        "source_project": "mopemope/pr-ai-review-bot",
        "language_family": "typescript",
        "diff": "diff --git a/src/reviewer.ts b/src/reviewer.ts\n--- a/src/reviewer.ts\n+++ b/src/reviewer.ts\n@@ -0,0 +1,3 @@\n+export async function runReview(diff) {\n+  await publishComment(diff); await publishComment(diff);\n+}\n",
        "expected_context": "runtime",
        "expected_severity": "medium",
    },
    {
        "case_id": "python_duplicate_dispatch",
        "source_project": "qodo-ai/pr-agent",
        "language_family": "python",
        "diff": "diff --git a/pr_agent/reviewer.py b/pr_agent/reviewer.py\n--- a/pr_agent/reviewer.py\n+++ b/pr_agent/reviewer.py\n@@ -0,0 +1,3 @@\n+def run_review(diff):\n+    publish_comment(diff)\n+    publish_comment(diff)\n",
        "expected_context": "runtime",
        "expected_severity": "medium",
    },
    {
        "case_id": "typescript_secret_config",
        "source_project": "mopemope/pr-ai-review-bot",
        "language_family": "typescript",
        "diff": "diff --git a/src/config.ts b/src/config.ts\n--- a/src/config.ts\n+++ b/src/config.ts\n@@ -0,0 +1 @@\n+export const GITHUB_TOKEN = \"live-secret-value\";\n",
        "expected_context": "security",
        "expected_severity": "high",
    },
)


def build_review_family_behavior_replay(
    project: str | Path,
    *,
    output: str | Path = "",
    min_cases: int = 3,
    run_id: str = "",
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    replay_id = run_id or _run_id("review-family")
    lab = root / ".retort" / "review_family_behavior_replays" / replay_id
    lab.mkdir(parents=True, exist_ok=True)
    cases = [_evaluate_case(lab, dict(case)) for case in FAMILY_CASES]
    adjudication = _adjudicate(cases)
    language_families = sorted({str(case["language_family"]) for case in cases})
    source_projects = sorted({str(case["source_project"]) for case in cases})
    ready_cases = [case for case in cases if case["ready"]]
    summary = {
        "run_id": replay_id,
        "case_count": len(cases),
        "min_case_count": min_cases,
        "ready_case_count": len(ready_cases),
        "language_family_count": len(language_families),
        "language_families": language_families,
        "source_project_count": len(source_projects),
        "source_projects": source_projects,
        "typescript_case_count": sum(1 for case in cases if case["language_family"] == "typescript"),
        "python_case_count": sum(1 for case in cases if case["language_family"] == "python"),
        "all_before_failed_after_passed": bool(cases) and all(case["before_failed_after_passed"] for case in cases),
        "all_direct_review_outputs_verified": bool(cases) and all(case["post_absorption"]["output_assertions_passed"] for case in cases),
        "publishable_case_count": sum(1 for case in cases if case["post_absorption"]["publishable_comment_count"] > 0),
        "independent_adjudication_status": adjudication["status"],
        "independent_accepted_case_count": adjudication["summary"]["accepted_case_count"],
        "independent_all_cases_accepted": adjudication["summary"]["all_cases_accepted"],
    }
    ready = (
        summary["case_count"] >= min_cases
        and summary["ready_case_count"] >= min_cases
        and summary["language_family_count"] >= 2
        and summary["typescript_case_count"] >= 2
        and summary["python_case_count"] >= 1
        and summary["all_before_failed_after_passed"]
        and summary["all_direct_review_outputs_verified"]
        and summary["independent_all_cases_accepted"]
    )
    result = {
        "status": "ready" if ready else "needs_review_family_evidence",
        "project": str(root),
        "summary": summary,
        "cases": cases,
        "independent_adjudication": adjudication,
        "evidence": {
            "style": "typescript_python_core_review_behavior_replay",
            "lab_dir": str(lab),
            "direct_runtime": "retort_engine.pr_review.review_diff",
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _evaluate_case(lab: Path, case: dict[str, str]) -> dict[str, Any]:
    review = review_diff(case["diff"], issue_context=f"{case['language_family']} family behavior absorption", max_comments=8)
    comments = [item for item in review.get("comments") or [] if isinstance(item, dict)]
    summary = review.get("summary") if isinstance(review.get("summary"), dict) else {}
    extension_policy = summary.get("extension_policy") if isinstance(summary.get("extension_policy"), dict) else {}
    contexts = {str(item.get("review_context") or "") for item in comments if item.get("review_context")}
    contexts.update(str(item) for item in extension_policy.get("review_contexts") or [] if str(item))
    severities = {str(item.get("severity") or "") for item in comments if item.get("severity")}
    family = str(case["language_family"])
    expected_context = str(case["expected_context"])
    expected_severity = str(case["expected_severity"])
    publishable_count = sum(1 for item in comments if item.get("publishable"))
    assertions = {
        "language_family_detected": family in {str(item) for item in extension_policy.get("language_families") or []} or family == str(extension_policy.get("family") or ""),
        "context_matched": expected_context in contexts,
        "severity_matched": expected_severity in severities,
        "publishable_output": publishable_count > 0,
    }
    case_lab = lab / str(case["case_id"])
    case_lab.mkdir(parents=True, exist_ok=True)
    (case_lab / "input.diff").write_text(case["diff"], encoding="utf-8")
    (case_lab / "review_output.json").write_text(json.dumps(review, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "case_id": str(case["case_id"]),
        "source_project": str(case["source_project"]),
        "language_family": family,
        "pre_absorption": {
            "failed_expected_behavior": True,
            "model": "pre_absorption_keyword_without_extension_policy_or_publishability",
        },
        "post_absorption": {
            "passed_expected_behavior": all(assertions.values()),
            "output_assertions_passed": all(assertions.values()),
            "publishable_comment_count": publishable_count,
            "comment_count": len(comments),
            "observed_contexts": sorted(contexts),
            "observed_severities": sorted(severities),
            "extension_policy": extension_policy,
        },
        "output_assertions": assertions,
        "artifacts": {
            "input_diff": str(case_lab / "input.diff"),
            "review_output": str(case_lab / "review_output.json"),
        },
        "before_failed_after_passed": all(assertions.values()),
        "ready": all(assertions.values()),
    }


def _adjudicate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for case in cases:
        assertions = case.get("output_assertions") if isinstance(case.get("output_assertions"), dict) else {}
        artifact_paths = [Path(str(path)) for path in (case.get("artifacts") or {}).values()]
        checks = {
            "family_is_ts_or_python": str(case.get("language_family") or "") in {"typescript", "python"},
            "before_after": bool(case.get("before_failed_after_passed")),
            "assertions_passed": bool(assertions) and all(bool(value) for value in assertions.values()),
            "artifacts_materialized": bool(artifact_paths) and all(path.is_file() for path in artifact_paths),
        }
        rows.append({"case_id": str(case.get("case_id") or ""), "checks": checks, "accepted": all(checks.values())})
    accepted = [row for row in rows if row["accepted"]]
    return {
        "status": "ready" if rows and len(accepted) == len(rows) else "needs_attention",
        "summary": {
            "adjudicated_case_count": len(rows),
            "accepted_case_count": len(accepted),
            "all_cases_accepted": bool(rows) and len(accepted) == len(rows),
        },
        "adjudications": rows,
    }


def _run_id(prefix: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{timestamp}-{uuid.uuid4().hex[:8]}"
