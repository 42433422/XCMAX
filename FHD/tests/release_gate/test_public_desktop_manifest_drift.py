"""No network calls: the drift checker must verify current pointer and ALL platforms."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/dev/verify_desktop_manifest_drift.py"
BASE = "https://xiu-ci.com"
VERSION = "1.0.0.7"
SHA = "a" * 40
MANIFEST = f"{BASE}/xcagi-v{VERSION}/manifest.json"
FILES = {f"{BASE}/xcagi-v{VERSION}/enterprise/win.exe": b"win",
         f"{BASE}/xcagi-v{VERSION}/enterprise/mac.dmg": b"mac"}


def load():
    spec = importlib.util.spec_from_file_location("desktop_manifest_drift", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def manifest():
    def entry(url, content):
        return {"url": url, "filename": url.rsplit("/", 1)[-1],
                "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    return {"schema": "xcagi.download_manifest/v1", "version": VERSION,
            "git_sha": SHA, "release_id": f"xcagi-{VERSION}-{SHA}",
            "channels": {"official_download": {"base_url": BASE, "enterprise": {
                "win": entry(list(FILES)[0], b"win"),
                "mac": [entry(list(FILES)[1], b"mac")],
            }}}}


def pointer():
    return {"schema": "xcagi.download_release.public/v1",
            "version_lock": VERSION, "download_version": VERSION,
            "release_ready": True, "git_sha": SHA,
            "release_id": f"xcagi-{VERSION}-{SHA}", "manifest_url": MANIFEST}


def run(monkeypatch, tmp_path, m=None, p=None, full=False):
    obj = load()
    page = manifest() if m is None else m
    release = pointer() if p is None else p
    def fetch(url, timeout=30):
        if url.endswith("/download-release.json"):
            return json.dumps(release).encode()
        if url == MANIFEST:
            return json.dumps(page).encode()
        return FILES[url]
    monkeypatch.setattr(obj, "_fetch", fetch)
    monkeypatch.setattr(obj, "_content_length", lambda url, timeout=30: len(FILES[url]))
    out = tmp_path / "report.json"
    argv = [str(SCRIPT), "--output", str(out)]
    if full:
        argv.append("--full-sha256")
    monkeypatch.setattr(sys, "argv", argv)
    status = obj.main()
    return status, json.loads(out.read_text())


@pytest.mark.parametrize("full", [False, True])
def test_all_platforms_are_verified(monkeypatch, tmp_path, full):
    status, result = run(monkeypatch, tmp_path, full=full)
    assert status == 0 and result["passed"] is True
    assert result["entries_checked"] == 2


@pytest.mark.parametrize("changed", [
    {"release_ready": False}, {"git_sha": "b" * 40},
    {"manifest_url": "https://evil.invalid/manifest.json"},
])
def test_untrusted_or_unpublished_pointer_fails(monkeypatch, tmp_path, changed):
    status, result = run(monkeypatch, tmp_path, p={**pointer(), **changed})
    assert status == 1 and result["drift"]


def test_empty_artifacts_fail_instead_of_zero_checks_pass(monkeypatch, tmp_path):
    m = {**manifest(), "channels": {"official_download": {"base_url": BASE}}}
    status, result = run(monkeypatch, tmp_path, m=m)
    assert status == 1 and result["entries_checked"] == 0


@pytest.mark.parametrize("field", ["size", "sha256", "url"])
def test_windows_dict_entry_is_validated(monkeypatch, tmp_path, field):
    m = manifest()
    m["channels"]["official_download"]["enterprise"]["win"][field] = (
        0 if field == "size" else "bad"
    )
    status, result = run(monkeypatch, tmp_path, m=m)
    assert status == 1
    assert any(v.get("reason") == "invalid_artifact_identity" for v in result["drift"])


def test_manifest_sha_must_equal_published_pointer(monkeypatch, tmp_path):
    status, result = run(monkeypatch, tmp_path, m={**manifest(), "git_sha": "b" * 40})
    assert status == 1 and result["drift"]


def test_daily_uses_public_pointer_and_weekly_full_digest():
    workflow = (Path(__file__).resolve().parents[2] /
                ".github/workflows/desktop-manifest-drift-check.yml").read_text()
    assert "inputs.version || ''" in workflow
    assert "30 3 * * 0" in workflow
    assert "--full-sha256" in workflow
