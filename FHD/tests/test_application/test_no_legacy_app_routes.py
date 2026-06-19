"""Architecture guard: the legacy app.routes package must stay removed."""

from __future__ import annotations

import re
from pathlib import Path


FHD_ROOT = Path(__file__).resolve().parents[2]
LEGACY_IMPORT_RE = re.compile(
    r"\bfrom\s+app\.routes\.(?:tools|ai_chat|template_grid_core|document_templates_compat|state)\b"
    r"|\bimport\s+app\.routes\.(?:tools|ai_chat|template_grid_core|document_templates_compat|state)\b"
    r"|[\"']app\.routes\.(?:tools|ai_chat|template_grid_core|document_templates_compat|state)\b"
)


def _py_files() -> list[Path]:
    roots = [FHD_ROOT / "app", FHD_ROOT / "tests", FHD_ROOT / "scripts", FHD_ROOT / "resources"]
    return sorted(path for root in roots for path in root.rglob("*.py"))


def test_legacy_app_routes_package_is_removed() -> None:
    assert not (FHD_ROOT / "app" / "routes").exists()


def test_no_legacy_app_routes_imports_or_patch_targets() -> None:
    offenders = []
    for path in _py_files():
        text = path.read_text(encoding="utf-8")
        if LEGACY_IMPORT_RE.search(text):
            offenders.append(path.relative_to(FHD_ROOT).as_posix())

    assert offenders == []
