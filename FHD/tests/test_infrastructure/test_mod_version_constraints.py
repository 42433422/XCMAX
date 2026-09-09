"""Version-aware runtime loading with actual manifests and isolated registries."""

import json
from unittest.mock import Mock

import pytest

from app.infrastructure.mods import mod_manager
from app.infrastructure.mods.manifest import ModMetadata, _check_xcagi_version
from app.infrastructure.mods.registry import ModRegistry
from app.infrastructure.mods.version_constraints import compare_versions, version_satisfies


@pytest.mark.parametrize(
    "version,spec,expected",
    [
        ("1.0.0.1", ">=1.0.0.2", False),
        ("1.0.0.2", ">1.0.0.1", True),
        ("1", "=1.0.0.0", True),
        ("1.2", "!=1.2.0", False),
        ("1.2.3", ">=1.0, <2.0", True),
        ("2.0", ">=1.0 <2.0", False),
        ("1.9", "^1.2", True),
        ("2.0", "^1.2", False),
        ("0.2.9", "^0.2.1", True),
        ("0.3", "^0.2.1", False),
        ("0.0.2", "^0.0.1", False),
        ("1.2.9", "~1.2.1", True),
        ("1.3", "~1.2.1", False),
        ("1.2.3.4", "1.2.*", True),
        ("1.3.0", "1.2.x", False),
        ("1.0", "*", True),
        ("1.0", "garbage", False),
        ("1.0", ">=1.0junk", False),
        ("1.0", ">=1.0,", False),
        ("1.0-rc1", "*", False),
    ],
)
def test_numeric_version_constraints(version, spec, expected):
    assert version_satisfies(version, spec) is expected


def test_trailing_release_segments_are_not_discarded():
    assert compare_versions("1.0.0.1", "1.0.0") == 1
    assert compare_versions("1", "1.0.0") == 0
    assert not _check_xcagi_version(">=1.0.0.2")
    assert not _check_xcagi_version("<1.0.0")
    assert not _check_xcagi_version("unknown")


@pytest.mark.parametrize("mode", ["single", "all"])
@pytest.mark.parametrize("installed,allowed", [("1.0.0.1", False), ("1.0.0.2", True)])
def test_loader_checks_registered_dependency_version_before_backend_initialization(
    tmp_path, monkeypatch, mode, installed, allowed
):
    registry = ModRegistry()
    registry.register_mod(ModMetadata(id="dependency", name="Dependency", version=installed))
    monkeypatch.setattr(mod_manager, "get_mod_registry", lambda: registry)
    monkeypatch.setattr("app.mod_sdk.product_skus.assert_mod_allowed_for_sku", lambda *_: None)
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise", lambda *_: True
    )
    directory = tmp_path / "dependent"
    directory.mkdir()
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "id": "dependent",
                "name": "Dependent",
                "version": "1.0",
                "dependencies": {"dependency": ">=1.0.0.2"},
            }
        )
    )
    manager = mod_manager.ModManager(mods_root=str(tmp_path))
    monkeypatch.setattr(manager, "all_mods_roots", lambda: [str(tmp_path)])
    backend = Mock()
    monkeypatch.setattr(manager, "_load_mod_backend", backend)
    if mode == "single":
        assert manager.load_mod("dependent") is allowed
    else:
        assert ("dependent" in manager.load_all_mods()) is allowed
    assert bool(registry.get_mod_metadata("dependent")) is allowed
    assert backend.call_count == int(allowed)
