"""Protect actual pinned CLI output in ordinary CI and rerun its producer when installed.

The golden artifacts were captured from the real 0.126.0 echo/contains run below;
their original output and input bytes are preserved, including CRLF and --- lines.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from modstore_server import capability_trainer as trainer
from tests.promptfoo_local_only import local_only_environment

FIXTURE = Path(__file__).parent / "fixtures" / "promptfoo-0.126.0"
RESULT_SHA256 = "9cbc0c0327376ebeb03112aab6c76b4605399efb97751d45c0dbead0d69e4844"


def test_captured_real_cli_output_seals_without_installing_node():
    output = FIXTURE / "actual-promptfoo-result.json"
    assert trainer._file_hash(output) == RESULT_SHA256
    actual = json.loads(output.read_bytes())
    assert actual["metadata"]["promptfooVersion"] == "0.126.0"
    rows = actual["results"]["results"]
    assert len(rows) == 4
    assert {row["vars"]["case_id"] for row in rows} == {"case-0", "case-1"}
    assert {row["provider"]["id"] for row in rows} == {"echo"}
    failures = [row for row in rows if row["success"] is False]
    assert len(failures) == 2
    assert all(
        row["failureReason"] == 1 and row["error"] and row["gradingResult"]["pass"] is False
        for row in failures
    )
    assert [prompt["raw"] for prompt in actual["results"]["prompts"]] == [
        (FIXTURE / name).read_bytes().decode("utf-8")
        for name in ("baseline_prompt.md", "candidate_prompt.md")
    ]
    proposal = trainer.candidate_for_experiment(FIXTURE / "training-bundle.json", output)
    assert proposal["control_prompt"] == "BASELINE_ONLY\r\n---\r\n"
    assert proposal["treatment_prompt"] == "CANDIDATE_PASS\r\n---\r\n"
    evidence = proposal["offline_evidence"]
    assert evidence["verdict"] == "candidate_for_approval"
    assert evidence["baseline"] == {"pass": 0, "total": 2}
    assert evidence["candidate"] == {"pass": 2, "total": 2}
    assert evidence["results_sha256"] == RESULT_SHA256


@pytest.mark.parametrize("name", ["baseline", "candidate", "config", "tests"])
def test_captured_bundle_rejects_changed_input_bytes(tmp_path, name):
    shutil.copytree(FIXTURE, tmp_path, dirs_exist_ok=True)
    bundle_path = tmp_path / "training-bundle.json"
    bundle = json.loads(bundle_path.read_bytes())
    changed = tmp_path / bundle["files"][name]["name"]
    changed.write_bytes(changed.read_bytes() + b" ")
    with pytest.raises(ValueError, match="training_input_changed"):
        trainer.seal_evaluation(bundle_path, tmp_path / "actual-promptfoo-result.json")


@pytest.mark.parametrize("field", ["prompt_sha256", "case_sha256"])
def test_captured_bundle_rejects_inconsistent_metadata_hashes(tmp_path, field):
    shutil.copytree(FIXTURE, tmp_path, dirs_exist_ok=True)
    bundle_path = tmp_path / "training-bundle.json"
    bundle = json.loads(bundle_path.read_bytes())
    if field == "prompt_sha256":
        bundle[field]["candidate"] = "0" * 64
    else:
        bundle[field][0] = "0" * 64
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    assert trainer._file_hash(tmp_path / "actual-promptfoo-result.json") == RESULT_SHA256
    with pytest.raises(ValueError, match="training_(?:prompt|case)_hash_mismatch"):
        trainer.seal_evaluation(bundle_path, tmp_path / "actual-promptfoo-result.json")


def test_real_promptfoo_cli_seals_paired_results_without_model_credentials(tmp_path, monkeypatch):
    cli = os.environ.get("PROMPTFOO_CLI") or shutil.which("promptfoo")
    if not cli:
        pytest.skip("install promptfoo@0.126.0 and set PROMPTFOO_CLI to exercise its real output")
    monkeypatch.setenv("XCAGI_LLM_MODEL", "unused-fixture")
    monkeypatch.setenv("XCAGI_LLM_BASE_URL", "https://unused.invalid/v1")
    control, candidate = "BASELINE_ONLY\r\n---\r\n", "CANDIDATE_PASS\r\n---\r\n"
    built = trainer.build_config(
        out_dir=tmp_path,
        baseline_prompt=control,
        candidate_prompt=candidate,
        cases=[{"task": "Fixture alpha"}, {"task": "Fixture beta"}],
    )
    config_path, tests_path = Path(built["config"]), Path(built["tests"])
    config = json.loads(config_path.read_bytes())
    config.update(providers=["echo"], sharing=False)
    config.pop("defaultTest")
    config_path.write_text(json.dumps(config), encoding="utf-8")
    cases = json.loads(tests_path.read_bytes())
    for case in cases:
        case["assert"] = [{"type": "contains", "value": "CANDIDATE_PASS"}]
    tests_path.write_text(json.dumps(cases), encoding="utf-8")
    bundle_path = Path(built["bundle"])
    bundle = json.loads(bundle_path.read_bytes())
    bundle["provider_id"] = "echo"
    for key in ("config", "tests"):
        bundle["files"][key]["sha256"] = trainer._file_hash(Path(built[key]))
    bundle_path.write_text(json.dumps(bundle, sort_keys=True), encoding="utf-8")
    output_path = tmp_path / "actual-promptfoo-result.json"
    with local_only_environment(tmp_path) as (environment, denied_hosts):
        process = subprocess.run(
            [
                str(cli),
                "eval",
                "-c",
                str(config_path),
                "-o",
                str(output_path),
                "--no-cache",
                "--no-write",
                "--no-share",
                "--max-concurrency",
                "1",
                "--no-progress-bar",
            ],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
    assert denied_hosts and set(denied_hosts) == {"r.promptfoo.app"}
    assert process.returncode == 100, process.stderr
    actual = json.loads(output_path.read_bytes())
    assert actual["metadata"]["promptfooVersion"] == trainer.PROMPTFOO_VERSION
    assert len(actual["results"]["results"]) == 4
    sealed = trainer.seal_evaluation(bundle_path, output_path)
    assert sealed["verdict"] == "candidate_for_approval"
    assert sealed["baseline"] == {"pass": 0, "total": 2}
    assert sealed["candidate"] == {"pass": 2, "total": 2}
    proposal = trainer.candidate_for_experiment(bundle_path, output_path)
    assert proposal["control_prompt"] == control and proposal["treatment_prompt"] == candidate
    assert sealed["results_sha256"] == trainer._file_hash(output_path)
