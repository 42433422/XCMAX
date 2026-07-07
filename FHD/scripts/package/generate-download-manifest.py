#!/usr/bin/env python3
"""生成 XCAGI 下载清单 manifest.json + download-release.json。

扫描 release/xcagi-v{version}/{sku}/ 目录,计算每个安装包的 SHA256 + size,
生成两个文件:
  - manifest.json: 完整清单,含 auto_update 和 official_download 两个 channel
  - download-release.json: 向后兼容格式(供 corp-butler / 旧版官网使用)

用法:
    python scripts/package/generate-download-manifest.py \\
        --version 10.0.0 \\
        --output manifest.json \\
        --download-release-output download-release.json

    # CI 中用 --git-sha 传入 commit hash
    python scripts/package/generate-download-manifest.py \\
        --version 10.0.0 \\
        --git-sha abc123def456 \\
        --output manifest.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SCHEMA = "xcagi.download_manifest/v1"
SKUS = ("personal", "enterprise")
WINDOWS_ARCH = "x64"
MAC_ARCHS = ("x64", "arm64")


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_git_sha(explicit: str | None) -> str:
    if explicit:
        return explicit
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def find_artifact(sku_dir: Path, pattern: re.Pattern[str]) -> Path | None:
    matches = sorted(sku_dir.glob("*.exe")) + sorted(sku_dir.glob("*.dmg")) + sorted(sku_dir.glob("*.apk"))
    for m in matches:
        if pattern.match(m.name):
            return m
    return None


def build_artifact_entry(
    sku_dir: Path,
    filename_pattern: str,
    base_url: str,
    sku: str,
    platform_label: str,
    arch: str | None = None,
) -> dict[str, Any] | None:
    pattern = re.compile(filename_pattern)
    artifact = find_artifact(sku_dir, pattern)
    if artifact is None:
        return None
    sha256 = compute_sha256(artifact)
    size = artifact.stat().st_size
    relative = f"{sku}/{artifact.name}"
    url = f"{base_url.rstrip('/')}/{relative}"
    entry: dict[str, Any] = {
        "url": url,
        "filename": artifact.name,
        "sha256": sha256,
        "size": size,
    }
    if arch:
        entry["arch"] = arch
    entry["platform_label"] = platform_label
    return entry


def build_sku_channel(
    release_root: Path,
    version: str,
    base_url: str,
    sku: str,
) -> dict[str, Any]:
    sku_dir = release_root / sku
    channel: dict[str, Any] = {}
    if not sku_dir.is_dir():
        return channel

    win_pattern = rf"^XCAGI-{'Personal' if sku == 'personal' else 'Enterprise'}-Setup-{re.escape(version)}-x64\.exe$"
    win_entry = build_artifact_entry(sku_dir, win_pattern, base_url, sku, "Windows x64")
    if win_entry:
        channel["win"] = win_entry

    for arch in MAC_ARCHS:
        mac_pattern = rf"^XCAGI-{re.escape(version)}-mac-{arch}\.dmg$"
        mac_entry = build_artifact_entry(sku_dir, mac_pattern, base_url, sku, f"macOS {arch}", arch=arch)
        if mac_entry:
            channel.setdefault("mac", []).append(mac_entry)

    android_pattern = rf"^XCAGI-{'Personal' if sku == 'personal' else 'Enterprise'}-Android-{re.escape(version)}\.apk$"
    android_entry = build_artifact_entry(sku_dir, android_pattern, base_url, sku, "Android")
    if android_entry:
        channel["android"] = android_entry

    return channel


def build_manifest(
    release_root: Path,
    version: str,
    git_sha: str,
    auto_update_base: str,
    official_download_base: str,
) -> dict[str, Any]:
    channels: dict[str, Any] = {}
    for channel_name, base in (
        ("auto_update", auto_update_base),
        ("official_download", official_download_base),
    ):
        sku_entries: dict[str, Any] = {}
        for sku in SKUS:
            sku_channel = build_sku_channel(release_root, version, base, sku)
            if sku_channel:
                sku_entries[sku] = sku_channel
        channels[channel_name] = {
            "base_url": base.rstrip("/"),
            **sku_entries,
        }
    return {
        "schema": SCHEMA,
        "version": version,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "git_sha": git_sha,
        "channels": channels,
    }


def write_download_release(
    manifest: dict[str, Any],
    version: str,
    output: Path,
    cos_base_url: str,
    release_root_url: str,
) -> None:
    official = manifest["channels"]["official_download"]
    win_size = 0
    for sku in SKUS:
        sku_entry = official.get(sku, {})
        win = sku_entry.get("win", {})
        if win:
            win_size = max(win_size, win.get("size", 0))
    win_mb = win_size // (1024 * 1024) if win_size else 0
    legacy = {
        "schema": "xcagi.download_release.public/v1",
        "version_lock": "v10",
        "download_version": version,
        "android_version": version,
        "win_installer_mb": win_mb,
        "cos_base_url": cos_base_url,
        "release_root": release_root_url,
        "generated_at": manifest["generated_at"],
        "git_sha": manifest["git_sha"],
    }
    output.write_text(json.dumps(legacy, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="Release version (e.g. 10.0.0)")
    parser.add_argument("--release-dir", default="release", help="Release root directory (default: release)")
    parser.add_argument("--release-subdir", default=None, help="Release subdir (default: xcagi-v{version})")
    parser.add_argument("--output", required=True, help="Output manifest.json path")
    parser.add_argument("--download-release-output", default=None, help="Optional download-release.json output path")
    parser.add_argument("--git-sha", default=None, help="Git SHA (default: auto-detect)")
    parser.add_argument(
        "--auto-update-base",
        default="https://xiu-ci.com/releases/stable",
        help="Base URL for auto-update channel",
    )
    parser.add_argument(
        "--official-download-base",
        default=None,
        help="Base URL for official download channel (default: https://xiu-ci.com/xcagi-v{version})",
    )
    parser.add_argument("--cos-base-url", default="https://xiu-ci.com", help="COS base URL for legacy download-release.json")
    parser.add_argument(
        "--release-root-url",
        default=None,
        help="Release root URL for legacy download-release.json (default: https://xiu-ci.com/xcagi-v{version})",
    )
    args = parser.parse_args()

    version = args.version.lstrip("vV")
    release_subdir = args.release_subdir or f"xcagi-v{version}"
    release_root = Path(args.release_dir) / release_subdir
    if not release_root.is_dir():
        print(f"::error::Release directory missing: {release_root}", file=sys.stderr)
        return 2

    official_base = args.official_download_base or f"https://xiu-ci.com/xcagi-v{version}"
    release_root_url = args.release_root_url or f"https://xiu-ci.com/xcagi-v{version}"

    git_sha = resolve_git_sha(args.git_sha)
    manifest = build_manifest(
        release_root=release_root,
        version=version,
        git_sha=git_sha,
        auto_update_base=args.auto_update_base,
        official_download_base=official_base,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"manifest.json written to {output_path}")

    if args.download_release_output:
        write_download_release(
            manifest=manifest,
            version=version,
            output=Path(args.download_release_output),
            cos_base_url=args.cos_base_url,
            release_root_url=release_root_url,
        )
        print(f"download-release.json written to {args.download_release_output}")

    found_skus = {sku for ch in manifest["channels"].values() for sku in ch if sku not in ("base_url",)}
    if not found_skus:
        print("::error::No artifacts found for any SKU. Build installers before generating manifest.", file=sys.stderr)
        return 3

    print("Manifest summary:")
    for channel_name, channel in manifest["channels"].items():
        for sku in SKUS:
            if sku in channel:
                for plat, entry in channel[sku].items():
                    if isinstance(entry, list):
                        for e in entry:
                            print(f"  {channel_name}/{sku}/{plat}/{e.get('arch', '?')}: {e['filename']} ({e['size']} bytes)")
                    else:
                        print(f"  {channel_name}/{sku}/{plat}: {entry['filename']} ({entry['size']} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
