from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = FHD_ROOT / "scripts" / "package" / "generate-windows-hotfix-pointer.py"
WORKFLOW = FHD_ROOT / ".github" / "workflows" / "windows-macalign-hotfix.yml"
ROOT_WORKFLOW = FHD_ROOT.parent / ".github" / "workflows" / "fhd-windows-macalign-hotfix.yml"


def _metadata(path: Path, version: str = "1.0.0.1") -> None:
    path.write_text(
        json.dumps(
            {
                "version_lock": version,
                "download_version": version,
                "release_history": [
                    {
                        "version": version,
                        "date": "2026-09-01",
                        "title": "Windows 临时交付",
                        "channel": "交付候选版",
                        "notes": ["明确显示未签名风险。"],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_generates_fail_closed_unsigned_quarantine_metadata(tmp_path: Path) -> None:
    version = "1.0.0.1"
    filename = f"XCAGI-Enterprise-Setup-{version}-x64-macalign.exe"
    artifact = tmp_path / filename
    artifact.write_bytes(b"MZ-interim")
    metadata = tmp_path / "release.json"
    output = tmp_path / "pointer.json"
    _metadata(metadata)

    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--version",
            version,
            "--git-sha",
            "a" * 40,
            "--artifact",
            str(artifact),
            "--artifact-url",
            f"artifact://github-actions/{filename}",
            "--release-metadata-source",
            str(metadata),
            "--output",
            str(output),
        ],
        check=True,
    )

    pointer = json.loads(output.read_text(encoding="utf-8"))
    assert pointer["schema"] == "xcagi.windows_interim_release/v1"
    assert pointer["version"] == version
    assert pointer["git_sha"] == "a" * 40
    assert pointer["download_allowed"] is False
    assert pointer["channel"] == "enterprise-quarantine"
    assert pointer["signature_status"] == "unsigned"
    assert "禁止公开下载" in pointer["warning"]
    assert pointer["artifact"]["filename"] == filename
    assert pointer["artifact"]["size"] == len(b"MZ-interim")
    assert pointer["artifact"]["sha256"] == hashlib.sha256(b"MZ-interim").hexdigest()
    assert pointer["release"]["version"] == version


def _acceptance(path: Path, **overrides) -> Path:
    record = {
        "schema": "xcagi.windows_signing_acceptance/v1",
        "id": "WSA-TEST-01",
        "scope": "public_download",
        "status": "accepted_risk",
        "author": "release-bot",
        "reviewer": "owner-42433422",
        "accepted_at": "2026-09-17T00:00:00+08:00",
        "expires_at": "2029-09-17T00:00:00+08:00",
        "windows_stable_feed": "closed",
        "decision_record": "限期风险接受：授权期内允许未签名包公开下载，更新通道保持关闭。",
        "disclosed_risks": [
            {"id": "unknown-publisher", "impact": "medium", "text": "客户机会显示未知发布者。"}
        ],
    }
    record.update(overrides.pop("fields", {}))
    canonical = json.dumps(
        {
            key: value
            for key, value in record.items()
            if key not in ("schema", "decision_record_sha256")
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    record["decision_record_sha256"] = overrides.pop(
        "decision_record_sha256", hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    )
    record.update(overrides)
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return path


def _authorized_run(tmp_path: Path, acceptance: Path) -> subprocess.CompletedProcess:
    version = "1.0.0.4"
    filename = f"XCAGI-Enterprise-Setup-{version}-x64-unsigned.exe"
    artifact = tmp_path / filename
    artifact.write_bytes(b"MZ-unsigned")
    metadata = tmp_path / "release.json"
    _metadata(metadata, version)
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--version",
            version,
            "--git-sha",
            "c" * 40,
            "--artifact",
            str(artifact),
            "--artifact-url",
            f"https://xiu-ci.com/xcagi-v{version}/enterprise/{filename}",
            "--release-metadata-source",
            str(metadata),
            "--risk-acceptance",
            str(acceptance),
            "--output",
            str(tmp_path / "pointer.json"),
        ],
        capture_output=True,
        text=True,
    )


def test_authorized_acceptance_opens_public_download_within_its_term(tmp_path: Path) -> None:
    acceptance = _acceptance(tmp_path / "acceptance.json")
    result = _authorized_run(tmp_path, acceptance)
    assert result.returncode == 0, result.stderr

    pointer = json.loads((tmp_path / "pointer.json").read_text(encoding="utf-8"))
    assert pointer["download_allowed"] is True
    assert pointer["channel"] == "enterprise-interim"
    assert pointer["signature_status"] == "unsigned"
    assert "禁止公开下载" not in pointer["warning"]
    assert pointer["risk_acceptance"]["expires_at"] == "2029-09-17T00:00:00+08:00"
    assert pointer["risk_acceptance"]["disclosed_risks"]
    assert pointer["artifact"]["url"].startswith("https://")


def test_authorized_acceptance_requires_a_public_https_artifact_url(tmp_path: Path) -> None:
    acceptance = _acceptance(tmp_path / "acceptance.json")
    version = "1.0.0.4"
    filename = f"XCAGI-Enterprise-Setup-{version}-x64-unsigned.exe"
    (tmp_path / filename).write_bytes(b"MZ-unsigned")
    metadata = tmp_path / "release.json"
    _metadata(metadata, version)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--version",
            version,
            "--git-sha",
            "c" * 40,
            "--artifact",
            str(tmp_path / filename),
            "--artifact-url",
            f"artifact://github-actions/{filename}",
            "--release-metadata-source",
            str(metadata),
            "--risk-acceptance",
            str(acceptance),
            "--output",
            str(tmp_path / "pointer.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "requires an https artifact URL" in result.stderr


def test_expired_acceptance_fails_closed(tmp_path: Path) -> None:
    acceptance = _acceptance(
        tmp_path / "acceptance.json",
        fields={
            "accepted_at": "2019-09-17T00:00:00+08:00",
            "expires_at": "2020-09-17T00:00:00+08:00",
        },
    )
    result = _authorized_run(tmp_path, acceptance)
    assert result.returncode != 0
    assert "risk acceptance expired" in result.stderr
    assert not (tmp_path / "pointer.json").exists()


def test_weak_acceptance_evidence_fails_closed(tmp_path: Path) -> None:
    self_reviewed = _acceptance(tmp_path / "self.json", fields={"reviewer": "release-bot"})
    result = _authorized_run(tmp_path, self_reviewed)
    assert result.returncode != 0
    assert "reviewer must differ" in result.stderr

    tampered = _acceptance(tmp_path / "tampered.json")
    payload = json.loads(tampered.read_text(encoding="utf-8"))
    payload["decision_record"] = "被改写过的决策记录。"
    tampered.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = _authorized_run(tmp_path, tampered)
    assert result.returncode != 0
    assert "decision hash does not match" in result.stderr


def test_rejects_release_metadata_version_drift(tmp_path: Path) -> None:
    artifact = tmp_path / "XCAGI-Enterprise-Setup-1.0.0.1-x64-macalign.exe"
    artifact.write_bytes(b"MZ")
    metadata = tmp_path / "release.json"
    _metadata(metadata, "1.0.0.0")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--version",
            "1.0.0.1",
            "--git-sha",
            "b" * 40,
            "--artifact",
            str(artifact),
            "--artifact-url",
            "artifact://github-actions/XCAGI-Enterprise-Setup-1.0.0.1-x64-macalign.exe",
            "--release-metadata-source",
            str(metadata),
            "--output",
            str(tmp_path / "pointer.json"),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "release metadata version does not match" in result.stderr


def test_hotfix_workflow_only_retains_a_quarantined_ci_artifact() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    root_workflow = ROOT_WORKFLOW.read_text(encoding="utf-8")

    for candidate in (workflow, root_workflow):
        assert "generate-windows-hotfix-pointer.py" in candidate
        assert "WINDOWS-QUARANTINE.json" in candidate
        assert "verify_security_scan_pair.py" in candidate
        assert "Publish mac-align hotfix to CVM" not in candidate
        assert "download-windows-hotfix.json" not in candidate
        assert "latest.yml" not in candidate
