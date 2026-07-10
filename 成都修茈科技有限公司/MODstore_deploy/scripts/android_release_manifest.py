#!/usr/bin/env python3
"""Create or verify an SKU-scoped XCAGI Android OTA release manifest.

The APK must already have its final public filename and live beside the
manifest.  Publishing therefore becomes: upload/copy APK first, then atomically
replace ``android_release_manifest.json`` last.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_NAME_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$")
_MAX_ANDROID_VERSION_CODE = 2_100_000_000


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("manifest must be a JSON object")
    return raw


def _expected_apk_name(sku: str, version_name: str) -> str:
    edition = "Enterprise" if sku == "enterprise" else "Personal"
    return f"XCAGI-{edition}-Android-{version_name}.apk"


def _validate(raw: dict, *, sku: str, manifest_path: Path) -> dict:
    if raw.get("schema_version") != 1 or raw.get("platform") != "android":
        raise ValueError("unsupported manifest schema or platform")
    if raw.get("channel", "stable") != "stable" or raw.get("sku") != sku:
        raise ValueError("manifest channel or SKU mismatch")
    version_code = raw.get("version_code")
    version_name = str(raw.get("version_name") or "").strip()
    min_version_code = raw.get("min_version_code", 0)
    force_update = raw.get("force_update", False)
    size = raw.get("size")
    sha256 = str(raw.get("sha256") or "").strip().lower()
    if (
        isinstance(version_code, bool)
        or not isinstance(version_code, int)
        or not 1 <= version_code <= _MAX_ANDROID_VERSION_CODE
        or not _VERSION_NAME_RE.fullmatch(version_name)
        or isinstance(min_version_code, bool)
        or not isinstance(min_version_code, int)
        or not 0 <= min_version_code <= version_code
        or not isinstance(force_update, bool)
        or isinstance(size, bool)
        or not isinstance(size, int)
        or size <= 0
        or not _SHA256_RE.fullmatch(sha256)
    ):
        raise ValueError("invalid version, policy, size, or digest fields")
    filename = _expected_apk_name(sku, version_name)
    if raw.get("artifact") != filename:
        raise ValueError(f"artifact must be {filename}")
    parsed = urlsplit(str(raw.get("download_url") or ""))
    path = unquote(parsed.path)
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname not in {"xiu-ci.com", "www.xiu-ci.com"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not path.endswith(f"/download/{sku}/{filename}")
    ):
        raise ValueError("download URL is not an approved SKU-scoped HTTPS URL")
    artifact = manifest_path.parent / filename
    if not artifact.is_file() or artifact.stat().st_size != size:
        raise ValueError("adjacent APK is missing or has the wrong size")
    if _sha256(artifact) != sha256:
        raise ValueError("adjacent APK digest does not match manifest")
    return {
        "ok": True,
        "sku": sku,
        "version_code": version_code,
        "version_name": version_name,
        "download_url": str(raw["download_url"]),
        "sha256": sha256,
        "size": size,
        "manifest": str(manifest_path),
        "artifact": str(artifact),
    }


def _verify(path: Path, sku: str) -> dict:
    raw = _read(path)
    return _validate(raw, sku=sku, manifest_path=path)


def _write(args: argparse.Namespace) -> dict:
    apk = args.apk.resolve()
    output = (args.output or apk.parent / "android_release_manifest.json").resolve()
    if not apk.is_file():
        raise ValueError(f"APK does not exist: {apk}")
    if apk.parent != output.parent:
        raise ValueError(
            "APK and manifest must be in the same controlled release directory"
        )
    expected_name = _expected_apk_name(args.sku, args.version_name)
    if apk.name != expected_name:
        raise ValueError(f"APK filename must be {expected_name}")
    if output.is_file():
        existing = _verify(output, args.sku)
        if args.version_code <= existing["version_code"]:
            raise ValueError(
                "refusing non-increasing release version_code "
                f"{args.version_code} <= {existing['version_code']}"
            )
    raw = {
        "schema_version": 1,
        "platform": "android",
        "channel": "stable",
        "sku": args.sku,
        "version_code": args.version_code,
        "version_name": args.version_name,
        "min_version_code": args.min_version_code,
        "force_update": args.force_update,
        "download_url": args.download_url,
        "sha256": _sha256(apk),
        "size": apk.stat().st_size,
        "artifact": apk.name,
        "published_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    _validate(raw, sku=args.sku, manifest_path=output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(raw, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return _verify(output, args.sku)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    write = subparsers.add_parser(
        "write", help="generate and atomically publish a manifest"
    )
    write.add_argument("--sku", choices=("enterprise", "personal"), required=True)
    write.add_argument("--apk", type=Path, required=True)
    write.add_argument("--output", type=Path)
    write.add_argument("--version-code", type=int, required=True)
    write.add_argument("--version-name", required=True)
    write.add_argument("--min-version-code", type=int, default=0)
    write.add_argument("--force-update", action="store_true")
    write.add_argument("--download-url", required=True)

    check = subparsers.add_parser(
        "check", help="verify a manifest and its adjacent APK"
    )
    check.add_argument("--sku", choices=("enterprise", "personal"), required=True)
    check.add_argument("--manifest", type=Path, required=True)

    args = parser.parse_args()
    try:
        result = (
            _write(args)
            if args.command == "write"
            else _verify(args.manifest, args.sku)
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
