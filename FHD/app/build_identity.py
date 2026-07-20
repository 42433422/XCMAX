"""Runtime-visible identity of the exact tested release artifact."""

from __future__ import annotations

import json
import os
import subprocess
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


def _local_git_sha() -> str:
    root = _release_root()
    if not (root / ".git").exists():
        return ""
    try:
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


def build_identity() -> dict[str, str]:
    packaged = _identity_file()
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
    return {
        "artifact_sha256": artifact_sha256,
        "built_at": str(packaged.get("built_at") or ""),
        "git_sha": git_sha,
        "image_digest": image_digest,
    }


__all__ = ["build_identity"]
