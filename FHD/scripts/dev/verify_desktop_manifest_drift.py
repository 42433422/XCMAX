#!/usr/bin/env python3
"""桌面下载中心 manifest 与线上制品一致性检测（审计 R03 制度化）.

背景：2026-09-04 的 macOS OTA 发布在上传步骤被取消，制品与 latest-mac.yml 已更新、
但 `xcagi-v<version>/manifest.json` 未再生，导致 manifest 声称的 sha256/size 与
线上实际 dmg/zip 脱节（同版本 5 个构建 gitSha 并存）。本脚本以只读 HTTP 方式核对：

1. 每个制品条目声明的 `size` 与实际 `Content-Length` 一致（轻量模式，默认）；
2. `--full-sha256` 时下载制品并核对 `sha256`（高成本，供发布后手动跑）。

漂移即 exit 1（fail-closed），供 CI 日检与发布后验证复用。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from typing import Any

BASE_URL = "https://xiu-ci.com"
USER_AGENT = "xcagi-manifest-drift/1.0"


def _fetch(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed public host
        return resp.read()


def _content_length(url: str, timeout: int = 30) -> int | None:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            value = resp.headers.get("Content-Length")
            return int(value) if value is not None else None
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _iter_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    channels = manifest.get("channels") or {}
    for channel in channels.values():
        if not isinstance(channel, dict):
            continue
        for sku_block in channel.values():
            if not isinstance(sku_block, dict):
                continue
            for platform_items in sku_block.values():
                if isinstance(platform_items, list):
                    entries.extend(item for item in platform_items if isinstance(item, dict))
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="产品版本，如 1.0.0.1")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument(
        "--full-sha256",
        action="store_true",
        help="下载每个制品核对 sha256（高带宽成本）；默认只做 HEAD 尺寸核对",
    )
    parser.add_argument("--output", type=str, help="JSON 报告输出路径")
    args = parser.parse_args()

    manifest_url = f"{args.base_url}/xcagi-v{args.version}/manifest.json"
    try:
        manifest = json.loads(_fetch(manifest_url).decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(json.dumps({"passed": False, "error": f"manifest_fetch_failed:{exc}"}))
        return 1

    if str(manifest.get("version")) != args.version:
        print(
            json.dumps(
                {
                    "passed": False,
                    "error": f"manifest_version_mismatch:{manifest.get('version')}!={args.version}",
                }
            )
        )
        return 1

    drift: list[dict[str, Any]] = []
    checked = 0
    for entry in _iter_entries(manifest):
        url = str(entry.get("url") or "")
        if not url.startswith("http"):
            url = f"{args.base_url.rstrip('/')}/{url.lstrip('/')}"
        declared_size = entry.get("size")
        filename = str(entry.get("filename") or url.rsplit("/", 1)[-1])
        checked += 1
        actual_size = _content_length(url)
        if actual_size is None:
            drift.append({"filename": filename, "reason": "artifact_unreachable", "url": url})
            continue
        if declared_size is not None and int(declared_size) != actual_size:
            drift.append(
                {
                    "filename": filename,
                    "reason": "size_mismatch",
                    "declared_size": declared_size,
                    "actual_size": actual_size,
                    "url": url,
                }
            )
            continue
        if args.full_sha256 and entry.get("sha256"):
            digest = hashlib.sha256(_fetch(url, timeout=600)).hexdigest()
            if digest != str(entry["sha256"]).lower():
                drift.append(
                    {
                        "filename": filename,
                        "reason": "sha256_mismatch",
                        "declared": entry["sha256"],
                        "actual": digest,
                        "url": url,
                    }
                )

    report = {
        "schema": "desktop-manifest-drift/v1",
        "version": args.version,
        "manifest_git_sha": manifest.get("git_sha"),
        "entries_checked": checked,
        "mode": "full-sha256" if args.full_sha256 else "size-only",
        "passed": not drift,
        "drift": drift,
    }
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(rendered)
    print(rendered, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
