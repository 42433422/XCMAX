#!/usr/bin/env python3
"""Validate immutable native Actions artifacts and stage their original bytes offline."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import plistlib
import re
import shutil
import struct
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

STEPS = (
    "Lock checkout and acceptance candidate to main",
    "Notarize and staple macOS enterprise DMG",
    "Verify notarized DMG and packaged runtime",
    "Upload macOS OTA artifacts for recovery",
)


def desktop_public_key() -> str:
    # Trust the client key in the exact checked-out main, never the supplied signing key.
    source = (Path(__file__).resolve().parents[2] / "desktop/desktop-config.ts").read_text()
    block = source.split("export const ED25519_PUBLIC_KEY_PEM = [", 1)[1].split("].join('\\n')", 1)[
        0
    ]
    parts = [value for value in re.findall(r"'([^']*)'", block) if value]
    if parts[0] != "-----BEGIN PUBLIC KEY-----" or parts[-1] != "-----END PUBLIC KEY-----":
        raise ValueError("client trust anchor could not be read")
    return parts[0] + "\n" + "".join(parts[1:-1]) + "\n" + parts[-1] + "\n"


def digest(path: Path, algorithm: str = "sha256") -> str:
    h = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def merge_download_metadata(
    pointer: dict, previous: dict, generated: dict, mac_manifest: dict, review: dict
) -> tuple[dict, dict]:
    from copy import deepcopy
    from urllib.parse import urlsplit

    version, old_sha = pointer.get("download_version"), pointer.get("git_sha", "")
    if not (
        pointer.get("schema") == "xcagi.download_release.public/v1"
        and previous.get("schema") == "xcagi.download_manifest/v1"
        and re.fullmatch(r"[0-9a-f]{40}", old_sha)
        and previous.get("version") == version == generated.get("download_version")
        and previous.get("git_sha") == old_sha
        and pointer.get("release_id") == previous.get("release_id") == f"xcagi-{version}-{old_sha}"
    ):
        raise ValueError("trusted same-version current public pointer/manifest identity required")
    if not (
        generated.get("git_sha") == mac_manifest.get("git_sha") == review.get("source_sha")
        and generated.get("release_id") == mac_manifest.get("release_id")
        and review.get("version") == version
    ):
        raise ValueError("new Mac candidate identity mismatch")
    for field in ("cos_base_url", "release_root", "manifest_url", "auto_update_base"):
        url = urlsplit(pointer.get(field, ""))
        if (
            url.scheme != "https"
            or url.hostname != "xiu-ci.com"
            or url.username
            or url.port not in (None, 443)
        ):
            raise ValueError("trusted shared public download roots required")
    merged, public = deepcopy(previous), deepcopy(pointer)
    for key in ("version", "git_sha", "release_id", "generated_at"):
        merged[key] = mac_manifest[key]
    for key in ("git_sha", "release_id", "generated_at"):
        public[key] = generated[key]
    merged["release_ready"] = public["release_ready"] = False
    for channel in ("official_download", "auto_update"):
        if not isinstance(merged.get("channels", {}).get(channel), dict):
            raise ValueError("current shared channel missing")
        merged["channels"][channel].setdefault("enterprise", {})["mac"] = mac_manifest["channels"][
            channel
        ]["enterprise"]["mac"]
    merged.setdefault("update_metadata_signatures", {})["mac"] = mac_manifest[
        "update_metadata_signatures"
    ]["mac"]
    public["mac_release"] = deepcopy(review)
    merged["mac_release"] = deepcopy(review)
    return public, merged


def prepare(root: Path, output: Path, sha: str, version: str, key_pem: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", sha) or not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", version):
        raise ValueError("exact SHA and four-part version required")
    key = serialization.load_pem_public_key(key_pem.replace("\\n", "\n").encode())
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("Ed25519 public key required")
    rows, files = [], []
    for arch, cpu, runner in (
        ("arm64", 0x100000C, "macos-latest"),
        ("x64", 0x1000007, "macos-15-intel"),
    ):
        directory = root / arch
        run = json.loads((directory / "run.json").read_text())
        artifact = json.loads((directory / "artifact.json").read_text())
        jobs = json.loads((directory / "jobs.json").read_text())["jobs"]
        if not (
            run["head_sha"] == sha
            and run["head_branch"] == "main"
            and run["name"] == "Release Desktop macOS OTA"
            and run["path"] == ".github/workflows/fhd-release-desktop-mac-ota.yml"
            and run["event"] == "workflow_dispatch"
            and run["conclusion"] == "success"
            and artifact["name"] == f"mac-acceptance-{sha}-{arch}"
            and artifact["expired"] is False
            and artifact["workflow_run"]["id"] == run["id"]
            and artifact["workflow_run"]["head_sha"] == sha
            and artifact["digest"] == "sha256:" + digest(directory / "artifact.zip")
            and artifact["size_in_bytes"] == (directory / "artifact.zip").stat().st_size
        ):
            raise ValueError(f"{arch}: Actions artifact/run/digest mismatch")
        native = [
            j
            for j in jobs
            if j["name"] == "macos-ota" and j["conclusion"] == "success" and runner in j["labels"]
        ]
        if len(native) != 1 or not all(
            any(s["name"] == name and s["conclusion"] == "success" for s in native[0]["steps"])
            for name in STEPS
        ):
            raise ValueError(f"{arch}: native notarization/startup evidence missing")
        with zipfile.ZipFile(directory / "artifact.zip") as wrapper:
            members = wrapper.namelist()
            if len(members) != len(set(members)) or any(
                Path(n).is_absolute() or ".." in Path(n).parts for n in members
            ):
                raise ValueError("unsafe or duplicate artifact members")
            payload = directory / "payload"
            if payload.exists():
                raise ValueError("payload destination must be new")
            wrapper.extractall(payload)
        name = f"XCAGI-Enterprise-{version}-mac-{arch}"
        archives = list(payload.rglob(name + ".zip"))
        if len(archives) != 1:
            raise ValueError(f"{arch}: unique canonical ZIP required")
        archive = archives[0]
        dmg = archive.with_suffix(".dmg")
        if not dmg.is_file():
            raise ValueError(f"{arch}: canonical DMG missing")
        feed = (archive.parent / "latest-mac.yml").read_text()
        signatures = [line for line in feed.splitlines() if line.startswith("signature: ed25519:")]
        if len(signatures) != 1:
            raise ValueError("unique original feed signature required")
        body = "\n".join(
            line for line in feed.splitlines() if not line.startswith("signature:")
        ).rstrip()
        key.verify(
            base64.b64decode(signatures[0].split("ed25519:", 1)[1], validate=True), body.encode()
        )
        import yaml

        metadata = yaml.safe_load(body)
        zip_hash = base64.b64encode(bytes.fromhex(digest(archive, "sha512"))).decode()
        entries = [f for f in metadata["files"] if f["url"].endswith(name + ".zip")]
        if (
            metadata.get("buildSha") != sha
            or metadata.get("productVersion") != version
            or len(entries) != 1
            or entries[0]["sha512"] != zip_hash
            or entries[0]["size"] != archive.stat().st_size
        ):
            raise ValueError(f"{arch}: signed feed identity/hash mismatch")
        with zipfile.ZipFile(archive) as app:
            if len(app.namelist()) != len(set(app.namelist())):
                raise ValueError("duplicate application members")
            info = json.loads(app.read("XCAGI.app/Contents/Resources/build-info.json"))
            plist = plistlib.loads(app.read("XCAGI.app/Contents/Info.plist"))
            executable = app.read("XCAGI.app/Contents/MacOS/XCAGI")[:8]
            if (
                info.get("gitSha") != sha
                or info.get("version") != version
                or plist.get("CFBundleVersion") != version
                or plist.get("CFBundleIdentifier") != "com.xcagi.desktop.enterprise"
                or struct.unpack("<II", executable) != (0xFEEDFACF, cpu)
            ):
                raise ValueError(f"{arch}: embedded identity/architecture mismatch")
        startup = json.loads(
            (archive.parent / "acceptance-evidence/installed-startup.json").read_text()
        )
        if (
            startup.get("sha") != sha
            or startup.get("version") != version
            or startup.get("packageSha") != digest(dmg)
            or startup.get("runtime", {}).get("architecture") != arch
            or startup.get("systemIntegration") is not True
        ):
            raise ValueError(f"{arch}: original installed startup identity mismatch")
        row = {
            "architecture": arch,
            "run_id": run["id"],
            "artifact_id": artifact["id"],
            "artifact_digest": artifact["digest"],
            "files": [],
        }
        for path in (archive, dmg, archive.with_name(archive.name + ".blockmap")):
            if not path.is_file():
                raise ValueError(f"{arch}: payload/blockmap missing")
            row["files"].append(
                {"name": path.name, "sha256": digest(path), "size": path.stat().st_size}
            )
            files.append(path)
        rows.append(row)
    output.mkdir(parents=True, exist_ok=False)
    for source in files:
        shutil.copy2(source, output / source.name)
        if digest(source) != digest(output / source.name):
            raise ValueError("staged bytes changed")
    entries = []
    for arch in ("arm64", "x64"):
        path = output / f"XCAGI-Enterprise-{version}-mac-{arch}.zip"
        entries += [
            f"  - url: https://xiu-ci.com/xcagi-v{version}/builds/{sha}/enterprise/{path.name}",
            "    sha512: " + base64.b64encode(bytes.fromhex(digest(path, "sha512"))).decode(),
            f"    size: {path.stat().st_size}",
        ]
    from datetime import UTC, datetime

    primary = output / f"XCAGI-Enterprise-{version}-mac-arm64.zip"
    text = "\n".join(
        [
            f"version: {'.'.join(version.split('.')[:3])}",
            f"productVersion: {version}",
            f"buildSha: {sha}",
            f"releaseId: xcagi-{version}-{sha}",
            "files:",
            *entries,
            f"path: https://xiu-ci.com/xcagi-v{version}/builds/{sha}/enterprise/{primary.name}",
            "sha512: " + base64.b64encode(bytes.fromhex(digest(primary, "sha512"))).decode(),
            f"releaseDate: '{datetime.now(UTC).isoformat()}'",
        ]
    )
    (output / "latest-mac.yml").write_text(text + "\n")
    result = {
        "source_sha": sha,
        "version": version,
        "architectures": rows,
        "scope": "Frozen byte identity only; unsigned merged feed; no customer acceptance or publication PASS",
    }
    (output / "pair-review.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for flag in ("input", "output", "sha", "version"):
        parser.add_argument("--" + flag, required=True)
    args = parser.parse_args()
    prepare(
        Path(args.input),
        Path(args.output),
        args.sha,
        args.version,
        os.environ["XCAGI_UPDATE_ED25519_PUBLIC_KEY"],
    )
