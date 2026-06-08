"""modman.employee_sandbox 静态与 zip 门禁逻辑。"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from modman.employee_sandbox import (
    assert_employee_sandbox_passes_for_catalog_zip,
    extract_mod_root_from_zip,
    run_static_employee_sandbox,
)


def test_extract_flat_manifest(tmp_path: Path):
    zpath = tmp_path / "m.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "id": "flat-mod",
                    "name": "F",
                    "version": "1.0.0",
                    "backend": {"entry": "blueprints", "init": "mod_init"},
                    "frontend": {"routes": "routes"},
                },
                ensure_ascii=False,
            ),
        )
        zf.writestr("backend/blueprints.py", "x")
    work = tmp_path / "out"
    root = extract_mod_root_from_zip(zpath, work)
    assert (root / "manifest.json").is_file()


def test_static_skips_without_workflow_employees(tmp_path: Path):
    d = tmp_path / "m"
    d.mkdir()
    (d / "manifest.json").write_text(
        json.dumps(
            {
                "id": "m",
                "name": "M",
                "version": "1.0.0",
                "backend": {"entry": "blueprints", "init": "mod_init"},
                "frontend": {"routes": "routes"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    r = run_static_employee_sandbox(d)
    assert r["ok"] is True
    assert r.get("skipped") is True


def test_static_requires_stub_and_mount(tmp_path: Path):
    d = tmp_path / "m2"
    (d / "backend").mkdir(parents=True)
    (d / "backend" / "employee_stubs").mkdir(parents=True)
    (d / "backend" / "employee_stubs" / "__init__.py").write_text("", encoding="utf-8")
    (d / "backend" / "employee_stubs" / "e_h1.py").write_text("# stub", encoding="utf-8")
    (d / "backend" / "blueprints.py").write_text(
        "def register_fastapi_routes(app, mod_id):\n    from .employee_stubs import e_h1 as _emp_stub_e_h1\n    _emp_stub_e_h1.mount_employee_router(app, mod_id)\n",
        encoding="utf-8",
    )
    (d / "manifest.json").write_text(
        json.dumps(
            {
                "id": "m2",
                "name": "M",
                "version": "1.0.0",
                "backend": {"entry": "blueprints", "init": "mod_init"},
                "frontend": {"routes": "routes"},
                "workflow_employees": [{"id": "h1", "label": "H"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    r = run_static_employee_sandbox(d)
    assert r["ok"] is True
    assert not r.get("skipped")


def test_assert_catalog_zip_raises_without_stub(tmp_path: Path):
    zpath = tmp_path / "bad.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "id": "bad",
                    "name": "B",
                    "version": "1.0.0",
                    "artifact": "mod",
                    "backend": {"entry": "blueprints", "init": "mod_init"},
                    "frontend": {"routes": "routes"},
                    "workflow_employees": [{"id": "h1", "label": "H"}],
                },
                ensure_ascii=False,
            ),
        )
        zf.writestr("backend/blueprints.py", "e_h1\n")
    with pytest.raises(ValueError, match="员工沙箱未通过"):
        assert_employee_sandbox_passes_for_catalog_zip(zpath, probe_http=False, backend_base=None)
