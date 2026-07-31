#!/usr/bin/env python3
"""Generate manifest.json and download-release.json for XCAGI releases.

Outputs an enterprise-only stable manifest with two channels:
  - auto_update:       {base}/{sku}/{filename}      (electron-updater)
  - official_download: {base}/{sku}/{filename}      (官网下载页)

Manifest schema (verified by scripts/deploy/verify-download.sh):
{
  "version": "1.0.0.1",
  "git_sha": "...",
  "generated_at": "ISO-8601",
  "channels": {
    "auto_update": {
      "base_url": "https://xiu-ci.com/releases/stable",
      "enterprise": { ... }
    },
    "official_download": {
      "base_url": "https://xiu-ci.com/xcagi-v1.0.0.1",
      ...
    }
  }
}

macOS uses an array because a single SKU may ship multiple arches (arm64 + x64).
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

# Product-line SSOT: specs/product-lines-3-plus-2.md.
# Personal remains build-compatible for a future recovery, but it is frozen and must
# never enter the current stable release manifest.
ACTIVE_RELEASE_SKUS = ("enterprise",)
FROZEN_RELEASE_SKUS = ("personal",)


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def detect_platform(filename: str) -> str | None:
    name = filename.lower()
    if name.endswith(".exe"):
        return "win"
    if name.endswith(".dmg"):
        return "mac"
    if name.endswith(".pkg"):
        return "mac"
    if name.endswith(".apk"):
        return "android"
    return None


def build_entry(base_url: str, sku: str, file_path: Path) -> dict:
    return {
        "url": f"{base_url.rstrip('/')}/{sku}/{file_path.name}",
        "sha256": compute_sha256(file_path),
        "size": file_path.stat().st_size,
        "filename": file_path.name,
    }


def collect_sku_files(release_root: Path, sku: str) -> list[Path]:
    sku_dir = release_root / sku
    if not sku_dir.is_dir():
        return []
    files: list[Path] = []
    for path in sorted(sku_dir.iterdir()):
        if not path.is_file():
            continue
        name = path.name
        if name.endswith(".blockmap"):
            continue
        if name.startswith("latest") and name.endswith((".yml", ".yaml")):
            continue
        if name in {"manifest.json", "download-release.json"}:
            continue
        if detect_platform(name) is None:
            continue
        files.append(path)
    return files


def build_channel(base_url: str, release_root: Path) -> dict:
    channel: dict = {"base_url": base_url}
    for sku in ACTIVE_RELEASE_SKUS:
        sku_files = collect_sku_files(release_root, sku)
        if not sku_files:
            continue
        sku_section: dict = {}
        for path in sku_files:
            platform = detect_platform(path.name)
            if platform is None:
                continue
            entry = build_entry(base_url, sku, path)
            if platform == "mac":
                sku_section.setdefault("mac", []).append(entry)
            else:
                sku_section[platform] = entry
        if sku_section:
            channel[sku] = sku_section
    return channel


def win_installer_mb(release_root: Path) -> int:
    for sku in ACTIVE_RELEASE_SKUS:
        for path in collect_sku_files(release_root, sku):
            if path.name.endswith(".exe"):
                return int(round(path.stat().st_size / (1024 * 1024)))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--release-dir", required=True, help="Root containing <release-subdir>/<sku>/"
    )
    parser.add_argument(
        "--release-subdir", required=True, help="Subdirectory name like xcagi-v1.0.0.1"
    )
    parser.add_argument("--git-sha", required=True)
    parser.add_argument(
        "--android-version",
        default="",
        help="Published enterprise Android product version to preserve in the website pointer.",
    )
    parser.add_argument(
        "--android-git-sha",
        default="",
        help="Git SHA of the separately guarded enterprise Android artifact.",
    )
    parser.add_argument("--output", required=True, help="manifest.json output path")
    parser.add_argument(
        "--download-release-output",
        required=True,
        help="download-release.json output path",
    )
    parser.add_argument(
        "--auto-update-base",
        default="https://xiu-ci.com/releases/stable",
    )
    parser.add_argument(
        "--official-download-base",
        default=None,
        help="Defaults to https://xiu-ci.com/xcagi-v{version}",
    )
    args = parser.parse_args()

    official_base = args.official_download_base or f"https://xiu-ci.com/xcagi-v{args.version}"
    release_root = Path(args.release_dir) / args.release_subdir
    if not release_root.is_dir():
        print(f"[error] release root not found: {release_root}", file=sys.stderr)
        return 1

    auto_update = build_channel(args.auto_update_base, release_root)
    official_download = build_channel(official_base, release_root)
    release_ready = all(
        official_download.get(sku, {}).get("win") and official_download.get(sku, {}).get("mac")
        for sku in ACTIVE_RELEASE_SKUS
    )

    manifest = {
        "schema": "xcagi.download_manifest/v1",
        "version": args.version,
        "release_ready": release_ready,
        "active_skus": list(ACTIVE_RELEASE_SKUS),
        "frozen_skus": list(FROZEN_RELEASE_SKUS),
        "primary_sku": "enterprise",
        "git_sha": args.git_sha,
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "channels": {
            "auto_update": auto_update,
            "official_download": official_download,
        },
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"[ok] wrote {output_path} ({output_path.stat().st_size} bytes)")

    download_release = {
        "schema": "xcagi.download_release.public/v1",
        "version_lock": args.version,
        "download_version": args.version,
        "release_ready": release_ready,
        "active_skus": list(ACTIVE_RELEASE_SKUS),
        "frozen_skus": list(FROZEN_RELEASE_SKUS),
        "primary_sku": "enterprise",
        "git_sha": args.git_sha,
        "generated_at": manifest["generated_at"],
        "win_installer_mb": win_installer_mb(release_root),
        "cos_base_url": official_base,
        "release_root": official_base,
        "manifest_url": f"{official_base}/manifest.json",
        "auto_update_base": args.auto_update_base,
    }
    if args.android_version:
        download_release["android_version"] = args.android_version
    if args.android_git_sha:
        download_release["android_git_sha"] = args.android_git_sha

    dr_output = Path(args.download_release_output)
    dr_output.parent.mkdir(parents=True, exist_ok=True)
    dr_output.write_text(
        json.dumps(download_release, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"[ok] wrote {dr_output} ({dr_output.stat().st_size} bytes)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
