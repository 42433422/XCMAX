"""materialize_employee_pack_if_missing：目录已登记但 library 未落盘时解压到本地库。"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")


def _minimal_employee_zip_bytes(root_folder: str) -> bytes:
    mf = {
        "id": root_folder,
        "artifact": "employee_pack",
        "version": "1.0.0",
        "name": "Test",
        "description": "t",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            f"{root_folder}/manifest.json",
            json.dumps(mf, ensure_ascii=False),
        )
    return buf.getvalue()


def test_materialize_from_catalog_json(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(tmp_path / "cat"))

    from modstore_server import catalog_store
    from modstore_server.mod_scaffold_runner import materialize_employee_pack_if_missing

    pkg_id = "py-doc-generator"
    fname = f"{pkg_id}-1.0.0.xcemp"
    fd = catalog_store.files_dir()
    fd.mkdir(parents=True, exist_ok=True)
    (fd / fname).write_bytes(_minimal_employee_zip_bytes(pkg_id))

    catalog_store.save_store(
        {
            "packages": [
                {
                    "id": pkg_id,
                    "version": "1.0.0",
                    "name": "Py Doc",
                    "artifact": "employee_pack",
                    "stored_filename": fname,
                }
            ]
        }
    )

    lib = tmp_path / "lib"
    lib.mkdir(parents=True, exist_ok=True)

    def fake_lib() -> Path:
        return lib

    monkeypatch.setattr(
        "modstore_server.mod_scaffold_runner.modstore_library_path",
        fake_lib,
    )

    ok = materialize_employee_pack_if_missing(pkg_id)
    assert ok is True
    mf = lib / pkg_id / "manifest.json"
    assert mf.is_file()
    data = json.loads(mf.read_text(encoding="utf-8"))
    assert data.get("id") == pkg_id


def test_materialize_skips_when_manifest_already_present(monkeypatch, tmp_path: Path):
    from modstore_server.mod_scaffold_runner import materialize_employee_pack_if_missing

    pkg_id = "already-there"
    lib = tmp_path / "lib"
    pack_dir = lib / pkg_id
    pack_dir.mkdir(parents=True)
    (pack_dir / "manifest.json").write_text('{"id":"already-there"}', encoding="utf-8")

    def fake_lib() -> Path:
        return lib

    monkeypatch.setattr(
        "modstore_server.mod_scaffold_runner.modstore_library_path",
        fake_lib,
    )

    assert materialize_employee_pack_if_missing(pkg_id) is True
