from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from retort_engine.competitor_blind_adjudication import build_competitor_blind_adjudication
from retort_engine.contracts import validate_contract
from retort_engine.service import RetortService


def test_competitor_blind_adjudication_labels_retort_win_from_artifacts(tmp_path: Path) -> None:
    _write_competitor_runtime_report(tmp_path)

    result = build_competitor_blind_adjudication(tmp_path, run_id="unit-competitor-blind")

    assert result["status"] == "ready"
    assert result["summary"]["accepted_competitor_count"] == 3
    assert result["summary"]["minimum_blind_delta"] >= 45
    assert result["summary"]["script_imports_retort_engine"] is False
    assert result["summary"]["input_contains_score_fields"] is False
    assert all(case["label"] == "retort_wins" for case in result["cases"])
    assert validate_contract("competitor_blind_adjudication_result", result)["valid"] is True


def test_service_exposes_competitor_blind_adjudication(tmp_path: Path) -> None:
    _write_competitor_runtime_report(tmp_path)

    result = RetortService().competitor_blind_adjudication({"project": str(tmp_path)})

    assert result["status"] == "ready"
    assert result["summary"]["all_competitors_blind_accepted"] is True


def test_competitor_blind_adjudication_cli_outputs_contract(tmp_path: Path) -> None:
    _write_competitor_runtime_report(tmp_path)
    completed = subprocess.run(
        [sys.executable, "-m", "retort_engine.cli", "competitor-blind-adjudication", "--project", str(tmp_path), "--json"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert validate_contract("competitor_blind_adjudication_result", payload)["valid"] is True
    assert payload["summary"]["accepted_competitor_count"] == 3


def _write_competitor_runtime_report(project: Path) -> None:
    docs = project / "docs"
    lab = project / ".retort" / "runtime"
    docs.mkdir(parents=True)
    lab.mkdir(parents=True)
    outputs = []
    for name, payload in {
        "mopemope__pr-ai-review-bot": {"status": "parsed", "hunk_count": 2, "hunks": [{"to": {"content": ["+debug"]}}, {"to": {"content": ["+info"]}}]},
        "qodo-ai__pr-agent": {"status": "review_signal_counted", "finding_count": 2, "findings": [{"rule": "debug"}, {"rule": "error_path"}]},
        "reviewdog__reviewdog": {"status": "diagnostics_mapped", "finding_count": 3, "diagnostics": [{"line": 5}, {"line": 84}, {"line": 86}]},
    }.items():
        path = lab / f"{name}_output.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        outputs.append((name.replace("__", "/"), path, payload))
    report = {
        "status": "ready",
        "summary": {"competitor_project_count": 3, "ready_competitor_project_count": 3},
        "competitor_output": {
            "runtimes": [
                {
                    "project": project_name,
                    "kind": "fixture",
                    "ready": True,
                    "external_process_returncode": 0,
                    "output": payload,
                    "output_path": str(path),
                    "source_sha256": f"{index}abc",
                    "live_upstream": {"materialized": True, "source_sha": f"{index}def"},
                }
                for index, (project_name, path, payload) in enumerate(outputs)
            ]
        },
        "retort_output": {
            "comments": [
                {
                    "comment_anchor": {"path": "src/main.ts", "line": 5},
                    "severity": "medium",
                    "review_context": "runtime",
                    "publishable": True,
                    "employee_actionable": True,
                    "publish_payload": {"body": "review"},
                },
                {
                    "comment_anchor": {"path": "src/main.ts", "line": 83},
                    "severity": "info",
                    "review_context": "runtime",
                    "publishable": True,
                    "employee_actionable": False,
                    "publish_payload": {"body": "review"},
                },
                {
                    "comment_anchor": {"path": "src/main.ts", "line": 86},
                    "severity": "medium",
                    "review_context": "runtime",
                    "publishable": True,
                    "employee_actionable": False,
                    "publish_payload": {"body": "review"},
                },
            ]
        },
        "artifacts": {},
        "evidence": {},
    }
    (docs / "retort_competitor_runtime_comparison.json").write_text(json.dumps(report), encoding="utf-8")
