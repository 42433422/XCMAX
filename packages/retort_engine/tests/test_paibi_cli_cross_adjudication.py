from __future__ import annotations

import json
from pathlib import Path

from retort_engine.cli import main
from retort_engine.contracts import validate_contract
from retort_engine.paibi_cli_cross_adjudication import build_paibi_cli_cross_adjudication
from retort_engine.paibi_llm import PAIBI_SUPPORTED_TOOLS
from retort_engine.service import RetortService


def test_paibi_cli_cross_adjudication_runs_all_supported_cli_identities(tmp_path: Path) -> None:
    _write_inputs(tmp_path)

    result = build_paibi_cli_cross_adjudication(tmp_path)

    assert result["status"] == "ready"
    assert result["summary"]["tool_count"] == len(PAIBI_SUPPORTED_TOOLS)
    assert result["summary"]["accepted_tool_count"] == 4
    assert result["summary"]["all_tools_accepted"] is True
    assert result["summary"]["cross_tool_consensus"] is True
    assert result["summary"]["input_contains_score_fields"] is False
    assert result["summary"]["script_imports_retort_engine"] is False
    assert result["summary"]["no_human_operating_model"] is True
    assert result["summary"]["human_review_required"] is False
    assert result["summary"]["human_review_not_applicable"] is True
    assert result["summary"]["oracle_calibrated_cli_consensus"] is True
    assert result["summary"]["human_reviewed"] is False
    assert result["summary"]["human_calibrated_cli_consensus"] is True
    assert result["summary"]["calibration_label_count"] == 50
    assert result["summary"]["calibration_human_label_count"] == 50
    assert result["summary"]["calibration_pass_rate"] == 1.0
    assert result["summary"]["replaces_human_labels"] is False
    assert {item["tool_name"] for item in result["tool_results"]} == set(PAIBI_SUPPORTED_TOOLS)
    assert all(item["output_sha256"] for item in result["tool_results"])
    assert validate_contract("paibi_cli_cross_adjudication_result", result)["valid"] is True


def test_paibi_cli_cross_adjudication_rejects_non_accepted_blind_cases(tmp_path: Path) -> None:
    _write_inputs(tmp_path)
    blind_path = tmp_path / "docs" / "retort_competitor_blind_adjudication.json"
    blind = json.loads(blind_path.read_text(encoding="utf-8"))
    blind["cases"][0]["accepted"] = False
    blind["cases"][0]["label"] = "needs_review"
    blind_path.write_text(json.dumps(blind, ensure_ascii=False), encoding="utf-8")

    result = build_paibi_cli_cross_adjudication(tmp_path)

    assert result["status"] == "needs_paibi_cli_cross_adjudication"
    assert result["summary"]["input_contains_score_fields"] is False
    assert result["summary"]["all_tools_accepted"] is False


def test_service_exposes_paibi_cli_cross_adjudication(tmp_path: Path) -> None:
    _write_inputs(tmp_path)

    result = RetortService().paibi_cli_cross_adjudication({"project": str(tmp_path)})

    assert result["status"] == "ready"
    assert result["summary"]["accepted_tool_count"] == 4


def test_cli_writes_paibi_cli_cross_adjudication_report(tmp_path: Path) -> None:
    _write_inputs(tmp_path)
    output = tmp_path / "docs" / "retort_paibi_cli_cross_adjudication.json"

    code = main(["paibi-cli-cross-adjudication", "--project", str(tmp_path), "--output", str(output), "--json"])

    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "ready"
    assert payload["summary"]["accepted_tool_count"] == 4


def _write_inputs(root: Path) -> None:
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "retort_competitor_blind_adjudication.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "summary": {
                    "all_competitors_blind_accepted": True,
                    "accepted_competitor_count": 3,
                    "competitor_count": 3,
                    "minimum_blind_delta": 56,
                    "script_imports_retort_engine": False,
                    "input_contains_score_fields": False,
                },
                "cases": [
                    {
                        "project": "mopemope/pr-ai-review-bot",
                        "kind": "patch_output_parser",
                        "label": "retort_wins",
                        "accepted": True,
                        "live_upstream_materialized": True,
                        "output_sha256": "a" * 64,
                    },
                    {
                        "project": "qodo-ai/pr-agent",
                        "kind": "security_review",
                        "label": "retort_wins",
                        "accepted": True,
                        "live_upstream_materialized": True,
                        "output_sha256": "b" * 64,
                    },
                    {
                        "project": "reviewdog/reviewdog",
                        "kind": "ci_publisher",
                        "label": "retort_wins",
                        "accepted": True,
                        "live_upstream_materialized": True,
                        "output_sha256": "c" * 64,
                    },
                ],
                "artifacts": {},
                "evidence": {"human_reviewed": False},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (docs / "retort_competitor_behavior_regression.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "summary": {
                    "all_competitor_signals_regressed": True,
                    "all_cases_direct_review_execution": True,
                    "ready_case_count": 3,
                    "case_count": 3,
                    "behavior_assertion_count": 18,
                },
                "cases": [
                    _behavior_case("mopemope-runtime-output-parser", "mopemope/pr-ai-review-bot", "typescript_patch_output_parsing"),
                    _behavior_case("qodo-security-secret-review", "qodo-ai/pr-agent", "security_ranked_pr_review"),
                    _behavior_case("reviewdog-ci-token-publisher", "reviewdog/reviewdog", "ci_review_publisher_safety"),
                ],
                "evidence": {"runtime": "retort_engine.pr_review.review_diff"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (docs / "retort_review_adjudication_calibration.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "summary": {
                    "human_label_count": 50,
                    "calibration_label_count": 50,
                    "no_human_operating_model": True,
                    "human_review_required": False,
                    "human_review_not_applicable": True,
                    "label_source_type": "retort_oracle_no_human",
                    "pass_rate": 1.0,
                    "pre_calibration_pass_rate": 0.26,
                    "false_positive_count": 0,
                    "false_negative_count": 0,
                    "feedback_recalibration_applied": True,
                },
                "cases": [],
                "evidence": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _behavior_case(case_id: str, source_project: str, signal: str) -> dict[str, object]:
    return {
        "case_id": case_id,
        "source_project": source_project,
        "absorbed_signal": signal,
        "ready": True,
        "direct_review_execution": True,
        "assertions": {
            "reviewed": True,
            "expected_context_present": True,
            "expected_severity_present": True,
            "publishable_comment_present": True,
            "anchored_comment_present": True,
            "direct_review_execution": True,
        },
    }
