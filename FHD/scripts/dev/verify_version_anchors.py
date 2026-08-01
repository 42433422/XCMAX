#!/usr/bin/env python3
"""Verify product/toolchain version anchors match VERSION.md (read-only)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

PRODUCT_VERSION = "product"
TOOLCHAIN_VERSION = "toolchain"

# (相对路径, 捕获版本号的正则, VERSION.md 中对应的版本口径)
ANCHORS: list[tuple[str, str, str]] = [
    ("pyproject.toml", r'version\s*=\s*"([\d.]+)"', PRODUCT_VERSION),
    ("XCAGI/pyproject.toml", r'version\s*=\s*"([\d.]+)"', PRODUCT_VERSION),
    ("frontend/package.json", r'"version"\s*:\s*"([\d.]+)"', TOOLCHAIN_VERSION),
    ("desktop/package.json", r'"version"\s*:\s*"([\d.]+)"', TOOLCHAIN_VERSION),
    ("package.json", r'"version"\s*:\s*"([\d.]+)"', TOOLCHAIN_VERSION),
    ("XCAGI/package.json", r'"version"\s*:\s*"([\d.]+)"', TOOLCHAIN_VERSION),
    ("admin-console/package.json", r'"version"\s*:\s*"([\d.]+)"', TOOLCHAIN_VERSION),
    ("sunbird-console/package.json", r'"version"\s*:\s*"([\d.]+)"', TOOLCHAIN_VERSION),
    (
        "app/fastapi_app/factory.py",
        r'os\.environ\.get\("XCAGI_VERSION"\)\s+or\s+"([\d.]+)"',
        PRODUCT_VERSION,
    ),
    (
        "app/infrastructure/mods/manifest.py",
        r'os\.environ\.get\("XCAGI_VERSION"\)\s+or\s+"([\d.]+)"',
        PRODUCT_VERSION,
    ),
    ("mobile-flutter-poc/android/app/build.gradle.kts", r'injectedVersionName[\s\S]*?\?:\s*"([\d.]+)"', PRODUCT_VERSION),
    ("mobile-flutter-poc/pubspec.yaml", r'(?m)^version:\s*([\d.]+)\+\d+', TOOLCHAIN_VERSION),
    ("mobile-flutter-poc/ios/Flutter/Version.xcconfig", r'(?m)^FLUTTER_BUILD_NAME=([\d.]+)', TOOLCHAIN_VERSION),
    ("desktop/resources/build-info.json", r'"version"\s*:\s*"([\d.]+)"', PRODUCT_VERSION),
    ("mobile-flutter-poc/lib/src/api/mobile_api.dart", r"versionName\s*=\s*'([\d.]+)'", PRODUCT_VERSION),
    ("config/download_release.json", r'"marketing_version"\s*:\s*"([\d.]+)"', PRODUCT_VERSION),
    ("config/release_train.json", r'"product_version"\s*:\s*"([\d.]+)"', PRODUCT_VERSION),
    ("../成都修茈科技有限公司/FHD/config/release_train.json", r'"product_version"\s*:\s*"([\d.]+)"', PRODUCT_VERSION),
    ("contracts/openapi.json", r'"info"[\s\S]*?"version"\s*:\s*"([\d.]+)"', PRODUCT_VERSION),
    ("setup.iss", r'#define\s+MyAppVersion\s+"([\d.]+)"', PRODUCT_VERSION),
    ("tools/XcagiDownloader/Models/AppSettings.cs", r'return\s+"([\d.]+)";', PRODUCT_VERSION),
    ("scripts/package/build-installer.sh", r'VERSION="\$\{1:-([\d.]+)\}"', PRODUCT_VERSION),
    ("scripts/package/build-installer.ps1", r'\[string\]\$Version\s*=\s*"([\d.]+)"', PRODUCT_VERSION),
    ("release/VERSION", r'(?m)^([\d.]+)$', PRODUCT_VERSION),
]


def canonical_version() -> str:
    """从 VERSION.md 动态读取稳定产品版本（四段）。唯一数字 SSOT 出口。"""
    version_md = REPO_ROOT / "VERSION.md"
    if not version_md.is_file():
        raise FileNotFoundError(f"missing {version_md}")
    for line in version_md.read_text(encoding="utf-8").splitlines():
        if "**XCAGI 稳定产品版本**" in line:
            match = re.search(r"`([\d.]+)`", line)
            if match:
                return match.group(1)
    raise ValueError("could not parse stable product version from VERSION.md")


def toolchain_version() -> str:
    """从 VERSION.md 动态读取工具链兼容版本（三段）。"""
    version_md = REPO_ROOT / "VERSION.md"
    if not version_md.is_file():
        raise FileNotFoundError(f"missing {version_md}")
    for line in version_md.read_text(encoding="utf-8").splitlines():
        if "**工具链兼容版本**" in line:
            match = re.search(r"`([\d.]+)`", line)
            if match:
                return match.group(1)
    raise ValueError("could not parse toolchain version from VERSION.md")


# 兼容旧私有名；新代码请用 canonical_version / toolchain_version
_canonical_version = canonical_version
_toolchain_version = toolchain_version


def _expected_versions() -> dict[str, str]:
    return {
        PRODUCT_VERSION: canonical_version(),
        TOOLCHAIN_VERSION: toolchain_version(),
    }


def verify() -> list[str]:
    expected_versions = _expected_versions()
    errors: list[str] = []
    for rel_path, pattern, version_kind in ANCHORS:
        full_path = REPO_ROOT / rel_path
        if not full_path.is_file():
            errors.append(f"{rel_path}: file not found")
            continue
        match = re.search(pattern, full_path.read_text(encoding="utf-8"))
        if not match:
            errors.append(f"{rel_path}: version pattern not found")
            continue
        found = match.group(1)
        expected = expected_versions[version_kind]
        if found != expected:
            errors.append(f"{rel_path}: expected {version_kind} version {expected}, found {found}")
    return errors


def main() -> int:
    errors = verify()
    if errors:
        print("Version anchor mismatches:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    versions = _expected_versions()
    print(
        "OK: all anchors match "
        f"product={versions[PRODUCT_VERSION]}, toolchain={versions[TOOLCHAIN_VERSION]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
