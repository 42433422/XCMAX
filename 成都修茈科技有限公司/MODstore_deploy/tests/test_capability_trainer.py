import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

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


def test_build_config_writes_promptfoo_inputs(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_LLM_MODEL", "approved-model")
    monkeypatch.setenv("XCAGI_LLM_BASE_URL", "https://platform.test/v1")
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
    assert config["defaultTest"]["options"]["provider"] == config["providers"][0]
    assert config["providers"][0]["config"]["max_tokens"] == 1024


def paired_result():
    return {
        "results": {
            "results": [
                {
                    "promptIdx": i,
                    "testIdx": 0,
                    "success": bool(i),
                    "failureReason": 0 if i else 1,
                    "gradingResult": {"pass": bool(i)},
                    "error": None if i else "Deterministic assertion failed",
                    "provider": {"id": "model"},
                    "vars": {"case_id": "case", "task": "actual case"},
                }
                for i in range(2)
            ]
        }
    }


def test_decide_requires_paired_provider_case_and_frozen_bundle():
    result, bundle = paired_result(), {"provider_id": "model", "case_ids": ["case"]}
    assert trainer.decide(result)["verdict"] == "keep_baseline"
    assert trainer.decide(result, bundle=bundle)["verdict"] == "candidate_for_approval"
    unavailable = deepcopy(result)
    unavailable["results"]["results"][0]["failureReason"] = 2
    assert trainer.decide(unavailable, bundle=bundle)["verdict"] == "keep_baseline"
    for mutation in ("provider", "testIdx", "success", "vars"):
        changed = deepcopy(result)
        changed["results"]["results"][1][mutation] = {
            "provider": {"id": "other"},
            "testIdx": 1,
            "success": "true",
            "vars": {"case_id": "other"},
        }[mutation]
        assert trainer.decide(changed, bundle=bundle)["verdict"] == "keep_baseline"
    result["results"]["results"].append(deepcopy(result["results"]["results"][1]))
    assert trainer.decide(result, bundle=bundle)["verdict"] == "keep_baseline"


def frozen_evaluation(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_LLM_MODEL", "approved-model")
    monkeypatch.setenv("XCAGI_LLM_BASE_URL", "https://platform.test/v1")
    built = trainer.build_config(
        out_dir=tmp_path,
        baseline_prompt="baseline\r\n",
        candidate_prompt="candidate\r\n",
        cases=[{"task": "actual case"}],
    )
    bundle = json.loads(Path(built["bundle"]).read_text())
    result = paired_result()
    result["metadata"] = {"promptfooVersion": trainer.PROMPTFOO_VERSION}
    result["results"]["prompts"] = [
        {"raw": Path(built[key]).read_bytes().decode()} for key in ("baseline", "candidate")
    ]
    for row in result["results"]["results"]:
        row["provider"]["id"] = bundle["provider_id"]
        row["vars"]["case_id"] = bundle["case_ids"][0]
    output = tmp_path / "result.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return built, output


def test_frozen_input_result_hashes_survive_transport_and_detect_mutation(tmp_path, monkeypatch):
    from modstore_server.retort_training_candidates import _candidate

    built, result = frozen_evaluation(tmp_path, monkeypatch)
    original = trainer.seal_evaluation(Path(built["bundle"]), result)
    body = {
        "bundle_json": Path(built["bundle"]).read_bytes().decode(),
        "result_json": result.read_bytes().decode(),
        "files": {
            key: Path(built[key]).read_bytes().decode()
            for key in ("baseline", "candidate", "config", "tests")
        },
    }
    candidate = _candidate(json.loads(json.dumps(body)))
    assert candidate["offline_evidence"] == original
    assert candidate["control_prompt"] == "baseline\r\n"
    wrong_bundle = deepcopy(body)
    document = json.loads(wrong_bundle["bundle_json"])
    document["prompt_sha256"]["candidate"] = "0" * 64
    wrong_bundle["bundle_json"] = json.dumps(document)
    with pytest.raises(ValueError, match="prompt_hash_mismatch"):
        _candidate(wrong_bundle)
    body["files"]["candidate"] += "changed"
    with pytest.raises(ValueError, match="input_changed"):
        _candidate(body)


def test_observation_without_reproduction_is_not_synthetic_case(tmp_path):
    clusters = trainer.cluster_failures([{**_rec(), "report_excerpt": ""}], min_count=1)
    assert trainer.append_cases(tmp_path, clusters) == []


def test_training_cost_bounds_and_unconfigured_model_fail_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("XCAGI_LLM_MODEL", raising=False)
    with pytest.raises(ValueError, match="not_configured"):
        trainer.build_config(
            out_dir=tmp_path, baseline_prompt="b", candidate_prompt="c", cases=[{"task": "case"}]
        )
    monkeypatch.setenv("XCAGI_LLM_MODEL", "model")
    monkeypatch.setenv("XCAGI_LLM_BASE_URL", "https://platform.test/v1")
    with pytest.raises(ValueError, match="cases_required"):
        trainer.build_config(
            out_dir=tmp_path,
            baseline_prompt="b",
            candidate_prompt="c",
            cases=[{"task": "case"}] * 21,
        )
