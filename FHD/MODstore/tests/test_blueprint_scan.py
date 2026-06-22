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


def test_scan_surface_bundle_missing_returns_error() -> None:
    """extension_surface.json 不存在时 load 函数返回 schema_version=0 的错误字典。"""
    from unittest.mock import patch

    from modman.surface_bundle import load_bundled_extension_surface

    load_bundled_extension_surface.cache_clear()
    with patch("modman.surface_bundle.bundled_extension_surface_path") as mock_p:
        mock_p.return_value = Path("/nonexistent/__test_surface__.json")
        result = load_bundled_extension_surface()
    load_bundled_extension_surface.cache_clear()
    assert result["schema_version"] == 0
    assert "error" in result


def test_scan_surface_bundle_loads() -> None:
    from modman.surface_bundle import bundled_extension_surface_path, load_bundled_extension_surface

    if not bundled_extension_surface_path().is_file():
        pytest.skip("extension_surface.json 未生成（CI 无构建步骤，需本地先 generate）")
    d = load_bundled_extension_surface()
    assert d.get("schema_version") == 1
    assert "manifest_contract" in d
