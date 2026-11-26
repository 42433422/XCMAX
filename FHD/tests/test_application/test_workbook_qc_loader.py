"""Workbook QC imports must remain isolated by the resolved trusted pack."""

import os
import py_compile
import sys
from types import ModuleType

import pytest

from app.application.agent_orchestrator.verification_workbook import _qc_package
from app.infrastructure.mods.package import compute_directory_hash


def _pack(root, value):
    package = root / "backend/vendor/excel_qc"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("")
    (package / "coordinates.py").write_text(f"VALUE = {value!r}\n")
    (package / "checks.py").write_text(
        "from .coordinates import VALUE\ndef run_qc(): return VALUE\n"
    )
    return root


def test_same_named_qc_packages_do_not_share_modules_or_versions(tmp_path, monkeypatch):
    # A previously imported public package cannot satisfy a trusted pack load.
    public = ModuleType("excel_qc")
    monkeypatch.setitem(sys.modules, "excel_qc", public)
    first, second = _pack(tmp_path / "first", "one"), _pack(tmp_path / "second", "two")
    with _qc_package(first) as a, _qc_package(second) as b:
        assert a.run_qc() == "one"
        assert b.run_qc() == "two"
        assert a.__package__ != b.__package__
        names = a.__package__, b.__package__
    assert all(not any(key.startswith(name) for key in sys.modules) for name in names)
    assert sys.modules["excel_qc"] is public
    _pack(first, "updated version")
    with _qc_package(first) as current:
        assert current.run_qc() == "updated version"
        assert current.__package__ not in names


def test_failed_qc_import_removes_its_partial_package(tmp_path):
    pack = _pack(tmp_path / "broken", "unused")
    (pack / "backend/vendor/excel_qc/checks.py").write_text("raise ImportError('broken QC')\n")
    before = {name for name in sys.modules if name.startswith("_xcagi_workbook_qc_")}
    finders = list(sys.meta_path)
    with pytest.raises(ImportError, match="broken QC"), _qc_package(pack):
        pytest.fail("broken QC must not be yielded")
    assert {name for name in sys.modules if name.startswith("_xcagi_workbook_qc_")} == before
    assert sys.meta_path == finders


def test_qc_import_does_not_change_trusted_pack_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    pack = _pack(tmp_path / "signed", "one")
    digest = compute_directory_hash(str(pack))
    finders = list(sys.meta_path)
    with _qc_package(pack) as module:
        assert module.run_qc() == "one"
        assert sys.dont_write_bytecode is False
    assert compute_directory_hash(str(pack)) == digest
    assert not list(pack.rglob("*.pyc"))
    assert sys.meta_path == finders


def test_qc_ignores_stale_bytecode_after_same_length_same_mtime_update(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    pack = _pack(tmp_path / "updated", "one")
    source = pack / "backend/vendor/excel_qc/coordinates.py"
    old = source.stat()
    cached = py_compile.compile(str(source), doraise=True)
    source.write_text("VALUE = 'two'\n")
    os.utime(source, ns=(old.st_atime_ns, old.st_mtime_ns))
    assert source.stat().st_size == old.st_size
    digest = compute_directory_hash(str(pack))
    with _qc_package(pack) as module:
        assert module.run_qc() == "two"
    assert compute_directory_hash(str(pack)) == digest
    assert cached is not None and os.path.isfile(cached)
