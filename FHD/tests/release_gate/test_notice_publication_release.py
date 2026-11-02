"""A verified notice is an immutable build material, including during old-candidate promotion."""

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

FHD = Path(__file__).resolve().parents[2]
REPO = FHD.parent
SOURCE = FHD / ".github/workflows/release-desktop.yml"
RECORD_PATH = "backend/_internal/config/elt_notice_publication.json"
SHA = "a" * 40


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def workflow():
    return yaml.safe_load(SOURCE.read_text(encoding="utf-8"))


def steps(job):
    return workflow()["jobs"][job]["steps"]


def step(job, name):
    return next(item for item in steps(job) if item.get("name") == name)


def test_optional_record_input_is_data_never_shell_source():
    data = workflow()
    inputs = data.get("on", data.get(True))["workflow_dispatch"]["inputs"]
    assert inputs["windows_installer_only"]["default"] is True
    for key in (
        "notice_publication_json",
        "notice_publication_origin",
        "notice_publication_base_path",
    ):
        assert inputs[key]["type"] == "string"
        assert inputs[key].get("required", False) is False
        assert inputs[key].get("default", "") == ""
    consumers = []
    for job in data["jobs"].values():
        for item in [job, *job.get("steps", [])]:
            assert "inputs.notice_publication_" not in item.get("run", "")
            consumers.extend((item.get("env") or {}).values())
    for key in ("json", "origin", "base_path"):
        assert "${{ inputs.notice_publication_" + key + " }}" in consumers


def test_new_installer_validates_record_before_build_and_installed_probe():
    job = "windows-installer-delivery"
    prepare = step(job, "Validate published notice material")
    assert prepare["env"] == {
        "FHD_NOTICE_PUBLICATION_JSON": "${{ inputs.notice_publication_json }}",
        "NOTICE_PUBLICATION_ORIGIN": "${{ inputs.notice_publication_origin }}",
        "NOTICE_PUBLICATION_BASE_PATH": "${{ inputs.notice_publication_base_path }}",
    }
    command = prepare["run"]
    assert "--record-env FHD_NOTICE_PUBLICATION_JSON" in command
    assert "--origin $env:NOTICE_PUBLICATION_ORIGIN" in command
    assert '"--base-path=$env:NOTICE_PUBLICATION_BASE_PATH"' in command
    assert "--record-file" in command and "RUNNER_TEMP" in command
    assert "'notice-publication'" in command and "'record.json'" in command
    for key in ("FILE", "SHA256", "ORIGIN", "BASE_PATH"):
        assert f"XCAGI_NOTICE_PUBLICATION_{key}" in command
    assert "GITHUB_ENV" in command
    names = [item.get("name", "") for item in steps(job)]
    assert names.index(prepare["name"]) < names.index("Build exact-SHA Windows installer")
    assert names.index("Build exact-SHA Windows installer") < names.index(
        "Verify resources, install, start, and uninstall"
    )
    assert (
        "verify-windows-installed-runtime.ps1"
        in step(job, "Verify resources, install, start, and uninstall")["run"]
    )
    receipt = step(job, "Prepare truthful delivery receipt")["run"]
    assert "notice_publication" in receipt and "notice_publication_installed_probe" in receipt
    upload = next(
        item for item in steps(job) if item.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert "FHD/delivery/notice-publication.json" in upload["with"]["path"]
    assert "FHD/delivery/delivery-receipt.json" in upload["with"]["path"]


def test_old_candidate_promotion_always_checks_material_even_without_new_input():
    guard = step("publish-interim-windows-pointer", "Verify immutable candidate notice material")
    assert "if" not in guard
    assert "inputs.notice_publication_json" not in yaml.safe_dump(guard)
    command = guard["run"]
    assert "notice_publication_material.py verify-candidate" in command
    assert all(flag in command for flag in ("--receipt", "--record", "--source-sha"))
    assert "notice-publication.json" in command
    names = [item.get("name", "") for item in steps("publish-interim-windows-pointer")]
    assert names.index(guard["name"]) < names.index("Generate bounded interim download pointer")
    assert names.index(guard["name"]) < names.index(
        "Publish installer and pointer to the public download page"
    )


@pytest.mark.parametrize(
    "change,accepted",
    [
        ({}, True),
        ({"NOTICE_PUBLICATION_BASE_PATH": "/admin"}, True),
        ({"WINDOWS_ONLY": "false"}, False),
        ({"VERIFY_ONLY": "true"}, False),
        ({"CANDIDATE_RUN": "123"}, False),
        ({"FHD_NOTICE_PUBLICATION_JSON": ""}, False),
        ({"NOTICE_PUBLICATION_ORIGIN": ""}, False),
        (
            {
                "FHD_NOTICE_PUBLICATION_JSON": "",
                "NOTICE_PUBLICATION_ORIGIN": "",
                "NOTICE_PUBLICATION_BASE_PATH": "/admin",
            },
            False,
        ),
        ({"FHD_NOTICE_PUBLICATION_JSON": "", "NOTICE_PUBLICATION_ORIGIN": ""}, False),
        (
            {
                "FHD_NOTICE_PUBLICATION_JSON": "",
                "NOTICE_PUBLICATION_ORIGIN": "",
                "VERIFY_ONLY": "true",
            },
            True,
        ),
        (
            {
                "FHD_NOTICE_PUBLICATION_JSON": "",
                "NOTICE_PUBLICATION_ORIGIN": "",
                "CANDIDATE_RUN": "123",
            },
            True,
        ),
        (
            {
                "FHD_NOTICE_PUBLICATION_JSON": "",
                "NOTICE_PUBLICATION_ORIGIN": "",
                "VERIFY_ONLY": "true",
                "CANDIDATE_RUN": "123",
            },
            False,
        ),
    ],
)
@pytest.mark.skipif(os.name == "nt", reason="Dispatch guard executes on the Ubuntu runner")
def test_input_lane_policy_executes_exact_dispatch_guard(change, accepted):
    gate = step("notice-publication-policy", "Validate notice material lane")
    env = {
        **os.environ,
        "WINDOWS_ONLY": "true",
        "VERIFY_ONLY": "false",
        "CANDIDATE_RUN": "",
        "FHD_NOTICE_PUBLICATION_JSON": "{}",
        "NOTICE_PUBLICATION_ORIGIN": "https://www.xiu-ci.com",
        "NOTICE_PUBLICATION_BASE_PATH": "",
        **change,
    }
    result = subprocess.run(["bash", "-euc", gate["run"]], env=env, capture_output=True, timeout=20)
    assert (result.returncode == 0) is accepted
    jobs = workflow()["jobs"]
    for name in (
        "windows-installer-delivery",
        "release-preflight",
        "publish-interim-windows-pointer",
    ):
        assert "notice-publication-policy" in jobs[name]["needs"]
    assert (
        "needs.notice-publication-policy.result == 'success'"
        in jobs["publish-interim-windows-pointer"]["if"]
    )


def test_published_root_workflow_is_the_official_source_render():
    publisher = load_module(
        "notice_ci_publisher", REPO / "scripts/dev/publish_ci_workflows_to_root.py"
    )
    name, rendered = publisher._render_fhd(SOURCE)
    assert name == "fhd-release-desktop.yml"
    assert (REPO / ".github/workflows" / name).read_text(encoding="utf-8") == rendered


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    monkeypatch.delenv("XCAGI_NOTICE_PUBLICATION_ORIGIN", raising=False)
    monkeypatch.delenv("XCAGI_NOTICE_PUBLICATION_BASE_PATH", raising=False)
    helper = load_module(
        "candidate_notice_material", FHD / "scripts/package/notice_publication_material.py"
    )
    docs = helper.publication_api().source_documents()
    raw = json.dumps(
        {
            "notice_version": docs["service-agreement"]["version"],
            "recipient_disclosure_version": docs["privacy-policy"]["version"],
            "published_at": "2026-01-01T00:00:00+00:00",
        },
        separators=(",", ":"),
    ).encode()
    record = tmp_path / "notice-publication.json"
    record.write_bytes(raw)
    receipt = tmp_path / "delivery-receipt.json"
    value = {
        "git_sha": SHA,
        "notice_publication": {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "origin": "https://www.xiu-ci.com",
            "base_path": "/admin",
            "source_sha": SHA,
            "path": RECORD_PATH,
        },
        "notice_publication_installed_probe": "passed",
    }
    receipt.write_text(json.dumps(value), encoding="utf-8")
    return helper, record, receipt, value


def test_candidate_material_guard_accepts_exact_installed_material_without_rewriting(candidate):
    helper, record, receipt, value = candidate
    before = record.read_bytes(), receipt.read_bytes()
    assert helper.verify_candidate(receipt, record, SHA) == value["notice_publication"]
    assert (
        helper.main(
            [
                "verify-candidate",
                "--receipt",
                str(receipt),
                "--record",
                str(record),
                "--source-sha",
                SHA,
            ]
        )
        == 0
    )
    assert (record.read_bytes(), receipt.read_bytes()) == before


def test_candidate_verifier_requires_no_site_packages(candidate):
    _, record, receipt, _ = candidate
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            str(FHD / "scripts/package/notice_publication_material.py"),
            "verify-candidate",
            "--receipt",
            str(receipt),
            "--record",
            str(record),
            "--source-sha",
            SHA,
        ],
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "mutation",
    [
        "old_receipt",
        "hash",
        "source",
        "path",
        "origin",
        "base_path",
        "base_missing",
        "receipt_source",
        "probe_missing",
        "probe_failed",
        "record_missing",
        "record_tampered",
    ],
)
def test_candidate_material_guard_declines_unproven_or_changed_candidates(candidate, mutation):
    helper, record, receipt, value = candidate
    if mutation == "old_receipt":
        value.pop("notice_publication")
    elif mutation in {"hash", "source", "path", "origin", "base_path"}:
        key, replacement = {
            "hash": ("sha256", "b" * 63),
            "source": ("source_sha", "b" * 40),
            "path": ("path", "different/record.json"),
            "origin": ("origin", "http://www.xiu-ci.com"),
            "base_path": ("base_path", "/../outside"),
        }[mutation]
        value["notice_publication"][key] = replacement
    elif mutation == "base_missing":
        value["notice_publication"].pop("base_path")
    elif mutation == "probe_missing":
        value.pop("notice_publication_installed_probe")
    elif mutation == "probe_failed":
        value["notice_publication_installed_probe"] = "not_verified"
    elif mutation == "record_missing":
        record.unlink()
    elif mutation == "receipt_source":
        value["git_sha"] = "b" * 40
    else:
        record.write_bytes(record.read_bytes() + b" ")
    receipt.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises((OSError, ValueError)):
        helper.verify_candidate(receipt, record, SHA)
