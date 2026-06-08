"""deploy_to_xcagi / pull_from_xcagi：employee_pack → mods/_employees，pull 含 _employees。"""

from __future__ import annotations

import json
from pathlib import Path

from modman.store import deploy_to_xcagi, pull_from_xcagi


def _write_mod_manifest(d: Path, mid: str, *, artifact: str = "mod") -> None:
    d.mkdir(parents=True, exist_ok=True)
    mf: dict = {
        "id": mid,
        "name": mid,
        "version": "1.0.0",
        "artifact": artifact,
        "scope": "global",
        "dependencies": {"xcagi": ">=1.0.0"},
        "employee": {"id": "e1", "label": "E"},
        "employee_config_v2": {},
    }
    if artifact == "mod":
        mf["backend"] = {"entry": "blueprints", "init": "mod_init"}
        mf["frontend"] = {"routes": "src/routes.ts"}
    (d / "manifest.json").write_text(json.dumps(mf, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "backend").mkdir(exist_ok=True)
    (d / "backend" / "__init__.py").write_text("", encoding="utf-8")


def test_deploy_employee_pack_goes_under_employees(tmp_path: Path) -> None:
    lib = tmp_path / "library"
    xc = tmp_path / "xcagi"
    mod_dir = lib / "my-mod"
    emp_dir = lib / "emp-pack"
    _write_mod_manifest(mod_dir, "my-mod", artifact="mod")
    _write_mod_manifest(emp_dir, "emp-pack", artifact="employee_pack")

    done = deploy_to_xcagi(None, lib, xc, replace=True)
    assert set(done) == {"my-mod", "emp-pack"}

    assert (xc / "mods" / "my-mod" / "manifest.json").is_file()
    assert (xc / "mods" / "_employees" / "emp-pack" / "manifest.json").is_file()
    data = json.loads(
        (xc / "mods" / "_employees" / "emp-pack" / "manifest.json").read_text(encoding="utf-8")
    )
    assert data.get("artifact") == "employee_pack"


def test_pull_includes_employees_dir(tmp_path: Path) -> None:
    lib = tmp_path / "library"
    xc = tmp_path / "xcagi"
    mods = xc / "mods"
    emps = mods / "_employees"
    mods.mkdir(parents=True)
    emps.mkdir(parents=True)
    _write_mod_manifest(mods / "m1", "m1", artifact="mod")
    _write_mod_manifest(emps / "e1", "e1", artifact="employee_pack")

    done = pull_from_xcagi(None, lib, xc, replace=True)
    assert set(done) == {"m1", "e1"}
    assert (lib / "m1" / "manifest.json").is_file()
    assert (lib / "e1" / "manifest.json").is_file()
    pulled = json.loads((lib / "e1" / "manifest.json").read_text(encoding="utf-8"))
    assert pulled.get("artifact") == "employee_pack"


def test_employee_pack_http_path_contract() -> None:
    """FHD employee_pack 由 blueprints 挂载的路径（与 Mod 内 workflow stub ``/emp/`` 不同）。"""
    pack_id = "my-pack"
    emp_id = "staff_a"
    assert f"/api/mod/{pack_id}/employees/{emp_id}/run" == "/api/mod/my-pack/employees/staff_a/run"


def test_pull_mod_ids_filters_employees(tmp_path: Path) -> None:
    lib = tmp_path / "library"
    xc = tmp_path / "xcagi"
    (xc / "mods").mkdir(parents=True)
    _write_mod_manifest(xc / "mods" / "_employees" / "only", "only", artifact="employee_pack")

    done = pull_from_xcagi(["only"], lib, xc, replace=True)
    assert done == ["only"]
