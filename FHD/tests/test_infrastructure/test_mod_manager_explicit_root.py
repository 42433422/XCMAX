"""An explicitly selected Mod library must never redirect writes to another library."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.infrastructure.mods import mod_manager
from app.infrastructure.mods.install_receipts import read_verified_install
from app.infrastructure.mods.package import ModPackage


@pytest.fixture
def isolated_roots(tmp_path, monkeypatch):
    fallback = tmp_path / "other-library"
    fallback.mkdir()
    (fallback / "keep.txt").write_text("other library must remain unchanged")
    default = Mock(return_value=str(fallback))
    monkeypatch.setattr(mod_manager, "_default_mods_root", default)
    monkeypatch.setattr(mod_manager, "_repo_layout_mods_candidates", lambda: [])
    monkeypatch.setenv("XCAGI_MODS_ROOT", str(fallback))
    monkeypatch.delenv("XCAGI_MODS_DIR", raising=False)
    return tmp_path / "selected" / "mods", fallback, default


@pytest.mark.parametrize("as_path,env_override", [(False, False), (True, True)])
def test_missing_explicit_root_installs_real_signed_package_only_there(
    isolated_roots, tmp_path, monkeypatch, as_path, env_override
):
    selected, fallback, default = isolated_roots
    if not env_override:
        monkeypatch.delenv("XCAGI_MODS_ROOT")
    key = Ed25519PrivateKey.generate()
    private_key = tmp_path / "synthetic-key.pem"
    private_key.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    monkeypatch.setattr(
        "app.infrastructure.mods.trusted_keys.load_trusted_public_keys",
        lambda: [key.public_key()],
    )
    source = tmp_path / "source"
    source.mkdir()
    (source / "manifest.json").write_text(
        json.dumps({"id": "root-fixture", "name": "Root fixture", "version": "1.0.0"})
    )
    (source / "logic.py").write_text("VALUE = 'signed selected library'\n")
    package = ModPackage(str(source)).create_package(
        str(tmp_path / "packages"), include_signature=True, private_key=str(private_key)
    )
    manager = mod_manager.ModManager(selected if as_path else str(selected))
    ok, message, metadata = manager.install_mod_package(package, activate=False)
    assert ok, message
    assert metadata.id == "root-fixture"
    assert selected.is_dir()
    assert manager.mods_root == str(selected)
    assert (selected / "root-fixture/logic.py").read_bytes() == (source / "logic.py").read_bytes()
    receipt = read_verified_install("root-fixture", mods_root=str(selected))
    assert receipt["package_version"] == "1.0.0"
    assert receipt["runtime_status"] == "installed"
    assert list(fallback.iterdir()) == [fallback / "keep.txt"]
    assert (fallback / "keep.txt").read_text() == "other library must remain unchanged"
    default.assert_not_called()


def test_explicit_file_path_is_rejected_without_fallback(isolated_roots):
    selected, fallback, default = isolated_roots
    selected.parent.mkdir()
    selected.write_text("this is a file")
    with pytest.raises(FileExistsError):
        mod_manager.ModManager(str(selected))
    assert selected.read_text() == "this is a file"
    assert list(fallback.iterdir()) == [fallback / "keep.txt"]
    default.assert_not_called()


def test_explicit_creation_failure_is_reported_without_fallback(isolated_roots, monkeypatch):
    selected, fallback, default = isolated_roots

    def refuse(path, *, exist_ok):
        assert path == str(selected)
        raise PermissionError("selected library is not writable")

    monkeypatch.setattr(mod_manager.os, "makedirs", refuse)
    with pytest.raises(PermissionError, match="selected library"):
        mod_manager.ModManager(str(selected))
    assert not selected.exists()
    assert list(fallback.iterdir()) == [fallback / "keep.txt"]
    default.assert_not_called()


def test_explicit_relative_root_stays_fixed_after_cwd_env_and_directory_change(
    isolated_roots, tmp_path, monkeypatch
):
    selected, fallback, default = isolated_roots
    monkeypatch.chdir(tmp_path)
    manager = mod_manager.ModManager("selected/mods")
    assert manager.mods_root == str(selected)
    selected.rmdir()
    monkeypatch.chdir(fallback)
    monkeypatch.setenv("XCAGI_MODS_ROOT", str(fallback))
    manager._refresh_mods_root_if_needed()
    assert selected.is_dir()
    assert manager.mods_root == str(selected)
    default.assert_not_called()


def test_empty_explicit_root_is_not_default_selection(isolated_roots):
    _, _, default = isolated_roots
    with pytest.raises(ValueError, match="mods_root"):
        mod_manager.ModManager("")
    default.assert_not_called()


def test_no_argument_keeps_existing_default_and_environment_refresh(isolated_roots):
    _, fallback, default = isolated_roots
    manager = mod_manager.ModManager()
    assert manager.mods_root == str(fallback)
    default.assert_called_once_with()


def test_no_argument_real_default_resolver_tracks_environment(tmp_path, monkeypatch):
    first = tmp_path / "default-one"
    second = tmp_path / "default-two"
    first.mkdir()
    second.mkdir()
    monkeypatch.setenv("XCAGI_MODS_ROOT", str(first))
    monkeypatch.delenv("XCAGI_MODS_DIR", raising=False)
    manager = mod_manager.ModManager()
    assert manager.mods_root == str(first)
    monkeypatch.setenv("XCAGI_MODS_ROOT", str(second))
    manager._refresh_mods_root_if_needed()
    assert manager.mods_root == str(second)
