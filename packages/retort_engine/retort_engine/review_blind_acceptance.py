from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from retort_engine.pr_review import review_diff

BLIND_MANIFEST = Path("tests") / "review_blind_cases" / "manifest.json"
PASS_RATE_FLOOR = 0.85


def build_review_blind_acceptance(
    project: str | Path = ".", *, output: str | Path = ""
) -> dict[str, Any]:
    """Evaluate sealed external-holdout review fixtures without rewriting them.

    Labels are precommitted expectations. The synthesizer must never edit the
    manifest; this gate only measures whether review_diff still meets them.
    """
    root = Path(project).expanduser().resolve()
    manifest = _load_manifest(root)
    cases = [
        _evaluate_case(case)
        for case in manifest.get("cases") or []
        if isinstance(case, dict)
    ]
    passed = [case for case in cases if case["passed"]]
    floor = float(manifest.get("pass_rate_floor") or PASS_RATE_FLOOR)
    pass_rate = round(len(passed) / len(cases), 4) if cases else 0.0
    summary = {
        "case_count": len(cases),
        "passed_count": len(passed),
        "failed_count": len(cases) - len(passed),
        "pass_rate": pass_rate,
        "pass_rate_floor": floor,
        "floor_met": bool(cases) and pass_rate >= floor,
        "synthesizer_must_not_rewrite": True,
        "label_policy": str(
            manifest.get("label_policy") or "sealed_external_holdout_expectations"
        ),
        "competitor_blind_excluded": True,
    }
    result = {
        "status": "ready" if summary["floor_met"] else "needs_attention",
        "project": str(root),
        "summary": summary,
        "cases": cases,
        "evidence": {
            "manifest": str(
                (root / BLIND_MANIFEST)
                if (root / BLIND_MANIFEST).is_file()
                else _package_manifest()
            ),
            "style": "sealed_external_holdout_blind_acceptance",
            "oracle": "precommitted_expectation_not_self_scorer",
        },
    }
    if output:
        path = Path(output).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return result


def _evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    expectation = dict(case.get("expectation") or {})
    diagnostics = [
        item
        for item in case.get("external_diagnostics") or []
        if isinstance(item, dict)
    ]
    review = review_diff(
        str(case.get("diff") or ""),
        max_comments=8,
        external_diagnostics=diagnostics or None,
    )
    comments = [item for item in review.get("comments") or [] if isinstance(item, dict)]
    publishable = [item for item in comments if item.get("publishable")]
    top = comments[0] if comments else {}
    checks = {
        "min_publishable_comments": len(publishable)
        >= int(expectation.get("min_publishable_comments") or 0),
        "expected_context": _match_optional(
            expectation.get("expected_context"),
            top.get("review_context") or _any_context(comments),
        ),
        "expected_severity": _match_optional(
            expectation.get("expected_severity"),
            top.get("severity") or _any_severity(comments),
        ),
        "top_capability": _match_optional(
            expectation.get("top_capability"), top.get("capability")
        ),
    }
    return {
        "case_id": str(case.get("case_id") or ""),
        "source_url": str(case.get("source_url") or ""),
        "passed": all(checks.values()),
        "checks": checks,
        "expectation": expectation,
        "review_summary": {
            "comment_count": len(comments),
            "publishable_comment_count": len(publishable),
            "top_capability": top.get("capability"),
            "top_context": top.get("review_context"),
            "top_severity": top.get("severity"),
        },
    }


def _match_optional(expected: Any, actual: Any) -> bool:
    wanted = str(expected or "").strip()
    if not wanted:
        return True
    return wanted == str(actual or "").strip()


def _any_context(comments: list[dict[str, Any]]) -> str:
    for comment in comments:
        if comment.get("review_context"):
            return str(comment["review_context"])
    return ""


def _any_severity(comments: list[dict[str, Any]]) -> str:
    for comment in comments:
        if comment.get("severity"):
            return str(comment["severity"])
    return ""


def _load_manifest(root: Path) -> dict[str, Any]:
    path = root / BLIND_MANIFEST
    if not path.is_file():
        path = _package_manifest()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _package_manifest() -> Path:
    return Path(__file__).resolve().parents[1] / BLIND_MANIFEST
