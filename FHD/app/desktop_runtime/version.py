"""Resolve the product version used by the packaged desktop runtime."""

from __future__ import annotations

import json
import os
import re
import sys
from importlib import metadata
from pathlib import Path

_DEFAULT_PRODUCT_VERSION = "10.0.0"
_UNKNOWN_VERSIONS = frozenset({"", "dev", "latest", "none", "null", "unknown"})
_SAFE_VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$")


def _normalize_version(value: object) -> str | None:
    raw = str(value or "").strip()
    if raw.lower() in _UNKNOWN_VERSIONS:
        return None
    if len(raw) > 1 and raw[0] in {"v", "V"} and raw[1].isdigit():
        raw = raw[1:]
    if not _SAFE_VERSION.fullmatch(raw):
        return None
    return raw


def _build_info_candidates() -> list[Path]:
    """Return build-info paths for source, PyInstaller, and Electron installs.

    A Windows install has this shape::

        resources/build-info.json
        resources/backend/xcagi-backend.exe
        resources/backend/_internal/build-info.json

    The top-level file identifies the Electron product build.  The internal
    copy makes the standalone backend and scheduled backup task self-contained.
    """

    paths: list[Path] = []
    explicit = (os.environ.get("XCAGI_BUILD_INFO_FILE") or "").strip()
    if explicit:
        paths.append(Path(explicit).expanduser())

    executable_dir = Path(sys.executable).resolve().parent
    paths.extend(
        [
            executable_dir.parent / "build-info.json",
            executable_dir / "_internal" / "build-info.json",
            executable_dir / "build-info.json",
        ]
    )

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        frozen_root = Path(meipass).resolve()
        paths.extend(
            [
                frozen_root / "build-info.json",
                frozen_root.parent / "build-info.json",
                frozen_root.parent.parent / "build-info.json",
            ]
        )

    # Source/development fallback. Formal installers resolve one of the paths
    # above and do not depend on the source tree being present.
    paths.append(Path(__file__).resolve().parents[2] / "desktop" / "resources" / "build-info.json")

    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path not in seen:
            unique.append(path)
            seen.add(path)
    return unique


def _version_from_build_info(path: Path) -> str | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return _normalize_version(payload.get("version"))


def resolve_runtime_version(preferred: str | None = None) -> str:
    """Resolve a safe, non-``unknown`` version for backup artifact names.

    Explicit caller/environment values remain supported for development, but
    a formal install needs no user-managed environment variable: it reads the
    build identity shipped beside the Electron and PyInstaller runtimes.
    """

    for value in (preferred, os.environ.get("XCAGI_VERSION")):
        normalized = _normalize_version(value)
        if normalized:
            return normalized

    for path in _build_info_candidates():
        resolved = _version_from_build_info(path)
        if resolved:
            return resolved

    try:
        installed_version = _normalize_version(metadata.version("xcagi"))
    except metadata.PackageNotFoundError:
        installed_version = None
    return installed_version or _DEFAULT_PRODUCT_VERSION
