from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from modman.db_bundle import collect_sources_from_dir, copy_databases_into_mod


def test_copy_db_into_mod_with_wal(tmp_path: Path) -> None:
    mod = tmp_path / "demo_mod"
    mod.mkdir()
    (mod / "manifest.json").write_text(
        json.dumps(
            {
                "id": "demo_mod",
                "name": "Demo",
                "version": "0.0.1",
                "backend": {"entry": "blueprints", "init": "mod_init"},
                "frontend": {"routes": "frontend/routes"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    src_dir = tmp_path / "srcdb"
    src_dir.mkdir()
    db = src_dir / "app.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE t (x INT)")
    conn.commit()
    conn.close()
    # WAL may or may not appear until first write; create empty wal for test
    (src_dir / "app.db-wal").write_bytes(b"")

    out = copy_databases_into_mod(mod, [db], dest_subdir="data", dry_run=False)
    assert any(x.endswith("data/app.db") for x in out)
    assert (mod / "data" / "app.db").is_file()
    assert (mod / "data" / "MODMAN_DATABASE_README.txt").is_file()


def test_collect_sources_from_dir(tmp_path: Path) -> None:
    d = tmp_path / "d"
    d.mkdir()
    (d / "a.db").write_text("x")
    (d / "b.txt").write_text("y")
    got = collect_sources_from_dir(d, "*.db")
    assert len(got) == 1 and got[0].name == "a.db"


def test_dry_run_no_files_created(tmp_path: Path) -> None:
    mod = tmp_path / "m2"
    mod.mkdir()
    (mod / "manifest.json").write_text(
        '{"id":"m2","name":"M","version":"1","backend":{"entry":"b","init":"i"},"frontend":{"routes":"r"}}',
        encoding="utf-8",
    )
    f = tmp_path / "x.db"
    sqlite3.connect(str(f)).close()
    copy_databases_into_mod(mod, [f], dry_run=True)
    assert not (mod / "data").exists()
