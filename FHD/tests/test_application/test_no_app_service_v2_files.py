"""Architecture guard: application services must not reintroduce *_v2 files."""

from __future__ import annotations

from pathlib import Path


def test_application_layer_has_no_app_service_v2_modules() -> None:
    app_root = Path(__file__).resolve().parents[2] / "app" / "application"
    offenders = sorted(
        p.relative_to(app_root.parent.parent).as_posix()
        for p in app_root.glob("*_app_service_v2.py")
    )
    assert offenders == []


def test_v2_allowlist_has_no_exceptions() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    allowlist = repo_root / "scripts" / "ci" / "v2_versioned_py_allowlist.txt"
    entries = [
        line.strip()
        for line in allowlist.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert entries == []
