from __future__ import annotations

from pathlib import Path

import pytest

from modman.blueprint_scan import scan_flask_route_decorators


def test_scan_taiyangniao_mod_blueprints() -> None:
    root = Path(__file__).resolve().parent.parent
    py = root / "library" / "taiyangniao-pro" / "backend" / "blueprints.py"
    if not py.is_file():
        pytest.skip("taiyangniao-pro 未安装到 library/（CI 仅有源码，无运行时 mods）")
    routes = scan_flask_route_decorators(py)
    paths = {(r["path"], tuple(r["methods"])) for r in routes}
    assert ("/hello", ("GET",)) in paths
    assert ("/attendance/rules", ("GET",)) in paths


def test_scan_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "x.py"
    p.write_text("def foo():\n    pass\n", encoding="utf-8")
    assert scan_flask_route_decorators(p) == []


def test_scan_surface_bundle_loads() -> None:
    from modman.surface_bundle import bundled_extension_surface_path, load_bundled_extension_surface

    if not bundled_extension_surface_path().is_file():
        pytest.skip("extension_surface.json 未生成（CI 无构建步骤，需本地先 generate）")
    d = load_bundled_extension_surface()
    assert d.get("schema_version") == 1
    assert "manifest_contract" in d
