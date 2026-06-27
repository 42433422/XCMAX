from __future__ import annotations

import json
from pathlib import Path

from retort_engine.comparative_replay import build_cross_project_replay
from retort_engine.contracts import validate_contract


def test_build_cross_project_replay_requires_real_evidence(tmp_path: Path) -> None:
    project = tmp_path / "project"
    run_dir = project / ".retort" / "real_absorption_runs"
    docs = project / "docs"
    run_dir.mkdir(parents=True)
    docs.mkdir()
    for index in range(3):
        (run_dir / f"run-{index}.json").write_text(
            json.dumps(
                {
                    "source": f"https://github.com/acme/repo-{index}",
                    "run_id": f"run-{index}",
                    "changed_files": [str(project / "retort_engine" / "absorbed_capabilities.py")],
                    "external_profile": {"signals": ["review_pipeline", f"signal_{index}"]},
                    "semantic_review": {"gaps": []},
                    "gates_passed": True,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    (docs / "retort_pr_dry_run_report.json").write_text(json.dumps({"status": "reviewed", "summary": {"comment_count": 4}}, ensure_ascii=False), encoding="utf-8")
    (docs / "retort_pr_publish_dry_run.json").write_text(json.dumps({"status": "dry_run_ready", "summary": {"would_post_comment_count": 4}}, ensure_ascii=False), encoding="utf-8")

    result = build_cross_project_replay(project)

    assert result["status"] == "ready"
    assert result["summary"]["external_project_count"] == 3
    assert result["summary"]["distinct_signal_count"] >= 4
    assert all(check["passed"] for check in result["checks"])
    assert validate_contract("cross_project_replay_result", result)["valid"] is True
