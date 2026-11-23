"""Original native employee execution and independent CSV/Excel bytes, without a model."""

from __future__ import annotations

import csv
import io
import json
import os
import socket
import subprocess
import sys
import time
import zipfile
from copy import deepcopy
from pathlib import Path

import psutil
import pytest
from openpyxl import Workbook

from modstore_server import workflow_training_replay as replay
from modstore_server.employee_runtime import parse_employee_config_v2
from modstore_server.workflow_nl_training import get_assert


def _fixture(kind="csv", *, wrong_reference=False, module_suffix="", order="A-1"):
    employee = f"{kind}-generate-employee"
    root = Path(__file__).resolve().parents[3] / "FHD/mods/_employees" / employee
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["employee_config_v2"]["workspace_policy"] = {
        "scope_globs": ["inputs/**", "outputs/**"],
        "forbidden_globs": ["**/.env"],
    }
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(root.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                member = f"{employee}/{path.relative_to(root).as_posix()}"
                raw = (
                    json.dumps(manifest).encode()
                    if path.name == "manifest.json"
                    else path.read_bytes()
                )
                if path.name == manifest["actions"]["direct_python"]["module"] + ".py":
                    raw += module_suffix.encode()
                bundle.writestr(
                    member,
                    raw,
                )
    config = parse_employee_config_v2(manifest)
    package = {
        **replay._blob(employee + ".xcemp", archive.getvalue()),
        "employee_id": employee,
        "version": manifest["version"],
        "manifest": manifest,
        "effective_config": config,
        "runtime_policy": {},
    }
    inputs = {"file_path": "/original/customer/inputs/order.json"}
    payload = json.dumps(
        {"columns": ["order", "quantity"], "rows": [{"order": order, "quantity": 3}]}
    ).encode()
    if kind == "csv":
        output_path = "outputs/output.csv"
        expected = f"order,quantity\r\n{order},{99 if wrong_reference else 3}\r\n".encode()
    else:
        output_path = "outputs/output.xlsx"
        book = Workbook()
        sheet = book.active
        sheet.title = "Sheet1"
        sheet.append(["order", "quantity"])
        sheet.append([order, 99 if wrong_reference else 3])
        buffer = io.BytesIO()
        book.save(buffer)
        expected = buffer.getvalue()
    assets = {
        "input_data": inputs,
        "workspace": "/original/customer",
        "employee_ids": [employee],
        "input_files": [replay._blob("inputs/order.json", payload)],
        "packages": [package],
        "expected_files": [replay._blob(output_path, expected)],
    }
    contract = {
        "execution_id": 11,
        "workflow_id": 13,
        "user_id": 7,
        "graph_fingerprint": "f" * 64,
        "execution_input_sha256": replay._digest(inputs),
        "node_id": 23,
        "employee_id": employee,
        "node_input": {"file_path": inputs["file_path"]},
        "execution_binding": {
            "archive_sha256": package["sha256"],
            "config_sha256": replay._digest(config),
            "manifest_sha256": replay._digest(manifest),
            "version": package["version"],
        },
    }
    frozen = {
        "schema": replay.ASSETS_SCHEMA,
        "replay_ready": True,
        "assets": assets,
        "source_group_sha256": replay.source_group_sha256({"assets": assets, "contract": contract}),
    }
    binding = {
        key: contract[key]
        for key in ("execution_id", "workflow_id", "user_id", "graph_fingerprint")
    }
    binding["customer_delivery"] = {
        **contract,
        "business_replay": frozen,
        "contract_sha256": replay._digest({**contract, "business_replay": frozen}),
    }
    portable = replay.export_customer_replay(binding, inputs, "e" * 64)
    source = {
        "graph": {
            "name": "Independent file replay",
            "nodes": [],
            "edges": [],
            "triggers": [],
        },
        "skills": [],
        "brief": "Generate the order file from confirmed JSON",
        "customer_business_replay": portable,
        "execution_feedback": {"measurement_scope": "workflow_customer_accepted_outcome"},
    }
    graph = {
        "nodes": [
            {"temp_id": "s", "node_type": "start", "config": {}},
            {
                "temp_id": "n",
                "node_type": "employee",
                "config": {
                    "employee_id": employee,
                    "task": "Generate the confirmed order file",
                    "input_mapping": {"file_path": "{{global.file_path}}"},
                },
            },
            {"temp_id": "e", "node_type": "end", "config": {}},
        ],
        "edges": [
            {"source_temp_id": "s", "target_temp_id": "n"},
            {"source_temp_id": "n", "target_temp_id": "e"},
        ],
    }
    return source, graph, binding


@pytest.mark.parametrize("kind", ["csv", "excel"])
def test_real_native_employee_and_independent_file_check(kind, monkeypatch):
    source, graph, _ = _fixture(kind)
    original = replay._run_worker

    def run(request, directory, env):
        # Gold is not in the worker request/environment, and the child has no live credentials.
        assert "expected_files" not in request["assets"]
        assert "customer_business_replay" not in request["source"]
        assert "XCAGI_LLM_API_KEY" not in env
        result = original(request, directory, env)
        assert result.returncode == 0, result.stderr[-7000:]
        return result

    monkeypatch.setattr(replay, "_run_worker", run)
    result = get_assert(json.dumps(graph), {"vars": {"generation_context": source}})
    assert result["pass"], result
    assert result["runtime_verified"] is True
    assert result["measurement_scope"] == replay.WORKFLOW_BUSINESS_MEASUREMENT
    assert result["business_evidence"]["output_sha256"]


def test_successful_native_run_with_wrong_cells_fails_business_assertion():
    source, graph, _ = _fixture("excel", wrong_reference=True)
    result = get_assert(json.dumps(graph), {"vars": {"generation_context": source}})
    assert result["runtime_verified"] is True
    assert result["pass"] is False
    assert result["reason"] == "training_business_artifact_mismatch"


@pytest.mark.parametrize("entry", ["seal", "cli"])
def test_native_replay_cannot_read_host_oracle_write_outside_or_use_network(
    tmp_path, monkeypatch, entry
):
    from modstore_server import capability_trainer as trainer

    oracle = tmp_path / "parent-only-oracle.txt"
    outside = tmp_path / "outside-write.txt"
    oracle.write_text("independent reference must remain outside the worker")
    monkeypatch.setenv("XCAGI_LLM_MODEL", "unused-fixture")
    monkeypatch.setenv("XCAGI_LLM_BASE_URL", "https://unused.invalid/v1")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        # This is an approved, hash-bound original package with a production-like
        # import side effect, not code supplied by the candidate workflow graph.
        probe = f"""
from pathlib import Path as _ProbePath
import socket as _probe_socket
_escaped = []
try:
    _ProbePath({str(oracle)!r}).read_text()
    _escaped.append('host_oracle')
except OSError:
    pass
try:
    _ProbePath({str(outside)!r}).write_text('native import side effect')
    _escaped.append('outside_write')
except OSError:
    pass
try:
    with _probe_socket.create_connection(('127.0.0.1', {listener.getsockname()[1]}), timeout=1):
        _escaped.append('localhost')
except OSError:
    pass
if _escaped:
    raise RuntimeError('training replay escaped: ' + ','.join(_escaped))
"""
        partitions = {}
        for number in range(100):
            source, graph, _ = _fixture(module_suffix=probe, order=f"isolation-{number}")
            frozen = source["customer_business_replay"]
            replay.validate_replay_manifest(frozen)
            source_sha = frozen["assets"]["input_files"][0]["sha256"]
            partitions.setdefault(
                int(source_sha[:8], 16) % 5 == 0,
                {"task": f"Generate isolation-{number}", "generation_context": source},
            )
            if len(partitions) == 2:
                break
        assert len(partitions) == 2
        built = trainer.build_config(
            out_dir=tmp_path,
            baseline_prompt="original",
            candidate_prompt="candidate",
            cases=list(partitions.values()),
            surface="workflow_nl_prompt",
        )
        bundle = json.loads(Path(built["bundle"]).read_text())
        tests = json.loads(Path(built["tests"]).read_text())
        result = tmp_path / "result.json"
        result.write_text(
            json.dumps(
                {
                    "metadata": {"promptfooVersion": trainer.PROMPTFOO_VERSION},
                    "results": {
                        "prompts": [
                            {"raw": Path(built[key]).read_text()}
                            for key in ("baseline", "candidate")
                        ],
                        "results": [
                            {
                                "promptIdx": arm,
                                "testIdx": index,
                                "success": True,
                                "failureReason": 0,
                                "gradingResult": {"pass": True, "score": 1, "reason": "fixture"},
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
        error = None
        if entry == "seal":
            try:
                sealed = trainer.seal_evaluation(Path(built["bundle"]), result)
            except ValueError as exc:
                error = str(exc)
        else:
            process = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "modstore_server.capability_trainer",
                    "decide",
                    "--bundle",
                    built["bundle"],
                    "--result",
                    str(result),
                ],
                capture_output=True,
                text=True,
                timeout=180,
            )
            error = process.stderr if process.returncode else None
            if error is None:
                sealed = json.loads(process.stdout)
        assert not outside.exists(), "native replay wrote outside its temporary root"
        listener.settimeout(0.05)
        with pytest.raises(socket.timeout):
            connection, _ = listener.accept()
            connection.close()
        assert error is None, error
        assert sealed["runtime_verified"] is True
        assert sealed["candidate"] == {"pass": 2, "total": 2}


def test_native_replay_without_sandbox_cannot_be_verified(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMPTFOO_SANDBOX_ENTRY", str(tmp_path / "missing-cli.js"))
    source, graph, _ = _fixture()
    result = get_assert(json.dumps(graph), {"vars": {"generation_context": source}})
    assert result["pass"] is False
    assert result["runtime_verified"] is False
    assert result["reason"] == "training_business_replay_blocked"


def test_missing_original_snapshot_cannot_be_provider_verified():
    source, graph, binding = _fixture()
    binding["customer_delivery"].pop("business_replay")
    source["customer_business_replay"] = replay.export_customer_replay(
        binding, {"file_path": "untrusted"}, "e" * 64
    )
    result = get_assert(
        json.dumps({**graph, "ok": True, "sandbox_ok": True, "runtime_verified": True}),
        {"vars": {"generation_context": source}},
    )
    assert result["pass"] is False
    assert result["runtime_verified"] is False


def test_source_drift_and_reference_drift_are_rejected():
    source, _, _ = _fixture()
    for field in ("input_files", "expected_files", "packages"):
        changed = deepcopy(source["customer_business_replay"])
        changed["assets"][field][0]["base64"] = "Zm9yZ2Vk"
        with pytest.raises(ValueError):
            replay.validate_replay_manifest(changed)


def test_source_group_survives_rename_duplicate_and_new_execution_identity():
    source, _, _ = _fixture()
    original = source["customer_business_replay"]
    changed = deepcopy(original)
    changed["assets"]["input_files"][0]["path"] = "inputs/renamed.json"
    changed["contract"]["node_input"]["file_path"] = "inputs/renamed.json"
    changed["assets"]["input_files"].append(deepcopy(changed["assets"]["input_files"][0]))
    changed["execution_id"] = 999
    assert replay.source_group_sha256(changed) == replay.source_group_sha256(original)


def test_template_changes_do_not_move_original_business_source_between_splits():
    source, _, _ = _fixture()
    original = source["customer_business_replay"]
    changed = deepcopy(original)
    changed["assets"]["input_files"].append(
        replay._blob("inputs/template.json", b'{"format":"new"}')
    )
    changed["contract"]["node_input"]["template_relpath"] = "inputs/template.json"
    assert replay.source_group_sha256(changed) == replay.source_group_sha256(original)
    assert replay.validate_replay_manifest(original)["source_sha256"] == [
        original["assets"]["input_files"][0]["sha256"]
    ]


def test_deferred_node_still_groups_its_independent_original_file():
    source, _, _ = _fixture()
    manifest = source["customer_business_replay"]
    first = deepcopy(manifest["contract"])
    manifest["assets"]["input_files"].append(replay._blob("inputs/other.json", b'{"value":2}'))
    manifest["assets"]["input_data"]["other"] = "inputs/other.json"
    second = {
        **first,
        "node_input": None,
        "deferred_input_mapping": {
            "file_path": "{{global.other}}",
            "note": "{{nodes.prev.output.note}}",
        },
    }
    manifest["contract"] = {"nodes": [first, second]}
    assert replay._source_hashes(manifest) == sorted(
        item["sha256"] for item in manifest["assets"]["input_files"]
    )


def test_candidate_cannot_swap_employee_or_execute_code():
    source, graph, _ = _fixture()
    graph["nodes"][1]["node_type"] = "code"
    graph["nodes"][1]["config"] = {"code": "print('fake')"}
    result = get_assert(json.dumps(graph), {"vars": {"generation_context": source}})
    assert result["pass"] is False
    assert result["runtime_verified"] is False


@pytest.mark.parametrize("field", ["output_relpath", "customer_deliverables"])
def test_candidate_cannot_add_output_paths_outside_original_contract(field):
    source, graph, _ = _fixture()
    config = graph["nodes"][1]["config"]
    if field == "output_relpath":
        config["input_mapping"][field] = "outputs/unapproved.csv"
    else:
        config[field] = ["outputs/output.csv", "outputs/unapproved.csv"]
    result = get_assert(json.dumps(graph), {"vars": {"generation_context": source}})
    assert result["pass"] is False
    assert result["runtime_verified"] is False


@pytest.mark.parametrize("value", [None, [], "bad"])
def test_nonobject_manifest_fails_closed(value):
    with pytest.raises((ValueError, TypeError)):
        replay.validate_replay_manifest(value)


@pytest.mark.parametrize("field", ["file_path", "output_relpath", "template_relpath"])
def test_resolved_dynamic_paths_cannot_escape_frozen_workspace(field):
    source, graph, _ = _fixture()
    manifest = source["customer_business_replay"]
    manifest["assets"]["input_data"]["unused_path"] = "/etc/hostname"
    manifest["input_sha256"] = replay._digest(manifest["assets"]["input_data"])
    manifest["contract"]["execution_input_sha256"] = manifest["input_sha256"]
    captured = {
        "schema": replay.ASSETS_SCHEMA,
        "replay_ready": True,
        "source_group_sha256": manifest["source_group_sha256"],
        "assets": manifest["assets"],
    }
    manifest["contract_sha256"] = replay._digest(
        {**manifest["contract"], "business_replay": captured}
    )
    graph["nodes"][1]["config"]["input_mapping"][field] = "{{global.unused_path}}"
    result = get_assert(json.dumps(graph), {"vars": {"generation_context": source}})
    assert result["pass"] is False
    assert result["runtime_verified"] is False


def test_formula_without_independent_calculated_value_is_not_verified():
    workbook = Workbook()
    workbook.active["A1"] = "=1+1"
    buffer = io.BytesIO()
    workbook.save(buffer)
    with pytest.raises(ValueError, match="formula_value_unverified"):
        replay._equal_files("result.xlsx", buffer.getvalue(), buffer.getvalue())


@pytest.mark.parametrize("delimiter", [";", "\t"])
def test_csv_reference_dialect_rejects_quoted_single_column(delimiter):
    expected = f"a{delimiter}b\n1{delimiter}2\n".encode()
    actual = f'"a{delimiter}b"\n"1{delimiter}2"\n'.encode()
    assert replay._equal_files("result.csv", actual, expected) is False


@pytest.mark.parametrize("delimiter", [",", ";", "\t", "|"])
def test_csv_reference_dialect_accepts_equivalent_quoting_and_record_newlines(delimiter):
    rows = [["label", "amount"], [f'café{delimiter} "quoted"', "2"]]
    expected, actual = io.StringIO(newline=""), io.StringIO(newline="")
    csv.writer(expected, delimiter=delimiter, lineterminator="\n").writerows(rows)
    csv.writer(actual, delimiter=delimiter, quoting=csv.QUOTE_ALL, lineterminator="\r\n").writerows(
        rows
    )
    assert (
        replay._equal_files(
            "result.csv", actual.getvalue().encode("utf-8-sig"), expected.getvalue().encode()
        )
        is True
    )


@pytest.mark.parametrize("expected", [b"header\nvalue\n", b"a,b;c\n1,2;3\n"])
def test_csv_undetected_or_ambiguous_reference_only_accepts_exact_bytes(expected):
    assert replay._equal_files("result.csv", expected, expected) is True
    assert replay._equal_files("result.csv", expected.replace(b"\n", b"\r\n"), expected) is False


def test_csv_reference_dialect_rejects_malformed_quoted_candidate():
    assert replay._equal_files("result.csv", b'a;b\n"1;2\n', b"a;b\n1;2\n") is False


def test_csv_reference_dialect_preserves_literal_cell_whitespace():
    assert replay._equal_files("result.csv", b"a;b\n1;2\n", b"a; b\n1; 2\n") is False


def test_csv_reference_dialect_accepts_standard_doubled_quote_escapes():
    expected = b'a;b\nhe said "hi";2\n'
    actual = b'"a";"b"\r\n"he said ""hi""";"2"\r\n'
    assert replay._equal_files("result.csv", actual, expected) is True


def test_csv_existing_native_fixture_keeps_its_content_comparison():
    source, _, _ = _fixture("csv")
    expected = replay._bytes(source["customer_business_replay"]["assets"]["expected_files"][0])
    assert replay._equal_files("result.csv", b'"order","quantity"\n"A-1","3"\n', expected) is True


@pytest.mark.skipif(os.name != "posix", reason="POSIX process group contract")
def test_timeout_reaps_worker_descendants(tmp_path, monkeypatch):
    original = subprocess.Popen
    pid_file = tmp_path / "descendant.pid"
    script = (
        "import pathlib,subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid)); time.sleep(30)"
    )

    def start(args, **kwargs):
        return original([sys.executable, "-c", script], **kwargs)

    monkeypatch.setattr(subprocess, "Popen", start)
    # This test owns a real timed-out process tree; the native sandbox boundary is
    # exercised separately above, so its configuration helper creates no child here.
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args,
            0,
            json.dumps(
                {
                    "node": sys.executable,
                    "runtime": "fixture-cli.js",
                    "policy": {"filesystem": {"allowRead": []}},
                }
            ),
            "",
        ),
    )
    with pytest.raises(subprocess.TimeoutExpired):
        replay._run_worker({}, tmp_path, dict(os.environ), timeout=1)
    child = int(pid_file.read_text())
    deadline = time.monotonic() + 2
    while True:
        try:
            state = psutil.Process(child).status()
        except psutil.NoSuchProcess:
            break
        if state in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}:
            break
        if time.monotonic() >= deadline:
            pytest.fail(f"descendant {child} survived worker timeout with status {state}")
        time.sleep(0.02)
