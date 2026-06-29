from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from retort_engine.competitor_runtime_comparison import build_competitor_runtime_comparison
from retort_engine.contracts import validate_contract
from retort_engine.service import RetortService


def test_competitor_runtime_comparison_materializes_side_by_side_outputs(tmp_path: Path) -> None:
    competitor = _write_competitor_fixture(tmp_path)

    result = build_competitor_runtime_comparison(tmp_path, competitor_root=competitor, run_id="unit-competitor-runtime")

    assert result["status"] == "ready"
    assert result["summary"]["competitor_source_exists"] is True
    assert result["summary"]["competitor_project_count"] == 3
    assert result["summary"]["ready_competitor_project_count"] == 3
    assert result["summary"]["multi_competitor_side_by_side"] is True
    assert result["summary"]["competitor_hunk_count"] >= 2
    assert result["summary"]["external_diagnostic_count"] >= 1
    assert result["retort_output"]["summary"]["external_diagnostic_ingestion"]["accepted_count"] >= 1
    assert result["summary"]["retort_review_status"] == "reviewed"
    assert result["summary"]["side_by_side_output_materialized"] is True
    assert validate_contract("competitor_runtime_comparison_result", result)["valid"] is True


def test_competitor_runtime_comparison_can_force_live_materialized_sources(tmp_path: Path, monkeypatch) -> None:
    def fake_gh_api(endpoint: str) -> dict:
        if endpoint.startswith("repos/") and "/contents/" not in endpoint:
            return {"returncode": 0, "json": {"default_branch": "main"}, "stderr_tail": ""}
        raw = f"live source for {endpoint}\n".encode("utf-8")
        git_blob_sha = hashlib.sha1(f"blob {len(raw)}\0".encode("utf-8") + raw).hexdigest()
        return {
            "returncode": 0,
            "json": {
                "sha": git_blob_sha,
                "content": base64.b64encode(raw).decode("ascii"),
                "html_url": f"https://example.test/{endpoint}",
                "download_url": f"https://example.test/{endpoint}/raw",
            },
            "stderr_tail": "",
        }

    monkeypatch.setattr("retort_engine.competitor_runtime_comparison._gh_api", fake_gh_api)

    result = build_competitor_runtime_comparison(tmp_path, live_upstream=True, force_live_refresh=True, run_id="unit-live-refresh")

    assert result["status"] == "ready"
    assert result["summary"]["force_live_refresh"] is True
    assert result["summary"]["all_runtime_sources_from_live_refresh"] is True
    assert result["summary"]["live_refresh_used_count"] == result["summary"]["competitor_project_count"]
    assert result["summary"]["all_live_upstream_sources_materialized"] is True
    assert result["summary"]["external_diagnostic_count"] >= 1
    assert result["retort_output"]["summary"]["core_review_score"]["external_diagnostic_core_behavior_active"] is True
    assert {item["source_mode"] for item in result["competitor_output"]["runtimes"]} == {"live_materialized"}
    assert validate_contract("competitor_runtime_comparison_result", result)["valid"] is True


def test_service_exposes_competitor_runtime_comparison(tmp_path: Path) -> None:
    competitor = _write_competitor_fixture(tmp_path)

    result = RetortService().competitor_runtime_comparison({"project": str(tmp_path), "competitor_root": str(competitor)})

    assert result["status"] == "ready"
    assert result["summary"]["retort_exceeds_patch_parser_by_semantic_comments"] is True
    assert result["summary"]["retort_exceeds_all_competitors_by_semantic_comments"] is True


def test_competitor_runtime_comparison_cli_outputs_contract(tmp_path: Path) -> None:
    competitor = _write_competitor_fixture(tmp_path)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "retort_engine.cli",
            "competitor-runtime-comparison",
            "--project",
            str(tmp_path),
            "--competitor-root",
            str(competitor),
            "--json",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert validate_contract("competitor_runtime_comparison_result", payload)["valid"] is True
    assert payload["summary"]["side_by_side_output_materialized"] is True
    assert payload["summary"]["ready_competitor_project_count"] == 3


def _write_competitor_fixture(root: Path) -> Path:
    competitor = root / "external" / "mopemope-pr-ai-review-bot"
    source = competitor / "src" / "patchParser.ts"
    source.parent.mkdir(parents=True)
    source.write_text("export const parsePatch = () => []\n", encoding="utf-8")
    qodo_source = root / ".retort" / "cache" / "github" / "qodo-ai" / "pr-agent" / "pr_agent" / "tools" / "pr_reviewer.py"
    qodo_source.parent.mkdir(parents=True)
    qodo_source.write_text("class PRReviewer:\n    pass\n", encoding="utf-8")
    reviewdog_source = root / ".retort" / "cache" / "github" / "reviewdog" / "reviewdog" / "diff" / "parse.go"
    reviewdog_source.parent.mkdir(parents=True)
    reviewdog_source.write_text("package diff\n", encoding="utf-8")
    return competitor
