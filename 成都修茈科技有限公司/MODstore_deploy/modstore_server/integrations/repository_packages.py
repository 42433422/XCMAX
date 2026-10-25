"""Explicit optional package boundary for author governance and pack building.

Production installs these packages in its release venv. Source checkouts may
resolve only the two declared monorepo packages; missing or broken dependencies
raise ImportError so governance callers retain their fail-closed behavior.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import ModuleType

_PACKAGES = frozenset({"retort_engine", "xcagi_common"})


def load_repository_module(name: str) -> ModuleType:
    package = name.partition(".")[0]
    if package not in _PACKAGES:
        raise ImportError(f"undeclared repository package: {package}")
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != package:
            raise ImportError(
                f"{package} has an unavailable dependency: {exc.name}"
            ) from exc

    monorepo = (
        Path(
            os.environ.get("XCMAX_MONOREPO_ROOT") or Path(__file__).resolve().parents[4]
        )
        .expanduser()
        .resolve()
    )
    configured = (
        os.environ.get("MODSTORE_RETORT_ENGINE_ROOT")
        if package == "retort_engine"
        else None
    )
    root = (
        Path(configured).expanduser().resolve()
        if configured
        else monorepo / "packages" / package
    )
    if (
        not (root / "pyproject.toml").is_file()
        or not (root / package / "__init__.py").is_file()
    ):
        raise ImportError(
            f"{package} is required; install the declared local package in the release"
        )
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return importlib.import_module(name)
