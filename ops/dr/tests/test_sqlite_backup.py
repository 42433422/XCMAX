"""Run the existing backup entrypoints against a live WAL database."""

from __future__ import annotations

import gzip
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "backup" / "xcmax_backup.sh"


class SqliteBackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dest = self.root / "backups"
        self.dest.mkdir()
        self.db = self.root / "source #?%.db"
        self.connection = sqlite3.connect(self.db)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA wal_autocheckpoint=0")
        self.connection.execute(
            "CREATE TABLE receipts (id TEXT PRIMARY KEY, status TEXT)"
        )
        self.connection.commit()
        self.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.connection.execute(
            "INSERT INTO receipts VALUES ('original-task', 'committed')"
        )
        self.connection.commit()
        self.env_file = self.root / "service.env"
        self.fhd_db = self.root / "fhd source #%.db"
        self.fhd_db.symlink_to(self.db)
        self.env_file.write_text(f"DATABASE_URL=sqlite:///{self.fhd_db}\n")

    def tearDown(self):
        self.connection.close()
        self.tmp.cleanup()

    def backup(self, component):
        env = {
            **os.environ,
            "SCRIPT": str(SCRIPT),
            "DEST": str(self.dest),
            "FHD_ENV": str(self.env_file),
            "FHD_DIR": str(self.root),
            "MODSTORE_DB": str(self.db),
            "MODSTORE_DIR": str(self.root),
            "LOG": str(self.root / "backup.log"),
            "COMPONENT": component,
        }
        return subprocess.run(
            [
                "bash",
                "-c",
                r"""set -uo pipefail
DRY_RUN=0; FAILURES=()
log() { :; }
fail() { FAILURES+=("$1"); }
for fn in extract_database_url backup_sqlite backup_fhd_pg backup_modstore_sqlite; do
  eval "$(sed -n "/^$fn() {/,/^}/p" "$SCRIPT")"
done
if [[ "$COMPONENT" == fhd ]]; then backup_fhd_pg; else backup_modstore_sqlite; fi
[[ ${#FAILURES[@]} == 0 ]]
""",
            ],
            env=env,
            text=True,
            capture_output=True,
            timeout=20,
        )

    def test_both_backups_restore_committed_wal_rows(self):
        for component in ("fhd", "modstore"):
            with self.subTest(component=component):
                result = self.backup(component)
                self.assertEqual(result.returncode, 0, result.stderr)
                output = self.dest / f"{component}_sqlite.db.gz"
                restored = self.root / f"restored-{component}.db"
                restored.write_bytes(gzip.decompress(output.read_bytes()))
                with sqlite3.connect(restored) as db:
                    self.assertEqual(
                        db.execute("PRAGMA quick_check").fetchall(), [("ok",)]
                    )
                    self.assertEqual(
                        db.execute("SELECT * FROM receipts").fetchall(),
                        [("original-task", "committed")],
                    )

    def test_missing_source_cannot_report_success_or_replace_prior_backup(self):
        self.env_file.write_text(f"DATABASE_URL=sqlite:///{self.root / 'missing.db'}\n")
        original = self.dest / "fhd_sqlite.db.gz"
        original.write_bytes(b"previous verified archive")
        self.assertNotEqual(self.backup("fhd").returncode, 0)
        self.assertEqual(original.read_bytes(), b"previous verified archive")
        self.assertFalse((self.root / "missing.db").exists())

    def test_relative_pysqlite_url_uses_service_directory_and_preserves_wal(self):
        self.env_file.write_text(
            f"DATABASE_URL=sqlite+pysqlite:///./{self.fhd_db.name}?timeout=10\n"
        )
        result = self.backup("fhd")
        self.assertEqual(result.returncode, 0, result.stderr)
        restored = self.root / "relative-restored.db"
        restored.write_bytes(
            gzip.decompress((self.dest / "fhd_sqlite.db.gz").read_bytes())
        )
        with sqlite3.connect(restored) as db:
            self.assertEqual(
                db.execute("SELECT * FROM receipts").fetchall(),
                [("original-task", "committed")],
            )

    def test_corrupt_source_cannot_replace_prior_backup(self):
        broken = self.root / "broken.db"
        broken.write_bytes(b"not a database")
        self.env_file.write_text(f"DATABASE_URL=sqlite:///{broken}\n")
        original = self.dest / "fhd_sqlite.db.gz"
        original.write_bytes(b"previous verified archive")
        self.assertNotEqual(self.backup("fhd").returncode, 0)
        self.assertEqual(original.read_bytes(), b"previous verified archive")
        self.assertEqual(sorted(p.name for p in self.dest.iterdir()), [original.name])


if __name__ == "__main__":
    unittest.main()
