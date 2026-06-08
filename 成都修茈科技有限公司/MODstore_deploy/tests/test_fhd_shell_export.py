from __future__ import annotations

import json
from pathlib import Path

from modman.fhd_shell_export import build_fhd_shell_mod_rows, write_fhd_shell_mods_json


def _write_mod(lib: Path, mid: str, name: str, **extra) -> None:
    d = lib / mid
    d.mkdir(parents=True)
    manifest = {
        "id": mid,
        "name": name,
        "version": "1.0.0",
        "author": "t",
        "description": "d",
        "primary": False,
        **extra,
    }
    (d / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def test_build_rows_inserts_all_and_sorts(tmp_path: Path) -> None:
    _write_mod(tmp_path, "zebra", "Z")
    _write_mod(tmp_path, "alpha", "A")
    rows = build_fhd_shell_mod_rows(tmp_path)
    assert rows[0] == {
        "id": "all",
        "name": "全部",
        "type": "category",
        "color": None,
    }
    ids = [r["id"] for r in rows[1:]]
    assert ids == ["alpha", "zebra"]
    assert rows[1]["type"] == "template" and rows[1]["color"] == "green"


def test_fhd_shell_overlay(tmp_path: Path) -> None:
    _write_mod(
        tmp_path,
        "m1",
        "Base",
        fhd_shell={"color": "blue", "type": "template", "description": "X", "name": "Shown"},
    )
    rows = build_fhd_shell_mod_rows(tmp_path)
    m1 = next(r for r in rows if r["id"] == "m1")
    assert m1["name"] == "Shown"
    assert m1["color"] == "blue"
    assert m1["description"] == "X"


def test_write_roundtrip(tmp_path: Path) -> None:
    _write_mod(tmp_path, "x", "Xmod")
    out = tmp_path / "out.json"
    n = write_fhd_shell_mods_json(tmp_path, out)
    assert n == 2
    data = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(data, list) and data[0]["id"] == "all"


def test_database_seed_sql_resolves_relative_to_mod(tmp_path: Path) -> None:
    _write_mod(tmp_path, "seedmod", "S", database_seed_sql="data/s.sql")
    d = tmp_path / "seedmod"
    seed = d / "data" / "s.sql"
    seed.parent.mkdir(parents=True, exist_ok=True)
    seed.write_text("SELECT 1;", encoding="utf-8")
    rows = build_fhd_shell_mod_rows(tmp_path)
    row = next(r for r in rows if r["id"] == "seedmod")
    assert row.get("database_seed_sql") == str(seed.resolve())
