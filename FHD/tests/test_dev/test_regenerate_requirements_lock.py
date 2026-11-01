"""Targeted runtime lock updates must preserve unrelated deployment pins."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.dev import regenerate_requirements_lock as tool


@pytest.fixture
def lock_files(tmp_path, monkeypatch):
    requirements = tmp_path / "requirements-server-api.txt"
    lock = tmp_path / "requirements-server-api.lock.txt"
    requirements.write_text("openpyxl==3.1.5\ndefusedxml==0.7.1\n", encoding="utf-8")
    lock.write_text("# deployment pins\nopenpyxl==3.1.5\n", encoding="utf-8")
    monkeypatch.setattr(tool, "REQ", requirements)
    monkeypatch.setattr(tool, "LOCK", lock)
    monkeypatch.setattr(
        tool,
        "distributions",
        lambda: [
            SimpleNamespace(metadata={"Name": "openpyxl"}, version="99.0.0"),
            SimpleNamespace(metadata={"Name": "defusedxml"}, version="0.7.1"),
        ],
    )
    return requirements, lock


def test_targeted_update_uses_installed_metadata_and_preserves_other_pins(lock_files):
    _, lock = lock_files

    assert tool.main(["--package", "defusedxml"]) == 0
    assert lock.read_text(encoding="utf-8") == (
        "# deployment pins\nopenpyxl==3.1.5\ndefusedxml==0.7.1\n"
    )


def test_targeted_update_replaces_existing_normalized_pin(lock_files):
    requirements, lock = lock_files
    requirements.write_text("openpyxl\nDefusedXML==0.7.1\n", encoding="utf-8")
    lock.write_text("openpyxl==3.1.5\ndefusedxml==0.6.0\n", encoding="utf-8")

    assert tool.main(["--package", "DEFUSEDXML"]) == 0
    assert lock.read_text(encoding="utf-8") == "openpyxl==3.1.5\nDefusedXML==0.7.1\n"


@pytest.mark.parametrize(
    "failure", ["undeclared", "missing_lock", "missing_installed", "missing_other_pin"]
)
def test_targeted_update_refuses_incomplete_inputs_without_writing(
    lock_files, monkeypatch, failure
):
    _, lock = lock_files
    package = "defusedxml"
    if failure == "undeclared":
        package = "unrelated"
    elif failure == "missing_lock":
        lock.unlink()
    elif failure == "missing_installed":
        monkeypatch.setattr(tool, "distributions", lambda: [])
    elif failure == "missing_other_pin":
        lock.write_text("# no existing openpyxl pin\n", encoding="utf-8")
    before = lock.read_bytes() if lock.exists() else None

    assert tool.main(["--package", package]) == 1
    assert (lock.read_bytes() if lock.exists() else None) == before


def test_multiple_package_update_does_not_partially_write_on_missing_distribution(
    lock_files, monkeypatch
):
    _, lock = lock_files
    before = lock.read_bytes()
    monkeypatch.setattr(
        tool,
        "distributions",
        lambda: [SimpleNamespace(metadata={"Name": "openpyxl"}, version="99.0.0")],
    )

    assert tool.main(["--package", "openpyxl", "--package", "defusedxml"]) == 1
    assert lock.read_bytes() == before


def test_complete_regeneration_remains_available(lock_files):
    _, lock = lock_files

    assert tool.main([]) == 0
    assert lock.read_text(encoding="utf-8").endswith("openpyxl==99.0.0\ndefusedxml==0.7.1\n")
