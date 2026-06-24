from __future__ import annotations

from pathlib import Path

import pytest

from modman.blueprint_scan import scan_flask_route_decorators

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_scan_example_mod_blueprints(tmp_path: Path) -> None:
    # Use inline fixture so the test is self-contained (library/ is gitignored)
    py = tmp_path / "blueprints.py"
    py.write_text(
        "from flask import Blueprint\n"
        "bp = Blueprint('example', __name__)\n"
        "@bp.route('/hello', methods=['GET'])\n"
        "def hello(): pass\n"
        "@bp.route('/status', methods=['GET'])\n"
        "def status(): pass\n",
        encoding="utf-8",
    )
    routes = scan_flask_route_decorators(py)
    paths = {(r["path"], tuple(r["methods"])) for r in routes}
    assert ("/hello", ("GET",)) in paths
    assert ("/status", ("GET",)) in paths


def test_scan_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "x.py"
    p.write_text("def foo():\n    pass\n", encoding="utf-8")
    assert scan_flask_route_decorators(p) == []


def test_scan_surface_bundle_loads() -> None:
    from modman.surface_bundle import load_bundled_extension_surface

    d = load_bundled_extension_surface()
    if d.get("schema_version") == 0 and "error" in d:
        pytest.skip(f"extension_surface.json not bundled: {d['error']}")
    assert d.get("schema_version") == 1
    assert "manifest_contract" in d
