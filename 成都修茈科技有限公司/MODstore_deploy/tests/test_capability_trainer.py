import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from modstore_server import capability_trainer as trainer


def _rec(employee="daily-orchestrator", reason="marker_missing", status="failed", ts=None):
    return {
        "employee_id": employee,
        "error": reason,
        "status": status,
        "step": "review",
        "report_excerpt": "任务正文",
        "timestamp": ts or datetime.now(timezone.utc).isoformat(),
        "run_id": "r1",
    }


def test_cluster_requires_min_count_and_summarizes():
    records = [_rec(), _rec(), _rec(), _rec(employee="other", reason="x")]
    clusters = trainer.cluster_failures(records, min_count=2)
    assert len(clusters) == 1
    assert clusters[0]["employee_id"] == "daily-orchestrator"
    assert clusters[0]["count"] == 3


def test_cluster_ignores_old_and_successful_records():
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    records = [_rec(ts=old), _rec(ts=old), _rec(status="success")]
    assert trainer.cluster_failures(records, min_count=1) == []


def test_append_cases_is_idempotent(tmp_path):
    clusters = trainer.cluster_failures([_rec(), _rec()], min_count=1)
    first = trainer.append_cases(tmp_path, clusters)
    second = trainer.append_cases(tmp_path, clusters)
    assert len(first) == 1
    assert second == []
    rows = (tmp_path / "daily-orchestrator.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1


def test_select_pack_prefers_latest_version(tmp_path):
    for version in ("1.0.0", "1.0.2", "1.0.1"):
        folder = tmp_path / f"worker@{version}"
        folder.mkdir()
        (folder / "prompt.txt").write_text("p" + version, encoding="utf-8")
    assert trainer.select_pack(tmp_path, "worker").name == "worker@1.0.2"


def test_build_config_writes_promptfoo_inputs(tmp_path):
    built = trainer.build_config(
        out_dir=tmp_path,
        baseline_prompt="基线",
        candidate_prompt="候选",
        cases=[{"task": "任务一"}],
    )
    config = json.loads(Path(built["config"]).read_text(encoding="utf-8"))
    assert len(config["prompts"]) == 2
    assert config["tests"].startswith("file://")
    assert "{{task}}" in Path(built["baseline"]).read_text(encoding="utf-8")


def test_decide_only_promotes_strict_improvement():
    assert trainer.decide(
        {"results": {"results": [
            {"promptIdx": 0, "success": False},
            {"promptIdx": 1, "success": True},
        ]}}
    )["verdict"] == "promote"
    assert trainer.decide(
        {"results": {"results": [
            {"promptIdx": 0, "success": True},
            {"promptIdx": 1, "success": True},
        ]}}
    )["verdict"] == "keep_baseline"
