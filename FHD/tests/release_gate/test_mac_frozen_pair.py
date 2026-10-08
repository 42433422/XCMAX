from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import os
import plistlib
import struct
import subprocess
import zipfile
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

FHD = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "pair", FHD / "scripts/release/prepare_mac_candidate_pair.py"
)
pair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pair)
SHA, VERSION = "a" * 40, "1.0.0.5"


def fixture(root, key, fault=None):
    for arch, cpu, runner in (
        ("arm64", 0x100000C, "macos-latest"),
        ("x64", 0x1000007, "macos-15-intel"),
    ):
        d = root / arch
        d.mkdir()
        stem = f"XCAGI-Enterprise-{VERSION}-mac-{arch}"
        app = io.BytesIO()
        with zipfile.ZipFile(app, "w") as z:
            z.writestr(
                "XCAGI.app/Contents/Resources/build-info.json",
                json.dumps({"gitSha": SHA, "version": VERSION}),
            )
            z.writestr(
                "XCAGI.app/Contents/Info.plist",
                plistlib.dumps(
                    {
                        "CFBundleVersion": VERSION,
                        "CFBundleIdentifier": "com.xcagi.desktop.enterprise",
                    }
                ),
            )
            z.writestr(
                "XCAGI.app/Contents/MacOS/XCAGI",
                struct.pack(
                    "<II",
                    0xFEEDFACF,
                    0x100000C if fault == "architecture" and arch == "x64" else cpu,
                ),
            )
        data = app.getvalue()
        body = f"buildSha: {SHA}\nproductVersion: {VERSION}\nfiles:\n  - url: {stem}.zip\n    sha512: {base64.b64encode(hashlib.sha512(data).digest()).decode()}\n    size: {len(data)}"
        signature = base64.b64encode(key.sign(body.encode())).decode()
        with zipfile.ZipFile(d / "artifact.zip", "w") as z:
            z.writestr(stem + ".zip", data)
            z.writestr(stem + ".dmg", b"SYNTHETIC DMG")
            z.writestr(stem + ".zip.blockmap", b"SYNTHETIC BLOCKMAP")
            z.writestr("latest-mac.yml", body + "\nsignature: ed25519:" + signature + "\n")
            z.writestr(
                "acceptance-evidence/installed-startup.json",
                json.dumps(
                    {
                        "sha": SHA,
                        "version": VERSION,
                        "packageSha": hashlib.sha256(b"SYNTHETIC DMG").hexdigest(),
                        "systemIntegration": True,
                        "runtime": {"architecture": arch},
                    }
                ),
            )
        run_id = 11 if arch == "arm64" else 12
        (d / "run.json").write_text(
            json.dumps(
                {
                    "id": run_id,
                    "name": "Release Desktop macOS OTA",
                    "path": ".github/workflows/fhd-release-desktop-mac-ota.yml",
                    "head_sha": SHA,
                    "head_branch": "main",
                    "event": "workflow_dispatch",
                    "conclusion": "success",
                }
            )
        )
        (d / "artifact.json").write_text(
            json.dumps(
                {
                    "id": run_id + 1,
                    "name": f"mac-acceptance-{SHA}-{arch}",
                    "expired": False,
                    "workflow_run": {"id": run_id, "head_sha": SHA},
                    "digest": "sha256:" + pair.digest(d / "artifact.zip"),
                    "size_in_bytes": (d / "artifact.zip").stat().st_size,
                }
            )
        )
        (d / "jobs.json").write_text(
            json.dumps(
                {
                    "jobs": [
                        {
                            "name": "macos-ota",
                            "conclusion": "success",
                            "labels": [runner],
                            "steps": [{"name": s, "conclusion": "success"} for s in pair.STEPS],
                        }
                    ]
                }
            )
        )


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "sha",
        "expired",
        "digest",
        "runner",
        "signature",
        "architecture",
        "publish-without-authorization",
    ],
)
def test_frozen_pair_preserves_bytes_and_refuses_mismatch(tmp_path, fault):
    key = Ed25519PrivateKey.generate()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    fixture(tmp_path, key, fault)
    if fault in {"sha", "expired", "digest"}:
        p = tmp_path / "x64/artifact.json"
        value = json.loads(p.read_text())
        if fault == "sha":
            value["workflow_run"]["head_sha"] = "b" * 40
        elif fault == "expired":
            value["expired"] = True
        else:
            value["digest"] = "sha256:" + "0" * 64
        p.write_text(json.dumps(value))
    if fault == "runner":
        p = tmp_path / "x64/jobs.json"
        value = json.loads(p.read_text())
        value["jobs"][0]["labels"] = ["macos-latest"]
        p.write_text(json.dumps(value))
    if fault == "signature":
        public = (
            Ed25519PrivateKey.generate()
            .public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode()
        )
    output = tmp_path / "output"
    if fault not in {None, "publish-without-authorization"}:
        with pytest.raises(InvalidSignature if fault == "signature" else ValueError):
            pair.prepare(tmp_path, output, SHA, VERSION, public)
        assert not output.exists()
        return
    review = pair.prepare(tmp_path, output, SHA, VERSION, public)
    assert len(review["architectures"]) == 2
    for row in review["architectures"]:
        for item in row["files"]:
            assert pair.digest(output / item["name"]) == item["sha256"]
    signer = FHD / "scripts/dev/sign_update_metadata.py"
    signer_spec = importlib.util.spec_from_file_location("signer", signer)
    sign = importlib.util.module_from_spec(signer_spec)
    signer_spec.loader.exec_module(sign)
    sign.sign_file(output / "latest-mac.yml", key)
    env = {
        k: v
        for k, v in os.environ.items()
        if not any(
            s in k.upper()
            for s in ("TOKEN", "SECRET", "PASSWORD", "PRIVATE_KEY", "API_KEY", "AUTHORIZED_SHA")
        )
    }
    env["XCAGI_UPDATE_ED25519_PUBLIC_KEY"] = public
    previous = tmp_path / "previous-public"
    previous.mkdir()
    old_pointer, old_manifest = public_snapshot()
    (previous / "download-release.json").write_text(json.dumps(old_pointer))
    (previous / "manifest.json").write_text(json.dumps(old_manifest))
    env["XCAGI_PUBLIC_DOWNLOAD_SNAPSHOT_DIR"] = str(previous)
    env["PATH"] = str(Path(os.sys.executable).parent) + os.pathsep + env["PATH"]
    script = Path(
        env.get(
            "MAC_PAIR_PUBLISHER_UNDER_TEST",
            FHD / "scripts/package/publish-macos-download-center.sh",
        )
    )
    mode = "--publish" if fault else "--dry-run"
    result = subprocess.run(
        ["bash", str(script), VERSION, SHA, str(output), mode],
        env=env,
        capture_output=True,
        text=True,
    )
    if fault:
        assert result.returncode != 0
    else:
        assert result.returncode == 0, result.stderr
        assert "Verification complete; public metadata may have been read" in result.stdout


@pytest.mark.parametrize("guard", ["approved", "disabled", "wrong-owner-sha", "failed-check"])
def test_publication_requires_explicit_owner_authorization_and_current_checks(tmp_path, guard):
    import yaml

    workflow = yaml.safe_load((FHD / ".github/workflows/fix-mac-update-feed.yml").read_text())
    step = next(
        s
        for s in workflow["jobs"]["frozen-pair"]["steps"]
        if s.get("name") == "Validate main identity and publication authorization"
    )
    source_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=FHD, text=True).strip()
    (tmp_path / "main").write_text(source_sha + "\n")
    (tmp_path / "protection").write_text(json.dumps({"contexts": ["gate"]}))
    (tmp_path / "checks").write_text(
        json.dumps(
            [
                {
                    "check_runs": [
                        {
                            "name": "gate",
                            "id": 2,
                            "conclusion": "failure" if guard == "failed-check" else "success",
                        }
                    ]
                }
            ]
        )
    )
    # An older success status must not override a currently failing protected check.
    (tmp_path / "statuses").write_text(
        json.dumps([[{"context": "gate", "id": 1, "state": "success"}]])
    )
    gh = tmp_path / "gh"
    gh.write_text("""#!/bin/bash
case "$*" in
 *commits/main*) cat "$FAKE_API/main" ;;
 *required_status_checks*) cat "$FAKE_API/protection" ;;
 *check-runs*) cat "$FAKE_API/checks" ;;
 *statuses*) cat "$FAKE_API/statuses" ;;
 *) exit 99 ;;
esac
""")
    gh.chmod(0o700)
    env = {
        "PATH": os.pathsep.join(
            (str(tmp_path), str(Path(os.sys.executable).parent), os.environ["PATH"])
        ),
        "FAKE_API": str(tmp_path),
        "BUILD_SHA": source_sha,
        "PRODUCT_VERSION": VERSION,
        "ARM_RUN": "11",
        "X64_RUN": "12",
        "PUBLISH": "true",
        "ENABLED": "false" if guard == "disabled" else "true",
        "AUTHORIZED_SHA": "b" * 40 if guard == "wrong-owner-sha" else source_sha,
        "GITHUB_REPOSITORY": "synthetic/repo",
        "RELEASE_PROTECTION_TOKEN": "TEST_ONLY",
        "GH_TOKEN": "TEST_ONLY",
    }
    result = subprocess.run(
        ["bash", "-c", step["run"]], cwd=FHD, env=env, capture_output=True, text=True
    )
    assert (result.returncode == 0) is (guard == "approved"), result.stderr


@pytest.mark.parametrize("wrong_bytes", [False, True])
def test_public_readback_rejects_same_size_different_bytes(tmp_path, wrong_bytes):
    import http.server
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            content = b"WRONG" if wrong_bytes else b"RIGHT"
            self.send_response(200)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    source = (FHD / "scripts/package/publish-macos-download-center.sh").read_text()
    check = source[source.index('  public_sha="$(') : source.index('  size="$(wc -c')]
    env = {
        "PATH": os.environ["PATH"],
        "NO_PROXY": "127.0.0.1",
        "immutable_base": f"http://127.0.0.1:{server.server_port}",
        "name": "synthetic.zip",
        "expected": hashlib.sha256(b"RIGHT").hexdigest(),
    }
    try:
        result = subprocess.run(
            ["bash", "-c", "set -euo pipefail\n" + check], env=env, capture_output=True, text=True
        )
        assert (result.returncode == 0) is (not wrong_bytes)
    finally:
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()


def public_snapshot():
    shared = "https://xiu-ci.com/xcagi-v" + VERSION
    pointer = {
        "schema": "xcagi.download_release.public/v1",
        "download_version": VERSION,
        "version_lock": VERSION,
        "git_sha": "b" * 40,
        "release_id": f"xcagi-{VERSION}-{'b' * 40}",
        "cos_base_url": shared,
        "release_root": shared,
        "manifest_url": shared + "/manifest.json",
        "auto_update_base": "https://xiu-ci.com/releases/stable",
        "win_installer_mb": 204,
        "android_version": "1.0.0.0",
        "android_git_sha": "c" * 40,
        "release_ready": False,
    }
    manifest = {
        "schema": "xcagi.download_manifest/v1",
        "version": VERSION,
        "git_sha": pointer["git_sha"],
        "release_id": pointer["release_id"],
        "release_ready": False,
        "channels": {
            name: {
                "base_url": pointer["auto_update_base"] if name == "auto_update" else shared,
                "enterprise": {"mac": [{"url": shared + "/enterprise/old-mac.dmg"}]},
            }
            for name in ("auto_update", "official_download")
        },
    }
    return pointer, manifest


@pytest.mark.parametrize(
    "case", ["mac-only", "other-platforms", "missing-pointer", "mismatched-current"]
)
def test_merge_keeps_shared_roots_and_all_other_platform_records(case):
    from copy import deepcopy

    pointer, old = public_snapshot()
    if case == "other-platforms":
        for channel in old["channels"].values():
            for platform in ("win", "android"):
                channel["enterprise"][platform] = {
                    "url": channel["base_url"] + "/enterprise/original-" + platform,
                    "filename": "original-" + platform,
                    "sha256": "d" * 64,
                    "size": 431,
                    "metadata": {"release_id": "preserved", "version": "1.0.0.0"},
                }
    unchanged = deepcopy((pointer, old))
    generated = {
        "download_version": VERSION,
        "git_sha": SHA,
        "release_id": f"xcagi-{VERSION}-{SHA}",
        "generated_at": "2026-10-08T00:00:00Z",
    }
    new = {
        "version": VERSION,
        **generated,
        "update_metadata_signatures": {"mac": "fresh-signature"},
        "channels": {
            name: {
                "enterprise": {
                    "mac": [
                        {
                            "url": f"https://xiu-ci.com/xcagi-v{VERSION}/builds/{SHA}/enterprise/mac-{arch}.dmg"
                        }
                        for arch in ("arm64", "x64")
                    ]
                }
            }
            for name in old["channels"]
        },
    }
    if case == "missing-pointer":
        pointer = {}
    if case == "mismatched-current":
        old["git_sha"] = "c" * 40
    if case in {"missing-pointer", "mismatched-current"}:
        with pytest.raises(ValueError):
            pair.merge_download_metadata(
                pointer, old, generated, new, {"source_sha": SHA, "version": VERSION}
            )
        return
    public, merged = pair.merge_download_metadata(
        pointer, old, generated, new, {"source_sha": SHA, "version": VERSION}
    )
    assert (pointer, old) == unchanged
    assert public["git_sha"] == merged["git_sha"] == SHA
    assert public["release_id"] == merged["release_id"] == generated["release_id"]
    for field in (
        "cos_base_url",
        "release_root",
        "manifest_url",
        "auto_update_base",
        "win_installer_mb",
        "android_version",
        "android_git_sha",
    ):
        assert public[field] == pointer[field]
    for name, channel in old["channels"].items():
        assert merged["channels"][name]["base_url"] == channel["base_url"]
        for platform, entry in channel["enterprise"].items():
            if platform != "mac":
                assert merged["channels"][name]["enterprise"][platform] == entry
        assert (
            merged["channels"][name]["enterprise"]["mac"]
            == new["channels"][name]["enterprise"]["mac"]
        )
