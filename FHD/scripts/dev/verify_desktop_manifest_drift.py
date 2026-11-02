#!/usr/bin/env python3
"""Read-only current-public-release drift gate (daily size, weekly full SHA-256)."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

BASE_URL = "https://xiu-ci.com"
USER_AGENT = "xcagi-manifest-drift/2.0"
VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){3}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _fetch(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310
        return response.read()


def _content_length(url: str, timeout: int = 30) -> int | None:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310
            length = response.headers.get("Content-Length")
            return int(length) if length is not None else None
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _iter_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for channel in (manifest.get("channels") or {}).values():
        if not isinstance(channel, dict):
            continue
        for sku in channel.values():
            if not isinstance(sku, dict):
                continue
            for platform in sku.values():
                if isinstance(platform, dict) and "url" in platform:
                    entries.append(platform)  # Windows / Android
                elif isinstance(platform, list):
                    entries.extend(item for item in platform if isinstance(item, dict))  # macOS
    return entries


def _trusted(url: str, base_url: str) -> bool:
    target = urllib.parse.urlsplit(url)
    base = urllib.parse.urlsplit(base_url)
    return bool(
        base.scheme == "https" and target.scheme == "https"
        and not target.username and not target.password
        and target.port in (None, 443) and target.hostname
        and (target.hostname == base.hostname or target.hostname.endswith(".xiu-ci.com"))
    )


def _identity(base_url: str, version: str) -> tuple[str, str, str | None]:
    base_url = base_url.rstrip("/")
    if version:
        if not VERSION.fullmatch(version):
            raise ValueError("invalid_version")
        return version, f"{base_url}/xcagi-v{version}/manifest.json", None
    pointer = json.loads(_fetch(f"{base_url}/download-release.json").decode("utf-8"))
    current = str(pointer.get("download_version") or "")
    sha = str(pointer.get("git_sha") or "")
    manifest_url = str(pointer.get("manifest_url") or "")
    if (
        pointer.get("schema") != "xcagi.download_release.public/v1"
        or pointer.get("release_ready") is not True
        or not VERSION.fullmatch(current) or not SHA.fullmatch(sha)
        or pointer.get("version_lock") != current
        or pointer.get("release_id") != f"xcagi-{current}-{sha}"
        or manifest_url != f"{base_url}/xcagi-v{current}/manifest.json"
    ):
        raise ValueError("public_release_pointer_identity_invalid")
    return current, manifest_url, sha


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="", help="Empty checks current public release")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--full-sha256", action="store_true")
    parser.add_argument("--output", type=str)
    args = parser.parse_args()
    report: dict[str, Any] = {
        "schema": "desktop-manifest-drift/v2", "version": args.version,
        "mode": "full-sha256" if args.full_sha256 else "size-only",
        "entries_checked": 0, "passed": False, "drift": [],
    }
    try:
        version, manifest_url, expected_sha = _identity(args.base_url, args.version)
        report["version"] = version
        if not _trusted(manifest_url, args.base_url):
            raise ValueError("untrusted_manifest_url")
        manifest = json.loads(_fetch(manifest_url).decode("utf-8"))
        sha = str(manifest.get("git_sha") or "")
        report["manifest_git_sha"] = sha
        if (
            manifest.get("schema") != "xcagi.download_manifest/v1"
            or manifest.get("version") != version or not SHA.fullmatch(sha)
            or manifest.get("release_id") != f"xcagi-{version}-{sha}"
            or (expected_sha is not None and expected_sha != sha)
        ):
            raise ValueError("manifest_release_identity_mismatch")
        entries = _iter_entries(manifest)
        if not entries:
            raise ValueError("manifest_has_no_artifacts")
        for item in entries:
            report["entries_checked"] += 1
            url = str(item.get("url") or "")
            if url.startswith("/"):
                url = args.base_url.rstrip("/") + url
            name = str(item.get("filename") or "")
            size = item.get("size")
            sha256 = str(item.get("sha256") or "").lower()
            if (
                not name or not _trusted(url, args.base_url)
                or not isinstance(size, int) or size <= 0
                or not DIGEST.fullmatch(sha256) or url.rsplit("/", 1)[-1] != name
            ):
                report["drift"].append({"filename": name, "reason": "invalid_artifact_identity"})
                continue
            actual = _content_length(url)
            if actual != size:
                report["drift"].append({
                    "filename": name, "reason": "size_mismatch_or_unreachable",
                    "expected_size": size, "actual_size": actual,
                })
                continue
            if args.full_sha256:
                try:
                    digest = hashlib.sha256(_fetch(url, timeout=900)).hexdigest()
                except (OSError, ValueError) as exc:
                    report["drift"].append({
                        "filename": name, "reason": "artifact_download_failed",
                        "error": str(exc)[:120],
                    })
                    continue
                if digest != sha256:
                    report["drift"].append({
                        "filename": name, "reason": "sha256_mismatch",
                        "expected_sha256": sha256, "actual_sha256": digest,
                    })
    except (OSError, ValueError, TypeError, KeyError) as exc:
        report["drift"].append({
            "reason": "public_release_or_manifest_unavailable", "error": str(exc)[:160],
        })
    report["passed"] = bool(report["entries_checked"]) and not report["drift"]
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as output:
            output.write(rendered)
    print(rendered, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
