"""Discovery and uninstall must stay within the library's actual package directories."""

from __future__ import annotations

import json
import logging
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.infrastructure.mods import mod_manager
from app.infrastructure.mods.employee_registry import EmployeeRegistry
from app.infrastructure.mods.manifest import ModMetadata, parse_manifest
from app.infrastructure.mods.registry import ModRegistry


def _manifest(directory: Path, mod_id: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "manifest.json").write_text(
        json.dumps({"id": mod_id, "name": "Boundary fixture", "version": "1.0.0"})
    )


@pytest.fixture
def isolated_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "mods"
    manager = mod_manager.ModManager(str(root))
    registry = ModRegistry()
    monkeypatch.setattr(mod_manager, "get_mod_registry", lambda: registry)
    monkeypatch.setattr(manager, "all_mods_roots", lambda: [str(root)])
    monkeypatch.setattr("app.mod_sdk.employee_runtime.refresh_employee_pack_runtime", Mock())
    return root, manager, registry


@pytest.mark.parametrize("target", [".", ".."])
@pytest.mark.parametrize("entry", ["manager", "employee_registry"])
def test_dot_uninstall_rejects_before_deleting_any_package(isolated_library, target, entry):
    root, manager, _ = isolated_library
    employee = root / "_employees" / "keep-employee"
    ordinary = root / "keep-mod"
    _manifest(employee, "keep-employee")
    _manifest(ordinary, "keep-mod")
    expected = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    remover = manager if entry == "manager" else EmployeeRegistry(str(root))

    result = remover.uninstall_mod(target) if entry == "manager" else remover.uninstall_pack(target)

    actual = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert actual == expected
    assert result[0] is False


def test_registered_traversal_identity_cannot_delete_sibling(isolated_library):
    root, manager, registry = isolated_library
    outside = root.parent / "sibling"
    _manifest(outside, "sibling")
    registry.register_mod(ModMetadata("../sibling", "Malformed identity", "1.0.0"))
    expected = (outside / "manifest.json").read_bytes()

    ok, _ = manager.uninstall_mod("../sibling")

    assert (outside / "manifest.json").read_bytes() == expected
    assert ok is False


@pytest.mark.parametrize("indexed", [False, True])
def test_discovery_does_not_follow_package_directory_symlinks(isolated_library, indexed):
    root, manager, _ = isolated_library
    outside = root.parent / "outside"
    _manifest(outside, "outside")
    linked = root / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    if indexed:
        (root / "mods-index.json").write_text(
            json.dumps(
                {
                    "fingerprint": manager._mods_scan_fingerprint(),
                    "mods": [{"mod_path": str(linked)}],
                }
            )
        )

    assert manager.scan_mods(use_cache=indexed) == []
    assert manager.resolve_mod_directory("linked") is None


def test_uninstall_does_not_follow_mod_directory_symlink(isolated_library):
    root, manager, registry = isolated_library
    outside = root.parent / "outside"
    _manifest(outside, "outside")
    payload = outside / "customer-record.txt"
    payload.write_text("private fixture data", encoding="utf-8")
    expected = payload.read_bytes()
    linked = root / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    registry.register_mod(ModMetadata("linked", "Linked", "1.0.0"))

    ok, _ = manager.uninstall_mod("linked")

    assert ok is True
    assert linked.is_symlink()
    assert payload.read_bytes() == expected


def test_build_index_cannot_promote_an_external_directory(isolated_library):
    root, manager, _ = isolated_library
    outside = root.parent / "outside"
    _manifest(outside, "outside")
    _manifest(root / "valid", "valid")
    (root / "mods-index.json").write_text(
        json.dumps(
            {
                "fingerprint": manager._mods_scan_fingerprint(),
                "mods": [{"mod_path": str(outside)}, {"mod_path": str(root / "valid")}],
            }
        )
    )

    assert [metadata.id for metadata in manager.scan_mods()] == ["valid"]


def test_malformed_index_shape_falls_back_to_live_discovery(isolated_library):
    root, manager, _ = isolated_library
    _manifest(root / "valid", "valid")
    (root / "mods-index.json").write_text("[]")

    assert [metadata.id for metadata in manager.scan_mods()] == ["valid"]


def test_valid_employee_uninstall_keeps_other_packages(isolated_library):
    root, manager, _ = isolated_library
    _manifest(root / "_employees" / "selected", "selected")
    _manifest(root / "_employees" / "keep", "keep")
    _manifest(root / "keep-mod", "keep-mod")

    ok, _ = manager.uninstall_mod("selected")

    assert ok
    assert not (root / "_employees" / "selected").exists()
    assert (root / "_employees" / "keep" / "manifest.json").is_file()
    assert (root / "keep-mod" / "manifest.json").is_file()


def _employee_archive(path: Path, pack_id: str) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "id": pack_id,
                    "name": "Boundary fixture",
                    "version": "1.0.0",
                    "artifact": "employee_pack",
                    "scope": "global",
                    "employee": {"id": "fixture-employee"},
                }
            ),
        )
        archive.writestr("logic.py", "VALUE = 'new employee'\n")


@pytest.mark.parametrize("identity", [".", "..", "../../sibling", "absolute"])
def test_employee_install_rejects_directory_identity_before_removal(
    isolated_library, tmp_path: Path, identity
):
    root, _, _ = isolated_library
    sibling = tmp_path / "sibling"
    keep = root / "_employees" / "keep"
    _manifest(sibling, "sibling")
    _manifest(keep, "keep")
    identity = str(sibling) if identity == "absolute" else identity
    expected = {
        path: path.read_bytes() for path in [sibling / "manifest.json", keep / "manifest.json"]
    }
    archive = tmp_path / "candidate.zip"
    _employee_archive(archive, identity)

    ok, _ = EmployeeRegistry(str(root)).install_from_package(str(archive), verify_signature=False)

    assert all(path.is_file() and path.read_bytes() == data for path, data in expected.items())
    assert ok is False


@pytest.mark.parametrize("link", ["employee-store", "package"])
def test_employee_install_rejects_symlink_destination(isolated_library, tmp_path: Path, link):
    root, _, _ = isolated_library
    outside = tmp_path / "outside"
    selected = outside / "selected"
    _manifest(selected, "selected")
    keep = selected / "manifest.json"
    original = keep.read_bytes()
    if link == "employee-store":
        (root / "_employees").symlink_to(outside, target_is_directory=True)
    else:
        (root / "_employees").mkdir()
        (root / "_employees" / "selected").symlink_to(selected, target_is_directory=True)
    archive = tmp_path / "candidate.zip"
    _employee_archive(archive, "selected")

    ok, _ = EmployeeRegistry(str(root)).install_from_package(str(archive), verify_signature=False)

    assert keep.read_bytes() == original
    assert not (selected / "logic.py").exists()
    assert ok is False


def test_employee_install_valid_archive_stays_in_selected_library(isolated_library, tmp_path: Path):
    root, _, _ = isolated_library
    _manifest(root / "keep-mod", "keep-mod")
    archive = tmp_path / "candidate.zip"
    _employee_archive(archive, "selected")

    ok, message = EmployeeRegistry(str(root)).install_from_package(
        str(archive), verify_signature=False
    )

    assert ok, message
    destination = root / "_employees" / "selected"
    assert (destination / "logic.py").read_text() == "VALUE = 'new employee'\n"
    receipt = json.loads((destination / ".xcagi-install-receipt.json").read_text())
    assert receipt["pack_id"] == "selected"
    assert receipt["signature_verified"] is False
    assert (root / "keep-mod" / "manifest.json").is_file()


def test_discovery_uses_injected_parser_and_owned_cache_without_public_manager(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.infrastructure.mods.management.discovery import DiscoveryPorts, ModDiscovery
    from app.infrastructure.mods.management.paths import trusted_child_path

    @dataclass
    class Cache:
        _scan_cache_fp: str = ""
        _scan_cache_mods: list[ModMetadata] = field(default_factory=list)
        _scan_manifest_errors: list[dict[str, str]] = field(default_factory=list)

    _manifest(tmp_path / "selected", "selected")
    parser = Mock(side_effect=parse_manifest)
    monkeypatch.setattr(
        mod_manager,
        "parse_manifest",
        Mock(side_effect=AssertionError("public root must not be called")),
    )
    cache = Cache()
    discovery = ModDiscovery(
        cache,
        DiscoveryPorts(
            roots=lambda: [str(tmp_path)],
            refresh=lambda: None,
            fingerprint=lambda: "same-files",
            index=lambda fingerprint: None,
            parse=parser,
            child=trusted_child_path,
            logger=logging.getLogger(__name__),
        ),
    )

    first = discovery.scan(use_cache=False)
    second = discovery.scan()

    assert [metadata.id for metadata in second] == ["selected"]
    assert first is not second
    assert cache._scan_cache_fp == "same-files"
    parser.assert_called_once_with(str(tmp_path / "selected"))
