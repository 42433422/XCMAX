"""Pinned promptfoo -> original native Excel runtime -> independently sealed holdout.

The local provider supplies deterministic graphs; it is not a real-model or
customer acceptance claim. Native employees and workbook verification are real.
"""

import io
import json
import os
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from openpyxl import Workbook

from modstore_server import capability_trainer as trainer
from modstore_server import workflow_training_replay as replay
from modstore_server.workflow_nl_graph import SYSTEM_PROMPT
from modstore_server.workflow_nl_training import DEFERRED_BUSINESS_REASON
from tests.promptfoo_local_only import local_only_environment
from tests.test_workflow_training_replay import _fixture


def _cases():
    source, graph, binding = _fixture("excel")
    partitions = {}
    for number in range(100):
        current, frozen = deepcopy(source), deepcopy(binding)
        contract = frozen["customer_delivery"]
        snapshot = contract["business_replay"]
        assets = snapshot["assets"]
        order = f"fixture-order-{number}"
        payload = json.dumps(
            {"columns": ["order", "quantity"], "rows": [{"order": order, "quantity": 3}]}
        ).encode()
        assets["input_files"] = [replay._blob("inputs/order.json", payload)]
        workbook = Workbook()
        workbook.active.title = "Sheet1"
        workbook.active.append(["order", "quantity"])
        workbook.active.append([order, 3])
        reference = io.BytesIO()
        workbook.save(reference)
        workbook.close()
        assets["expected_files"] = [replay._blob("outputs/output.xlsx", reference.getvalue())]
        group = replay.source_group_sha256({"assets": assets, "contract": contract})
        snapshot["source_group_sha256"] = group
        contract["contract_sha256"] = replay._digest(
            {key: value for key, value in contract.items() if key != "contract_sha256"}
        )
        current["customer_business_replay"] = replay.export_customer_replay(
            frozen, assets["input_data"], "e" * 64
        )
        source_sha = replay._sha(payload)
        partition = "holdout" if int(source_sha[:8], 16) % 5 == 0 else "development"
        partitions.setdefault(
            partition, {"task": f"Generate {order}", "generation_context": current}
        )
        if len(partitions) == 2:
            return [partitions["development"], partitions["holdout"]], graph
    raise AssertionError("fixture did not produce distinct original-content partitions")


@pytest.mark.parametrize("deferred", [False, True], ids=["direct", "deferred"])
def test_actual_promptfoo_excel_results_revalidate_and_seal_independent_holdout(
    tmp_path, monkeypatch, deferred
):
    cli = os.environ.get("PROMPTFOO_CLI") or shutil.which("promptfoo")
    if not cli:
        pytest.skip("requires the repository's pinned promptfoo CLI")
    sandbox = os.environ.get("PROMPTFOO_SANDBOX_ENTRY")
    assert sandbox, "requires the repository's pinned native replay sandbox"
    monkeypatch.setenv("XCAGI_LLM_MODEL", "unused-fixture")
    monkeypatch.setenv("XCAGI_LLM_BASE_URL", "https://unused.invalid/v1")
    cases, graph = _cases()
    baseline_graph = deepcopy(graph)
    baseline_graph["nodes"][1]["config"]["input_mapping"]["table_json"] = {
        "columns": ["order", "quantity"],
        "rows": [{"order": "incorrect-fixture-order", "quantity": 99}],
    }
    marker = "Business fixture candidate: preserve the required output path."
    built = trainer.build_config(
        out_dir=tmp_path,
        baseline_prompt=SYSTEM_PROMPT,
        candidate_prompt=SYSTEM_PROMPT + "\n" + marker,
        cases=cases,
        surface="workflow_nl_prompt",
    )
    provider = tmp_path / "native-graph-provider.cjs"
    provider.write_text(
        "module.exports = class { id() { return 'business-fixture'; } "
        "async callApi(prompt) { const system = JSON.parse(prompt)[0].content; "
        "return {output: JSON.stringify(system.includes("
        + json.dumps(marker)
        + ") ? "
        + json.dumps(graph)
        + " : "
        + json.dumps(baseline_graph)
        + ")}; }};",
        encoding="utf-8",
    )
    config_path, bundle_path = Path(built["config"]), Path(built["bundle"])
    config = json.loads(config_path.read_bytes())
    config["providers"] = [f"file://{provider}"]
    config.pop("defaultTest")
    config_path.write_text(json.dumps(config), encoding="utf-8")
    bundle = json.loads(bundle_path.read_bytes())
    bundle["provider_id"] = "business-fixture"
    bundle["files"]["config"]["sha256"] = trainer._file_hash(config_path)
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    output = tmp_path / "result.json"
    with local_only_environment(tmp_path) as (environment, _denied):
        environment["PROMPTFOO_PYTHON"] = sys.executable
        environment["NODE_OPTIONS"] = "--max-old-space-size=128"
        if deferred:
            environment["XCAGI_TRAINING_DEFER_NATIVE_REPLAY"] = "1"
        else:
            environment["PROMPTFOO_SANDBOX_ENTRY"] = sandbox
        process = subprocess.run(
            [
                str(cli),
                "eval",
                "-c",
                str(config_path),
                "-o",
                str(output),
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
            timeout=120,
        )
    assert process.returncode == 100, process.stderr[-4000:]
    raw_result = output.read_bytes()
    rows = json.loads(raw_result)["results"]["results"]
    assert len(rows) == 4
    if deferred:
        assert all(row["success"] is False for row in rows)
        assert all(
            row["gradingResult"]["componentResults"][0]["reason"] == DEFERRED_BUSINESS_REASON
            for row in rows
        )
    else:
        assert sum(row["success"] for row in rows) == 2
    evidence = trainer.seal_evaluation(bundle_path, output)
    assert output.read_bytes() == raw_result
    assert evidence["results_sha256"] == trainer._file_hash(output)
    assert evidence["baseline"] == {"pass": 0, "total": 2}
    assert evidence["candidate"] == {"pass": 2, "total": 2}
    assert evidence["verdict"] == "candidate_for_approval"
    assert evidence["runtime_verified"] is True
    assert evidence["holdout_verified"] is True
    assert set(evidence["business_evidence"]) == {"case-0", "case-1"}
    assert all(
        set(item["output_sha256"]) == {"outputs/output.xlsx"}
        for item in evidence["business_evidence"].values()
    )
    # The public CLI uses the same native sealing path, outside the model sandbox.
    command = subprocess.run(
        [
            sys.executable,
            "-m",
            "modstore_server.capability_trainer",
            "decide",
            "--bundle",
            str(bundle_path),
            "--result",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert command.returncode == 0, command.stderr[-4000:]
    assert json.loads(command.stdout)["verdict"] == "candidate_for_approval"
    from modstore_server.retort_training_candidates import _candidate

    proposal = _candidate(
        {
            "bundle_json": bundle_path.read_text(),
            "result_json": output.read_text(),
            "files": {name: Path(built[name]).read_text() for name in bundle["files"]},
        }
    )
    assert proposal["offline_evidence"]["runtime_verified"] is True


def _claimed_pass_bundle(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_LLM_MODEL", "unused-fixture")
    monkeypatch.setenv("XCAGI_LLM_BASE_URL", "https://unused.invalid/v1")
    cases, graph = _cases()
    built = trainer.build_config(
        out_dir=tmp_path,
        baseline_prompt=SYSTEM_PROMPT,
        candidate_prompt=SYSTEM_PROMPT + "\nCandidate fixture",
        cases=cases,
        surface="workflow_nl_prompt",
    )
    bundle_path = Path(built["bundle"])
    bundle = json.loads(bundle_path.read_bytes())
    tests = json.loads(Path(built["tests"]).read_bytes())
    # A fixed benign graph writes an in-workspace workbook with the wrong cells.
    graph["nodes"][1]["config"]["input_mapping"]["table_json"] = {
        "columns": ["order", "quantity"],
        "rows": [{"order": "wrong", "quantity": 99}],
    }
    output = tmp_path / "claimed-pass.json"
    output.write_text(
        json.dumps(
            {
                "metadata": {"promptfooVersion": trainer.PROMPTFOO_VERSION},
                "results": {
                    "prompts": [
                        {"raw": Path(built[key]).read_text()} for key in ("baseline", "candidate")
                    ],
                    "results": [
                        {
                            "promptIdx": arm,
                            "testIdx": index,
                            "success": True,
                            "failureReason": 0,
                            "provider": {"id": bundle["provider_id"]},
                            "vars": test["vars"],
                            "response": {"output": json.dumps(graph)},
                        }
                        for arm in (0, 1)
                        for index, test in enumerate(tests)
                    ],
                },
            }
        )
    )
    return built, bundle_path, output


@pytest.mark.parametrize("missing", [True, False])
def test_claimed_pass_cannot_seal_without_native_isolation(tmp_path, monkeypatch, missing):
    built, bundle_path, output = _claimed_pass_bundle(tmp_path, monkeypatch)
    if missing:
        monkeypatch.delenv("PROMPTFOO_SANDBOX_ENTRY", raising=False)
    else:
        monkeypatch.setenv("PROMPTFOO_SANDBOX_ENTRY", str(tmp_path / "missing-srt"))
    evidence = trainer.seal_evaluation(bundle_path, output)
    assert evidence["verdict"] == "keep_baseline"
    assert evidence["runtime_verified"] is False and evidence["holdout_verified"] is False
    from modstore_server.retort_training_candidates import _candidate

    bundle = json.loads(bundle_path.read_bytes())
    with pytest.raises(ValueError, match="training_candidate_not_improved"):
        _candidate(
            {
                "bundle_json": bundle_path.read_text(),
                "result_json": output.read_text(),
                "files": {name: Path(built[name]).read_text() for name in bundle["files"]},
            }
        )
    command = subprocess.run(
        [
            sys.executable,
            "-m",
            "modstore_server.capability_trainer",
            "decide",
            "--bundle",
            str(bundle_path),
            "--result",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert command.returncode == 0, command.stderr[-4000:]
    result = json.loads(command.stdout)
    assert result["verdict"] == "keep_baseline" and result["runtime_verified"] is False


def test_claimed_all_pass_is_overruled_by_real_native_wrong_cells(tmp_path, monkeypatch):
    _built, bundle_path, output = _claimed_pass_bundle(tmp_path, monkeypatch)
    evidence = trainer.seal_evaluation(bundle_path, output)
    assert evidence["runtime_verified"] is True
    assert evidence["verdict"] == "keep_baseline" and evidence["holdout_verified"] is False
    assert evidence["baseline"] == {"pass": 0, "total": 2}
    assert evidence["candidate"] == {"pass": 0, "total": 2}
