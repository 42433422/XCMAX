from __future__ import annotations

import re
from pathlib import Path

from packaging.version import Version

FHD_ROOT = Path(__file__).resolve().parents[2]
DESKTOP_LOCK = FHD_ROOT / "XCAGI" / "requirements-desktop.lock.txt"
SERVER_LOCK = FHD_ROOT / "deploy" / "requirements-server.lock.txt"


def _pin(path: Path, package: str) -> Version:
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"(?im)^{re.escape(package)}==([^\s;]+)", text)
    assert match is not None, f"missing exact pin for {package} in {path}"
    return Version(match.group(1))


def test_superseded_dependency_manifest_paths_cannot_return() -> None:
    assert not (FHD_ROOT / "XCAGI" / "requirements.lock.txt").exists()
    assert not (FHD_ROOT / "deploy" / "requirements-server-api.lock.txt").exists()
    assert DESKTOP_LOCK.is_file()
    assert SERVER_LOCK.is_file()


def test_high_severity_dependency_floors_are_pinned_in_new_ssot() -> None:
    assert _pin(DESKTOP_LOCK, "aiohttp") >= Version("3.14.3")
    assert _pin(DESKTOP_LOCK, "cryptography") >= Version("50.0.0")
    assert _pin(DESKTOP_LOCK, "pillow") >= Version("12.3.0")
    assert _pin(DESKTOP_LOCK, "transformers") >= Version("5.10.0")
    assert _pin(SERVER_LOCK, "pillow") >= Version("12.3.0")
