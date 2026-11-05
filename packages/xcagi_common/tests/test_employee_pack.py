"""Archive compatibility and exported-builder behavior for shared pack builds."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from xcagi_common.employee_pack import build_employee_pack, render_builder_script

REPOSITORY = Path(__file__).resolve().parents[3]
COMMON_PACKAGE = REPOSITORY / "packages" / "xcagi_common"
MODSTORE = REPOSITORY / "成都修茈科技有限公司" / "MODstore_deploy"
BUILDERS = sorted((REPOSITORY / "FHD" / "mods" / "_employees").glob("*/build_xcemp.py"))
BUILDERS += sorted((MODSTORE / "library").glob("*/build_xcemp.py"))
BUILDERS += sorted((MODSTORE / "examples").glob("*/build_xcemp.py"))


def _make_pack(root: Path, pack_id: str = "sample-employee") -> None:
    root.mkdir(parents=True)
    (root / "backend").mkdir()
    (root / "manifest.json").write_text(json.dumps({"id": pack_id, "name": "测试"}))
    (root / "backend" / "blueprints.py").write_text("answer = 42\n")
    (root / "backend" / "template.xlsx").write_bytes(b"spreadsheet template")
    (root / "backend" / "private.json").write_text('{"private": true}')
    (root / "README.md").write_text("Employee source")
    (root / "rule_spec.json").write_text('{"rules": []}')


def test_archive_keeps_layout_and_file_policy_with_repeatable_bytes(tmp_path):
    root = tmp_path / "employee"
    _make_pack(root)
    output = build_employee_pack(root)
    original = output.read_bytes()
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {
            "sample-employee/manifest.json",
            "sample-employee/backend/blueprints.py",
            "sample-employee/backend/template.xlsx",
            "sample-employee/README.md",
        }
        assert (
            json.loads(archive.read("sample-employee/manifest.json"))["name"] == "测试"
        )
        assert (
            archive.read("sample-employee/backend/template.xlsx")
            == b"spreadsheet template"
        )
    for source in root.rglob("*"):
        if source.is_file():
            os.utime(source, (1_700_000_000, 1_700_000_000))
    assert build_employee_pack(root).read_bytes() == original

    output = build_employee_pack(
        root, backend_suffixes=(".py",), extra_files=("rule_spec.json",)
    )
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {
            "sample-employee/manifest.json",
            "sample-employee/backend/blueprints.py",
            "sample-employee/rule_spec.json",
        }


@pytest.mark.parametrize("pack_id", ["../escaped", "x/y", "x\\y", "..", "", "wrong-id"])
def test_invalid_or_mismatched_identity_cannot_write_another_archive(tmp_path, pack_id):
    root = tmp_path / "employee"
    _make_pack(root)
    with pytest.raises(ValueError):
        build_employee_pack(root, pack_id=pack_id)
    assert not list(tmp_path.rglob("*.xcemp"))


def test_build_rejects_source_or_output_symlinks_outside_the_pack(tmp_path):
    root = tmp_path / "employee"
    _make_pack(root)
    outside = tmp_path / "outside.py"
    outside.write_text("private content")
    link = root / "backend" / "outside.py"
    link.symlink_to(outside)
    with pytest.raises(ValueError, match="escapes"):
        build_employee_pack(root)
    link.unlink()
    (root / "sample-employee.xcemp").symlink_to(outside)
    with pytest.raises(ValueError, match="symbolic link"):
        build_employee_pack(root)
    assert outside.read_text() == "private content"


def test_generated_builder_runs_from_an_unrelated_directory(tmp_path):
    root = tmp_path / "employee"
    _make_pack(root)
    script = root / "build_xcemp.py"
    script.write_text(render_builder_script("sample-employee"))
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(COMMON_PACKAGE)},
        text=True,
        capture_output=True,
        check=True,
    )
    assert completed.stdout == ""
    assert (root / "sample-employee.xcemp").is_file()
    with zipfile.ZipFile(root / "sample-employee.xcemp") as archive:
        assert "sample-employee/backend/blueprints.py" in archive.namelist()


@pytest.mark.parametrize("builder", BUILDERS, ids=lambda path: path.parent.name)
def test_all_existing_builders_keep_their_archive_contents(tmp_path, builder):
    root = tmp_path / builder.parent.name
    shutil.copytree(
        builder.parent, root, ignore=shutil.ignore_patterns("*.xcemp", "__pycache__")
    )
    pack_id = root.name
    special = pack_id in {"avatar-generation-employee", "trademark-generation-employee"}
    suffixes = {".py"} if special else {".py", ".xlsx", ".xlsm", ".xls"}
    extras = (
        ("README.md", "rule_spec.json", "asset_manifest.json")
        if special
        else ("README.md",)
    )
    expected = {
        f"{pack_id}/{path.relative_to(root).as_posix()}": path.read_bytes()
        for path in (root / "backend").rglob("*")
        if path.is_file() and path.suffix.lower() in suffixes
    }
    expected.update(
        {
            f"{pack_id}/{name}": (root / name).read_bytes()
            for name in extras
            if (root / name).is_file()
        }
    )
    subprocess.run(
        [sys.executable, str(root / "build_xcemp.py")],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(COMMON_PACKAGE)},
        capture_output=True,
        check=True,
    )
    with zipfile.ZipFile(root / f"{pack_id}.xcemp") as archive:
        assert set(archive.namelist()) == {*expected, f"{pack_id}/manifest.json"}
        for name, content in expected.items():
            assert archive.read(name) == content
        assert json.loads(archive.read(f"{pack_id}/manifest.json")) == json.loads(
            (root / "manifest.json").read_text()
        )
