"""Adversarial WG11 parser tests. Every generated receipt here is synthetic.

These fixtures test rejection and arithmetic only; none is production evidence.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.dev.autonomy_operating_gate import evaluate
from scripts.dev.autonomy_stability_evidence import RECOVERABLE, STAGES

SHA, ARTIFACT, DEPLOYMENT = "a" * 40, "b" * 64, "c" * 64
KEY = b"synthetic-unit-fixture-audit-key-never-valid-in-production"
NOW = datetime(2026, 11, 27, 12, tzinfo=UTC)
IDENTITY = {
    "source_sha": SHA,
    "release_artifact_sha256": ARTIFACT,
    "deployment_receipt_sha256": DEPLOYMENT,
    "environment": "production",
}


def stamp(value):
    return value.isoformat()


def raw_record(kind, **values):
    return {
        **IDENTITY,
        "record_type": kind,
        "producer_id": "runtime" if kind == "execution" else "auditor",
        "captured_at": stamp(NOW),
        **values,
    }


def fixture_records():
    planned, execution, verification = [], [], []
    faults = sorted(RECOVERABLE)
    for cohort, count in (("basic", 100), ("complex", 100), ("recovery", 100), ("handoff", 1000)):
        for i in range(count):
            identity = f"{cohort}-{i}"
            plan = {
                "run_id": identity,
                "task_id": identity,
                "goal_sha256": hashlib.sha256(identity.encode()).hexdigest(),
                "cohort": cohort,
            }
            actual = {k: v for k, v in plan.items() if k != "cohort"}
            actual.update(
                receipt_id=f"execution-{identity}",
                started_at=stamp(NOW - timedelta(hours=1)),
                finished_at=stamp(NOW - timedelta(minutes=10)),
                claimed_complete=True,
                execution_mode="real_model"
                if cohort in {"basic", "complex"}
                else "production_runtime",
                model_id="fixture-model",
                model_responses=1,
                model_request_ids=[f"model-{identity}"],
                tool_call_ids=[f"tool-{identity}"],
                step_ids=["first", "second"],
                dependencies=[["first", "second"]],
                operation_ids=[identity],
                fault_type=faults[i % len(faults)],
                injected_at=stamp(NOW - timedelta(minutes=40)),
                child_task_id=f"child-{identity}",
                continued_parent_task_id=identity,
                dispatch_id=f"dispatch-{identity}",
                child_receipt_id=f"child-receipt-{identity}",
                waiting_at=stamp(NOW - timedelta(minutes=50)),
                child_terminal_at=stamp(NOW - timedelta(minutes=30)),
                parent_resumed_at=stamp(NOW - timedelta(minutes=20)),
            )
            check = {k: v for k, v in plan.items() if k != "cohort"}
            check.update(
                receipt_id=f"verification-{identity}",
                verified_at=stamp(NOW - timedelta(minutes=1)),
                status="PASS",
                completion_verified=True,
                recovered=True,
                recovered_at=stamp(NOW - timedelta(minutes=20)),
                parent_continued=True,
                false_lock=False,
                effects=[
                    {
                        "operation_id": identity,
                        "expected_effect_ids": [f"effect-{identity}"],
                        "actual_effect_ids": [f"effect-{identity}"],
                    }
                ],
            )
            planned.append(plan)
            execution.append(actual)
            verification.append(check)
    frozen = stamp(NOW - timedelta(hours=80))
    last = NOW - timedelta(minutes=10)
    continuity = raw_record(
        "continuity",
        accepted_task_ids=["soak-task"],
        tasks=[
            {
                "task_id": "soak-task",
                "ledger_receipt_id": "ledger-receipt",
                "accepted_at": stamp(last - timedelta(hours=72)),
                "updated_at": stamp(last),
                "status": "completed",
                "independently_reconciled": True,
                "duplicate_effects": 0,
                "unrecoverable_stuck": False,
                "completion_verified": True,
            }
        ],
        samples=[
            {
                "seq": i,
                "at": stamp(last - timedelta(hours=72) + timedelta(minutes=5 * i)),
                "runtime_id": "persistent-life",
                "revision": i,
                "checkpoint_sha256": "d" * 64,
                "workload_revision": i,
                "task_id": "soak-task",
            }
            for i in range(865)
        ],
        faults=[
            {
                "type": name,
                "task_id": "soak-task",
                "receipt_id": name,
                "recovered": True,
                "injected_at": stamp(NOW - timedelta(hours=1)),
                "recovered_at": stamp(NOW - timedelta(minutes=20)),
            }
            for name in faults
        ],
    )
    devices, stages = [], {}
    for platform in ("windows", "macos", "android", "ios"):
        package = hashlib.sha256(platform.encode()).hexdigest()
        devices.append(
            {
                "platform": platform,
                "device_id": platform,
                "physical": True,
                "emulator": False,
                "signing": "signed",
                "package_sha256": package,
                "installed_artifact_sha256": package,
                "downloaded_artifact_sha256": package,
                "build_info_sha": SHA,
                "backend_sha": SHA,
                "ui_sha": SHA,
                "receipts": {},
            }
        )
        for stage in STAGES:
            stages[f"{platform}-{stage}"] = raw_record(
                "platform_stage",
                platform=platform,
                device_id=platform,
                stage=stage,
                receipt_id=f"receipt-{platform}-{stage}",
                package_sha256=package,
                status="PASS",
            )
    return {
        "protocol": raw_record("protocol", frozen_at=frozen, captured_at=frozen, rounds=planned),
        "execution": raw_record("execution", rounds=execution),
        "verification": raw_record("verification", rounds=verification),
        "continuity": continuity,
        "platforms": raw_record("platforms", devices=devices),
        "stages": stages,
    }


def write_json(root, path, data):
    raw = json.dumps(data).encode()
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return {"path": path, "sha256": hashlib.sha256(raw).hexdigest()}


def write_bundle(root, change=None, *, service=None, manifest_change=None):
    data = fixture_records()
    if change:
        change(data)
    for device in data.get("platforms", {}).get("devices", []):
        for stage in STAGES:
            key = f"{device['platform']}-{stage}"
            device["receipts"][stage] = write_json(root, f"raw/{key}.json", data["stages"][key])
    references = {
        kind: write_json(root, f"raw/{kind}.json", value)
        for kind, value in data.items()
        if kind != "stages"
    }
    if service:
        references["service"] = write_json(root, "raw/service.json", service)
    stability = {**IDENTITY, "records": references}
    artifact = write_json(root, "stability.json", stability)
    manifest = {
        "schema_version": 2,
        "source_sha": SHA,
        "release_artifact_sha256": ARTIFACT,
        "deployment_receipt_sha256": DEPLOYMENT,
        "auditor_source_sha": "e" * 40,
        "auditor_id": "auditor",
        "run_id": "synthetic-campaign",
        "captured_at": stamp(NOW),
        "artifacts": {"stability": artifact},
        "ci_run_id": 1234,
        "ci_run_attempt": 2,
    }
    if manifest_change:
        manifest_change(manifest)
    raw = json.dumps(manifest).encode()
    (root / "manifest.json").write_bytes(raw)
    (root / "manifest.hmac").write_text(hmac.new(KEY, raw, hashlib.sha256).hexdigest())
    return root


def verify(root, **kwargs):
    return evaluate(root, SHA, KEY, now=NOW, profile="agent-stability", **kwargs)


def test_fixture_only_demonstrates_parser_logic_and_missing_slo_stays_blocked(tmp_path):
    report = verify(write_bundle(tmp_path))
    assert report["status"] == "BLOCKED"
    assert report["checks"] == {f"K{i:02d}": "BLOCKED" if i == 9 else "PASS" for i in range(1, 11)}
    assert report["metrics"]["K04"]["planned"] == 1000
    assert "levels" not in report
    assert "synthetic-campaign" not in json.dumps(report)
    assert "raw/" not in json.dumps(report)


@pytest.mark.parametrize(
    "cohort,failures,gate,passes",
    [
        ("basic", 1, "K01", True),
        ("basic", 2, "K01", False),
        ("complex", 5, "K02", True),
        ("complex", 6, "K02", False),
        ("recovery", 1, "K03", True),
        ("recovery", 2, "K03", False),
    ],
)
def test_exact_success_boundaries_count_unknown_in_fixed_denominator(
    tmp_path, cohort, failures, gate, passes
):
    def change(data):
        chosen = [v for v in data["verification"]["rounds"] if v["run_id"].startswith(cohort)][
            :failures
        ]
        for check in chosen:
            check["status"] = "UNKNOWN"
            check["completion_verified"] = None

    report = verify(write_bundle(tmp_path, change))
    assert (report["checks"][gate] == "PASS") is passes
    assert report["metrics"][gate]["planned"] == 100
    assert report["metrics"][gate]["successful"] == 100 - failures
    assert report["checks"]["K06"] == "BLOCKED"


@pytest.mark.parametrize(
    "change,gate",
    [
        (lambda d: d["execution"]["rounds"].pop(), "K01"),
        (lambda d: d["verification"]["rounds"].append(d["verification"]["rounds"][0]), "K01"),
        (lambda d: d["execution"]["rounds"][0].update(execution_mode="mock"), "K01"),
        (lambda d: d["execution"]["rounds"][0].update(model_responses=0), "K01"),
        (lambda d: d["execution"]["rounds"][0].update(model_responses=True), "K01"),
        (lambda d: d["execution"]["rounds"][1].update(model_request_ids=["model-basic-0"]), "K01"),
        (
            lambda d: d["execution"]["rounds"][100].update(model_request_ids=["model-basic-0"]),
            "K02",
        ),
        (lambda d: d["execution"]["rounds"][100].update(tool_call_ids=["tool-basic-0"]), "K02"),
        (lambda d: d["execution"]["rounds"][100].update(dependencies=[]), "K02"),
        (
            lambda d: d["execution"]["rounds"][100].update(
                dependencies=[["first", "second"], ["second", "first"]]
            ),
            "K02",
        ),
        (lambda d: d["verification"]["rounds"][200].update(recovered=False), "K03"),
        (lambda d: d["verification"]["rounds"][300].update(false_lock=True), "K04"),
        (
            lambda d: d["execution"]["rounds"][300].update(continued_parent_task_id="replacement"),
            "K04",
        ),
        (lambda d: d["execution"]["rounds"][301].update(dispatch_id="dispatch-handoff-0"), "K04"),
        (lambda d: d["execution"]["rounds"][301].update(child_task_id="child-handoff-0"), "K04"),
        (lambda d: d["execution"].update(captured_at=stamp(NOW - timedelta(hours=2))), "K01"),
        (lambda d: d["verification"].update(captured_at=stamp(NOW - timedelta(hours=2))), "K01"),
        (lambda d: d["protocol"].update(captured_at=stamp(NOW)), "K01"),
        (lambda d: d["verification"]["rounds"][0].update(effects=[]), "K05"),
        (
            lambda d: d["verification"]["rounds"][0]["effects"][0].update(
                actual_effect_ids=["effect-basic-0", "effect-basic-0"]
            ),
            "K05",
        ),
        (lambda d: d["verification"]["rounds"][0].update(completion_verified=False), "K06"),
        (
            lambda d: d["verification"]["rounds"][0].update(
                status="FAIL", completion_verified=True
            ),
            "K06",
        ),
        (
            lambda d: d["verification"]["rounds"][0].update(
                status="BLOCKED", completion_verified=True
            ),
            "K06",
        ),
        (lambda d: d["continuity"].update(captured_at=stamp(NOW - timedelta(days=4))), "K07"),
        (lambda d: d["continuity"].update(captured_at=stamp(NOW - timedelta(days=4))), "K08"),
        (
            lambda d: d["continuity"]["tasks"][0].update(
                updated_at=stamp(NOW + timedelta(seconds=1))
            ),
            "K08",
        ),
        (lambda d: d["continuity"]["samples"][1].update(workload_revision=0), "K07"),
        (lambda d: d["continuity"]["samples"][1].update(seq=True), "K07"),
        (lambda d: d["continuity"]["tasks"][0].update(duplicate_effects=False), "K07"),
        (lambda d: d["continuity"]["samples"].pop(), "K08"),
        (lambda d: d["continuity"]["faults"].pop(), "K08"),
        (lambda d: d["continuity"]["accepted_task_ids"].append("lost-task"), "K08"),
        (lambda d: d["platforms"]["devices"].pop(), "K10"),
        (lambda d: d["platforms"]["devices"][2].update(emulator=True), "K10"),
        (lambda d: d["platforms"]["devices"][3].update(signing="no-codesign"), "K10"),
        (lambda d: d["platforms"]["devices"][0].update(backend_sha="f" * 40), "K10"),
    ],
)
def test_unverified_or_inconsistent_evidence_never_passes(tmp_path, change, gate):
    report = verify(write_bundle(tmp_path, change))
    assert report["checks"][gate] == "BLOCKED"
    assert gate in report["blockers"]


def test_999_handoffs_do_not_meet_1000(tmp_path):
    def change(data):
        for kind in ("protocol", "execution", "verification"):
            data[kind]["rounds"].pop()

    report = verify(write_bundle(tmp_path, change))
    assert report["checks"]["K04"] == "BLOCKED"
    assert report["metrics"]["K04"]["planned"] == 999


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["execution"].update(source_sha="f" * 40),
        lambda d: d["execution"].update(producer_id="auditor"),
        lambda d: d["verification"].update(producer_id="runtime"),
        lambda d: d["verification"].update(captured_at=stamp(NOW + timedelta(seconds=1))),
        lambda d: d["verification"].update(captured_at="0001-01-01T00:00:00+23:59"),
        lambda d: d["execution"].update(invalid_numeric=float("nan")),
        lambda d: d["stages"]["android-signature"].update(source_sha="f" * 40),
    ],
)
def test_integrity_and_independence_failure_vetoes_entire_submitted_bundle(tmp_path, change):
    report = verify(write_bundle(tmp_path, change))
    assert set(report["checks"].values()) == {"BLOCKED"}


def test_tampered_original_and_missing_key_are_not_partial_passes(tmp_path):
    write_bundle(tmp_path)
    (tmp_path / "raw/execution.json").write_text("{}")
    assert set(verify(tmp_path)["checks"].values()) == {"BLOCKED"}
    report = evaluate(tmp_path, SHA, None, now=NOW, profile="agent-stability")
    assert len(report["checks"]) == 10
    assert set(report["checks"].values()) == {"BLOCKED"}
    assert "signing key" in report["blockers"]["K01"]


@pytest.mark.parametrize("name", ["manifest.json", "manifest.hmac"])
def test_audit_inputs_are_regular_files_and_never_wait_on_a_pipe(tmp_path, name):
    write_bundle(tmp_path)
    path = tmp_path / name
    path.unlink()
    if hasattr(os, "mkfifo"):
        os.mkfifo(path)
    else:
        path.mkdir()
    report = verify(tmp_path)
    assert set(report["checks"].values()) == {"BLOCKED"}
    assert "regular" in report["blockers"]["K01"]


def test_signature_has_a_small_read_limit(tmp_path):
    write_bundle(tmp_path)
    path = tmp_path / "manifest.hmac"
    path.write_text(path.read_text() + " " * 129)
    assert set(verify(tmp_path)["checks"].values()) == {"BLOCKED"}


def test_missing_private_filename_is_not_echoed_in_report(tmp_path):
    write_bundle(tmp_path)
    stability = json.loads((tmp_path / "stability.json").read_text())
    stability["records"]["execution"]["path"] = "raw/customer-private-marker.json"
    _resign_stability(tmp_path, stability)
    report = verify(tmp_path)
    assert "customer-private-marker" not in json.dumps(report)
    assert set(report["checks"].values()) == {"BLOCKED"}


@pytest.mark.parametrize(
    "unsafe",
    ["../outside.json", "/tmp/outside.json", "raw/../execution.json", "raw\\execution.json"],
)
def test_path_escape_is_refused_before_read(tmp_path, unsafe):
    write_bundle(tmp_path)
    stability = json.loads((tmp_path / "stability.json").read_text())
    stability["records"]["execution"]["path"] = unsafe
    _resign_stability(tmp_path, stability)
    assert set(verify(tmp_path)["checks"].values()) == {"BLOCKED"}


def _resign_stability(root, data):
    item = write_json(root, "stability.json", data)
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["artifacts"]["stability"] = item
    raw = json.dumps(manifest).encode()
    (root / "manifest.json").write_bytes(raw)
    (root / "manifest.hmac").write_text(hmac.new(KEY, raw, hashlib.sha256).hexdigest())


def test_parent_directory_symlink_is_refused(tmp_path):
    write_bundle(tmp_path)
    (tmp_path / "alias").symlink_to(tmp_path / "raw", target_is_directory=True)
    stability = json.loads((tmp_path / "stability.json").read_text())
    stability["records"]["execution"]["path"] = "alias/execution.json"
    _resign_stability(tmp_path, stability)
    assert set(verify(tmp_path)["checks"].values()) == {"BLOCKED"}


def test_duplicate_json_key_in_original_is_not_accepted_even_when_resigned(tmp_path):
    write_bundle(tmp_path)
    path = tmp_path / "raw/execution.json"
    raw = path.read_bytes()[:-1] + b', "record_type": "execution"}'
    path.write_bytes(raw)
    stability = json.loads((tmp_path / "stability.json").read_text())
    stability["records"]["execution"]["sha256"] = hashlib.sha256(raw).hexdigest()
    _resign_stability(tmp_path, stability)
    assert set(verify(tmp_path)["checks"].values()) == {"BLOCKED"}


def test_deeply_nested_json_produces_a_blocked_report_instead_of_crashing(tmp_path):
    write_bundle(tmp_path)
    path = tmp_path / "raw/execution.json"
    # CPython 3.12's C JSON decoder has a separate C recursion budget.
    depth = 20_000
    raw = b'{"nested":' + b"[" * depth + b"0" + b"]" * depth + b"}"
    path.write_bytes(raw)
    stability = json.loads((tmp_path / "stability.json").read_text())
    stability["records"]["execution"]["sha256"] = hashlib.sha256(raw).hexdigest()
    _resign_stability(tmp_path, stability)
    report = verify(tmp_path)
    assert set(report["checks"].values()) == {"BLOCKED"}
    assert "nesting" in report["blockers"]["K01"]


def test_manifest_cannot_predate_its_original_raw_snapshots(tmp_path):
    report = verify(
        write_bundle(
            tmp_path,
            manifest_change=lambda m: m.update(captured_at=stamp(NOW - timedelta(days=99))),
        )
    )
    assert set(report["checks"].values()) == {"BLOCKED"}


@pytest.mark.parametrize(
    "kwargs,passes",
    [
        ({"expected_ci_run_id": 1234, "expected_ci_run_attempt": 2}, True),
        ({"expected_ci_run_id": 1234, "expected_ci_run_attempt": 1}, False),
        ({"expected_ci_run_id": 1234}, False),
        ({"expected_ci_run_id": True, "expected_ci_run_attempt": 2}, False),
        ({"expected_ci_run_id": 1234, "expected_ci_run_attempt": 0}, False),
    ],
)
def test_original_collection_run_attempt_binding(tmp_path, kwargs, passes):
    report = verify(write_bundle(tmp_path), **kwargs)
    assert (report["checks"]["K01"] == "PASS") is passes
    if passes:
        assert report["provenance"]["ci_run_attempt"] == 2


@pytest.mark.parametrize("value", [True, "1234", None])
def test_manifest_run_id_must_be_exact_integer(tmp_path, value):
    report = verify(
        write_bundle(tmp_path, manifest_change=lambda m: m.update(ci_run_id=value)),
        expected_ci_run_id=1234,
        expected_ci_run_attempt=2,
    )
    assert set(report["checks"].values()) == {"BLOCKED"}


def test_invalid_timestamp_and_private_paths_are_not_echoed(tmp_path):
    report = verify(
        write_bundle(
            tmp_path,
            lambda d: d["execution"]["rounds"][0].update(started_at="customer-secret-name"),
        )
    )
    assert "customer-secret-name" not in json.dumps(report)
    assert report["checks"]["K01"] == "BLOCKED"


def test_direct_cli_without_key_emits_ten_blockers_and_nonzero_exit(tmp_path):
    script = Path(__file__).resolve().parents[2] / "scripts/dev/autonomy_operating_gate.py"
    report = tmp_path / "report.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--profile",
            "agent-stability",
            "--evidence-dir",
            str(tmp_path),
            "--source-sha",
            SHA,
            "--report",
            str(report),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1, proc.stderr
    assert len(json.loads(report.read_text())["checks"]) == 10


def test_thirty_day_check_uses_original_raw_chain_and_collector_targets(tmp_path, monkeypatch):
    from scripts.observability import collect_slo_metrics as collector

    good = {
        "SLO-API-01": 0.9999,
        "SLO-API-02": 100,
        "SLO-API-03": 0.0001,
        "SLO-AI-01": 200,
        "SLO-BUS-01": 0.9999,
        "SLO-BIZ-01": 200,
        "SLO-BIZ-02": 0.0001,
        "SLO-BIZ-03": 1000,
        "SLO-BIZ-04": 1000,
        "SLO-BIZ-05": 1.0,
    }

    def synthetic_query(_url, expression, **_kwargs):
        if expression in collector.SCRAPE_QUERIES.values():
            return "5760"
        for key, template in collector.SAMPLE_QUERIES.items():
            if expression == template.format(w="30d"):
                return str(collector.SAMPLE_MINIMUMS[key])
        return next(
            str(good[key])
            for key, template in collector.QUERIES.items()
            if expression == template.format(w="30d")
        )

    monkeypatch.setattr(collector, "prom_query", synthetic_query)
    monkeypatch.setattr(collector, "measure_retention_days", lambda *_a, **_k: 120.0)
    refs = []
    for i in range(30):
        path = tmp_path / "slo" / f"{i:03d}.json"
        collector.collect(
            prom_url="https://fixture.invalid",
            prom_token="fixture-only",
            window="30d",
            mode="formal",
            release_id=f"xcagi-fixture-version-{SHA}",
            raw_retention_days=0,
            out_path=path,
            now=NOW - timedelta(days=29 - i),
        )
        refs.append(
            {"path": f"slo/{i:03d}.json", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        )
    service = raw_record(
        "service",
        evidence_dir="slo",
        files=refs,
        release_id=f"xcagi-fixture-version-{SHA}",
        release_version="fixture-version",
    )
    report = verify(write_bundle(tmp_path, service=service))
    assert report["checks"]["K09"] == "PASS"
    assert report["status"] == "PASS"  # Synthetic parser acceptance, never product acceptance.
    assert report["metrics"]["K09"]["window"] == "30d"

    service["release_id"] = "xcagi-fixture-version-" + "f" * 40
    report = verify(write_bundle(tmp_path, service=service))
    assert report["checks"]["K09"] == "BLOCKED"
    assert "exact source SHA" in report["blockers"]["K09"]

    service["release_id"] = f"xcagi-fixture-version-{SHA}"
    write_bundle(tmp_path, service=service)
    from scripts.observability import verify_production_slo_window as slo_verifier

    original = slo_verifier.verify_window

    def concurrent_mutation(snapshot, **kwargs):
        assert snapshot != tmp_path / "slo"
        (tmp_path / "slo/000.json").write_text("{}")
        return original(snapshot, **kwargs)

    monkeypatch.setattr(slo_verifier, "verify_window", concurrent_mutation)
    assert verify(tmp_path)["checks"]["K09"] == "PASS"
    (tmp_path / "slo/000.json").unlink()
    assert set(verify(tmp_path)["checks"].values()) == {"BLOCKED"}
