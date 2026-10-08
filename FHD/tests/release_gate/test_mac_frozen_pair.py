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
        assert "OFFLINE verification complete" in result.stdout
