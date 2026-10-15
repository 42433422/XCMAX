import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "lifecycle_fixtures",
    Path(__file__).parents[2] / "scripts/package/windows-lifecycle-fixtures.py",
)
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


def test_nonempty_owned_state_and_real_long_path_detect_corruption(tmp_path):
    root, evidence = tmp_path / "data", tmp_path / "evidence"
    root.mkdir()
    evidence.mkdir()
    fixtures.run("seed", root, evidence)
    fixtures.run("verify", root, evidence)
    entries = json.loads((evidence / "owned-fixtures.json").read_text())
    assert len(entries) == 4 and all(e["bytes"] > 0 for e in entries)
    assert max(len(str(root / e["path"])) for e in entries) == 261
    with sqlite3.connect(root / "data/xcagi.db") as db:
        db.execute("CREATE TABLE business(value TEXT)")
        db.execute("INSERT INTO business VALUES ('preserved')")
    fixtures.run("dirty", root, evidence)
    with pytest.raises(AssertionError, match="Owned-state mismatch"):
        fixtures.run("verify", root, evidence)
    with sqlite3.connect(root / "data/xcagi.db") as db:
        assert db.execute("SELECT * FROM business").fetchall() == [("preserved",)]
        assert db.execute("SELECT * FROM lifecycle_failure_probe").fetchall() == [
            ("controlled-failure",)
        ]
    assert not list(root.glob("rollback*"))


def test_original_app_manifest_rejects_changed_or_extra_files(tmp_path):
    root, evidence = tmp_path / "app", tmp_path / "evidence"
    root.mkdir()
    evidence.mkdir()
    (root / "app.exe").write_bytes(b"original")
    fixtures.run("app-seed", root, evidence)
    fixtures.run("app-verify", root, evidence)
    (root / "extra").write_bytes(b"extra")
    with pytest.raises(AssertionError):
        fixtures.run("app-verify", root, evidence)
    (root / "extra").unlink()
    (root / "app.exe").write_bytes(b"changed")
    with pytest.raises(AssertionError):
        fixtures.run("app-verify", root, evidence)
