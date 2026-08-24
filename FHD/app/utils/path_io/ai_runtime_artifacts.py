"""Resolve mutable AI artifacts outside immutable application bundles.

Development checkouts historically kept training logs next to their seed
resources.  A frozen desktop application must never do that: appending to a
file under ``Contents/Resources`` invalidates the macOS code signature.  This
module preserves the checkout behaviour while routing packaged/runtime writes
to the configured XCAGI user-data directory.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def mutable_ai_artifact_path(relative_path: str | Path, *, source_fallback: Path) -> Path:
    """Return a writable path for an AI runtime artifact.

    ``XCAGI_DATA_DIR`` is set by the desktop launcher.  The frozen fallback is
    defensive so an incomplete launcher configuration still cannot mutate the
    signed bundle.  Source-mode callers without a desktop data directory keep
    their historical repository-local paths.
    """

    configured_root = (
        os.environ.get("XCAGI_DATA_DIR") or os.environ.get("XCAGI_DESKTOP_DATA_DIR") or ""
    ).strip()
    if configured_root:
        root = Path(configured_root).expanduser().resolve()
        return root / "data" / "ai_runtime" / Path(relative_path)

    if bool(getattr(sys, "frozen", False)):
        from app.desktop_runtime.paths import get_desktop_data_dir

        return get_desktop_data_dir() / "data" / "ai_runtime" / Path(relative_path)

    return source_fallback


def readable_ai_artifact_path(relative_path: str | Path, *, bundled_default: Path) -> Path:
    """Prefer an existing user-data artifact and otherwise read the seed file."""

    runtime_path = mutable_ai_artifact_path(relative_path, source_fallback=bundled_default)
    if runtime_path != bundled_default and runtime_path.is_file():
        return runtime_path
    return bundled_default
