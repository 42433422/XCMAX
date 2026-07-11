from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/package/generate-download-manifest.py"


def test_generated_manifest_matches_download_page_schema(tmp_path: Path) -> None:
    release_root = tmp_path / "release/xcagi-v10.0.0"
    personal = release_root / "personal"
    enterprise = release_root / "enterprise"
    personal.mkdir(parents=True)
    enterprise.mkdir(parents=True)

    personal_installer = personal / "XCAGI-Personal-Setup-10.0.0-x64.exe"
    enterprise_installer = enterprise / "XCAGI-Enterprise-Setup-10.0.0-x64.exe"
    personal_installer.write_bytes(b"personal-installer")
    enterprise_installer.write_bytes(b"enterprise-installer")

    manifest_path = tmp_path / "manifest.json"
    download_release_path = tmp_path / "download-release.json"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--version",
            "10.0.0",
            "--release-dir",
            str(tmp_path / "release"),
            "--release-subdir",
            "xcagi-v10.0.0",
            "--git-sha",
            "deadbeef",
            "--output",
            str(manifest_path),
            "--download-release-output",
            str(download_release_path),
        ],
        check=True,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == "xcagi.download_manifest/v1"
    assert manifest["git_sha"] == "deadbeef"
    personal_entry = manifest["channels"]["official_download"]["personal"]["win"]
    enterprise_entry = manifest["channels"]["auto_update"]["enterprise"]["win"]
    assert personal_entry["size"] == personal_installer.stat().st_size
    assert personal_entry["sha256"] == hashlib.sha256(b"personal-installer").hexdigest()
    assert enterprise_entry["size"] == enterprise_installer.stat().st_size
    assert enterprise_entry["sha256"] == hashlib.sha256(b"enterprise-installer").hexdigest()
