"""Release updates and promotion must not import an older backup into live data."""

from __future__ import annotations

import gzip
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "xcmax_dr_prepare_runtime.sh"


class RuntimeDataPreservationTest(unittest.TestCase):
    def test_release_update_and_promotion_keep_newer_database_and_file_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "runtime-data"
            (data / "modstore").mkdir(parents=True)
            (data / "fhd/mods").mkdir(parents=True)
            live = data / "modstore/modstore.db"
            with sqlite3.connect(live) as db:
                db.execute("CREATE TABLE accepted_work (id TEXT PRIMARY KEY)")
                db.execute("INSERT INTO accepted_work VALUES ('after-backup')")
            active_mod = data / "fhd/mods/work.txt"
            active_mod.write_text("newer active state")
            restore = root / "restore-config"
            (restore / "opt/fhd-full/mods").mkdir(parents=True)
            (restore / "opt/fhd-full/mods/work.txt").write_text("old snapshot")
            archive = root / "archive"
            archive.mkdir()
            snapshot = archive / "snapshot"
            snapshot.mkdir()
            (archive / "latest").symlink_to(snapshot)
            (snapshot / "modstore_sqlite.db.gz").write_bytes(
                gzip.compress(b"older snapshot")
            )
            for flag in ("--release-update", "--preserve-data"):
                with self.subTest(flag=flag):
                    result = subprocess.run(
                        [
                            "bash",
                            "-c",
                            r"""
set -euo pipefail
eval "$(sed -n '/^RELEASE_UPDATE=0/,/^esac/p' "$SCRIPT")"
for fn in sync_tree restore_runtime_data; do
  eval "$(sed -n "/^$fn() {/,/^}/p" "$SCRIPT")"
done
restore_runtime_data
""",
                            "prepare-runtime-test",
                            flag,
                        ],
                        text=True,
                        capture_output=True,
                        timeout=10,
                        env={
                            **os.environ,
                            "SCRIPT": str(SCRIPT),
                            "DATA": str(data),
                            "DR_ROOT": str(root),
                            "RESTORE_CONFIG": str(restore),
                        },
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    with sqlite3.connect(live) as db:
                        self.assertEqual(
                            db.execute("SELECT * FROM accepted_work").fetchall(),
                            [("after-backup",)],
                        )
                    self.assertEqual(active_mod.read_text(), "newer active state")


if __name__ == "__main__":
    unittest.main()
