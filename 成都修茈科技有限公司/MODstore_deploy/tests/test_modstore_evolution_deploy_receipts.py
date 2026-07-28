from __future__ import annotations

import json
from pathlib import Path

import pytest

from modstore_server.build_employee_pack import register_in_packages_json
from modstore_server.modstore_evolution_deploy_receipts import (
    EvolutionDeploymentReceiptError,
    record_evolution_deployment_receipts,
    verify_catalog_package,
)

MERGE_SHA = "a" * 40


def _catalog_pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict]:
    catalog = tmp_path / "catalog_data"
    files = catalog / "files"
    source = files / "pilot-low-risk-clerk@1.0.0"
    source.mkdir(parents=True)
    manifest = {
        "id": "pilot-low-risk-clerk",
        "name": "pilot-low-risk-clerk",
        "version": "1.0.0",
        "artifact": "employee_pack",
        "department": "engineering",
        "description": "low-risk production readback probe",
        "prompt_template": "Only echo the immutable trace identifier.",
        "skills": ["trace-validation"],
        "tools": ["echo"],
        "acceptance_criteria": ["digest identity is exact"],
        "employee_config_v2": {
            "identity": {
                "id": "pilot-low-risk-clerk",
                "version": "1.0.0",
                "artifact": "employee_pack",
                "name": "pilot",
            },
            "actions": {"handlers": ["echo"]},
        },
    }
    (source / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (source / "prompt.txt").write_text("echo trace", encoding="utf-8")
    (catalog / "packages.json").write_text(json.dumps({"packages": []}), encoding="utf-8")
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(catalog))
    monkeypatch.setenv("MODSTORE_CATALOG_PACKAGES_PATH", str(catalog / "packages.json"))
    monkeypatch.setenv("MODSTORE_CATALOG_FILES_ROOT", str(files))
    register_in_packages_json(manifest, files_dir=source)
    return catalog, manifest


def test_verify_catalog_package_reads_exact_archive_and_runtime_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _catalog_pack(tmp_path, monkeypatch)

    result = verify_catalog_package("pilot-low-risk-clerk", "1.0.0")

    assert result["catalog_readback_verified"] is True
    assert result["installability_verified"] is True
    assert result["runtime_contract_verified"] is True
    assert len(result["package_sha256"]) == 64


def test_verify_catalog_package_rejects_digest_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog, _ = _catalog_pack(tmp_path, monkeypatch)
    archive = catalog / "files" / "pilot-low-risk-clerk-1.0.0.xcemp"
    archive.write_bytes(archive.read_bytes() + b"drift")

    with pytest.raises(EvolutionDeploymentReceiptError, match="digest_mismatch"):
        verify_catalog_package("pilot-low-risk-clerk", "1.0.0")


def test_record_evolution_receipt_is_strong_and_idempotent(monkeypatch) -> None:
    verified = {
        "package_id": "pilot-low-risk-clerk",
        "version": "1.0.0",
        "package_sha256": "b" * 64,
        "stored_filename": "pilot-low-risk-clerk-1.0.0.xcemp",
        "catalog_readback_verified": True,
        "installability_verified": True,
        "runtime_contract_verified": True,
    }
    monkeypatch.setattr(
        "modstore_server.modstore_evolution_deploy_receipts.verify_catalog_package",
        lambda package_id, version: dict(verified),
    )
    events: list[dict] = []
    result = record_evolution_deployment_receipts(
        packages=[{"id": "pilot-low-risk-clerk", "version": "1.0.0"}],
        merge_sha=MERGE_SHA,
        workflow_run_id="12345",
        rows=[],
        record_event=events.append,
        council_builder=lambda package: {"verified": True, "receipt_id": "council-1"},
    )

    assert result["recorded"] == 1
    assert events[0]["event_type"] == "modstore_deployment_verified"
    assert events[0]["dry_run"] is False
    assert events[0]["strategic_council_verified"] is True
    assert events[0]["merge_sha"] == MERGE_SHA

    repeated = record_evolution_deployment_receipts(
        packages=[{"id": "pilot-low-risk-clerk", "version": "1.0.0"}],
        merge_sha=MERGE_SHA,
        workflow_run_id="12345",
        rows=events,
        record_event=events.append,
        council_builder=lambda package: {"verified": True, "receipt_id": "council-1"},
    )
    assert repeated["recorded"] == 0
    assert len(events) == 1


def test_source_bound_pack_records_one_autonomous_code_qa_deploy_run(monkeypatch) -> None:
    verified = {
        "package_id": "autonomy-gap-analyst",
        "version": "1.0.0",
        "package_sha256": "b" * 64,
        "stored_filename": "autonomy-gap-analyst-1.0.0.xcemp",
        "source_commit_sha": "c" * 40,
        "catalog_readback_verified": True,
        "installability_verified": True,
        "runtime_contract_verified": True,
    }
    monkeypatch.setattr(
        "modstore_server.modstore_evolution_deploy_receipts.verify_catalog_package",
        lambda package_id, version: dict(verified),
    )
    events: list[dict] = []

    result = record_evolution_deployment_receipts(
        packages=[{"id": "autonomy-gap-analyst", "version": "1.0.0"}],
        merge_sha=MERGE_SHA,
        workflow_run_id="67890",
        rows=[],
        record_event=events.append,
        council_builder=lambda package: {"verified": True, "receipt_id": "council-2"},
    )

    assert result["recorded"] == 1
    assert len(events) == 5
    assert {event["run_id"] for event in events} == {
        "evolution-deploy-67890-autonomy-gap-analyst"
    }
    assert events[0]["phase"] == "start"
    assert events[0]["triggered_by"] == "proactive_signal"
    assert events[0]["force"] is False
    assert events[1]["step"] == "code"
    assert events[2]["step"] == "qa"
    assert events[3]["event_type"] == "modstore_deployment_verified"
    assert events[4]["status"] == "completed_merged"
