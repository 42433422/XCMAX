"""Runtime-visible identity of the exact tested release artifact."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def _release_root() -> Path:
    configured = (os.environ.get("FHD_DEPLOY_ROOT") or "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[1]


def _identity_file() -> dict[str, Any]:
    path = _release_root() / ".build-identity.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _desktop_identity_file() -> dict[str, Any]:
    """Read Electron's signed resources, never a userData or working directory copy."""
    configured = (os.environ.get("XCAGI_DESKTOP_RESOURCES") or "").strip()
    if configured:
        resources = Path(configured)
    elif getattr(sys, "frozen", False):
        backend = Path(sys.executable).resolve().parent
        if backend.name in {"_internal", "xcagi-backend"} and backend.parent.name == "backend":
            backend = backend.parent
        if backend.name != "backend":
            return {}
        resources = backend.parent
    else:
        return {}
    # Same locations and field aliases as the desktop updater's buildInfoCandidates.
    for path in (resources / "build-info.json", resources / "backend" / "build-info.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        raw_sha = payload.get("gitSha") or payload.get("buildSha") or ""
        raw_version = payload.get("version") or ""
        built_at = payload.get("builtAt") or ""
        if not all(isinstance(value, str) for value in (raw_sha, raw_version, built_at)):
            continue
        sha = str(raw_sha).strip().lower()
        version = str(raw_version).strip()
        if len(sha) != 40 or any(char not in "0123456789abcdef" for char in sha) or not version:
            continue
        release_id = str(payload.get("releaseId") or "").strip()
        if release_id and release_id != f"xcagi-{version}-{sha}":
            continue
        return {
            "git_sha": sha,
            "version": version,
            "built_at": built_at,
            # build_identity derives release_id from the resolved SHA/version,
            # so an explicit identity environment override remains consistent.
        }
    return {}


def _local_git_sha() -> str:
    if getattr(sys, "frozen", False):
        return ""
    root = _release_root()
    try:
        # FHD 通常是仓库子目录，.git 位于上层 XCMAX。git -C 可以自行向上
        # 解析工作树；不要因为 FHD/.git 不存在就把运行身份错误地报成空值。
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _stamp(name: str) -> str:
    try:
        return (_release_root() / name).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _admin_console_identity() -> dict[str, Any]:
    path = _release_root() / "templates" / "admin-vue-dist" / ".release-identity.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def build_identity() -> dict[str, str]:
    packaged = _identity_file() or _desktop_identity_file()
    admin_console = _admin_console_identity()
    git_sha = str(
        os.environ.get("XCAGI_GIT_SHA")
        or os.environ.get("FHD_GIT_SHA")
        or os.environ.get("GIT_SHA")
        or packaged.get("git_sha")
        or _local_git_sha()
        or ""
    ).strip()
    image_digest = str(
        os.environ.get("XCAGI_IMAGE_DIGEST")
        or os.environ.get("FHD_API_IMAGE_DIGEST")
        or packaged.get("image_digest")
        or _stamp(".deploy-image-digest")
        or ""
    ).strip()
    artifact_sha256 = str(
        os.environ.get("XCAGI_ARTIFACT_SHA256")
        or packaged.get("artifact_sha256")
        or _stamp(".deploy-sha256")
        or ""
    ).strip()
    product_version = str(
        os.environ.get("XCMAX_PRODUCT_VERSION")
        or packaged.get("product_version")
        or packaged.get("version")
        or ""
    ).strip()
    release_id = str(
        os.environ.get("XCAGI_RELEASE_ID")
        or packaged.get("release_id")
        or (f"xcagi-{product_version}-{git_sha}" if product_version and git_sha else "")
    ).strip()
    admin_console_sha256 = str(
        os.environ.get("XCAGI_ADMIN_CONSOLE_SHA256")
        or os.environ.get("FHD_ADMIN_CONSOLE_SHA256")
        or packaged.get("admin_console_sha256")
        or admin_console.get("sha256")
        or ""
    ).strip()
    return {
        "admin_console_sha256": admin_console_sha256,
        "admin_console_git_sha": str(admin_console.get("git_sha") or "").strip(),
        "artifact_sha256": artifact_sha256,
        "built_at": str(packaged.get("built_at") or ""),
        "git_sha": git_sha,
        "image_digest": image_digest,
        "product_version": product_version,
        "release_id": release_id,
    }


__all__ = ["build_identity"]
