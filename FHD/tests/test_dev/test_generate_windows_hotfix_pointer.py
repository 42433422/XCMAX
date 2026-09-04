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
