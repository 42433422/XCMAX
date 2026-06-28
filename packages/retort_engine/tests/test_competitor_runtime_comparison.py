from __future__ import annotations

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
    assert result["summary"]["competitor_hunk_count"] >= 2
    assert result["summary"]["retort_review_status"] == "reviewed"
    assert result["summary"]["side_by_side_output_materialized"] is True
    assert validate_contract("competitor_runtime_comparison_result", result)["valid"] is True


def test_service_exposes_competitor_runtime_comparison(tmp_path: Path) -> None:
    competitor = _write_competitor_fixture(tmp_path)

    result = RetortService().competitor_runtime_comparison({"project": str(tmp_path), "competitor_root": str(competitor)})

    assert result["status"] == "ready"
    assert result["summary"]["retort_exceeds_patch_parser_by_semantic_comments"] is True


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


def _write_competitor_fixture(root: Path) -> Path:
    competitor = root / "external" / "mopemope-pr-ai-review-bot"
    source = competitor / "src" / "patchParser.ts"
    source.parent.mkdir(parents=True)
    source.write_text("export const parsePatch = () => []\n", encoding="utf-8")
    return competitor
