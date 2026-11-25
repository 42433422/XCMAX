"""Run the native restore guard and SQLite replacement against isolated data.

Only PostgreSQL, systemd and ownership commands are replaced. The script's Bash,
flock, role validation, archive hashing, gzip, file moves and receipt writes run.
"""

from __future__ import annotations

import fcntl
import gzip
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "xcmax_dr_restore_latest.sh"


class RestoreRoleGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.state.mkdir(mode=0o700)
        self.role = self.root / "runtime-role.env"
        self.write_role("standby")
        self.lock = self.root / "release.lock"
        self.events = self.root / "events"
        self.events.touch()
        self.marker = self.state / "last_restored_snapshot"
        self.marker.write_text("previous-snapshot\n")
        self.success = self.state / "last_restore_success"
        self.success.write_text("previous-success\n")
        self.database = self.root / "runtime-data/modstore/modstore.db"
        self.database.parent.mkdir(parents=True)
        self.make_database(self.database, "customer-committed-after-promotion")
        self.original_database = self.database.read_bytes()
        self.archive = self.root / "archive"
        self.snapshot = self.archive / "20261123-001"
        self.snapshot.mkdir(parents=True)
        (self.archive / "latest").symlink_to(self.snapshot, target_is_directory=True)
        archived_db = self.root / "archived.db"
        self.make_database(archived_db, "old-backup-customer")
        (self.snapshot / "modstore_sqlite.db.gz").write_bytes(
            gzip.compress(archived_db.read_bytes())
        )
        for name in ("fhd_pg.dump", "modstore_pg.dump", "payment_pg.dump"):
            (self.snapshot / name).write_text("host PostgreSQL test boundary\n")
        (self.snapshot / "MANIFEST.txt").write_text(
            "".join(
                f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
                for path in sorted(self.snapshot.iterdir())
            )
        )
        self.bin = self.root / "bin"
        self.bin.mkdir()
        host_command = """#!/usr/bin/env python3
import os
from pathlib import Path
import sys

name, args = Path(sys.argv[0]).name, sys.argv[1:]
with Path(os.environ["HOST_EVENTS"]).open("a") as stream:
    stream.write(name + " " + " ".join(args) + "\\n")
if name == "docker":
    if args[:2] == ["inspect", "-f"]:
        print("true")
    elif args and args[0] == "exec":
        if "-i" in args:
            sys.stdin.buffer.read()
        if any("select count(*)" in value for value in args):
            print("1")
"""
        for name in ("docker", "systemctl", "pg_restore", "chown"):
            executable = self.bin / name
            executable.write_text(host_command)
            executable.chmod(0o755)

    def write_role(self, role: str) -> None:
        self.role.write_text(f"XCMAX_DR_SAVED_RUNTIME_MODE={role}\n")
        self.role.chmod(0o600)

    @staticmethod
    def make_database(path: Path, value: str) -> None:
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE receipts (customer TEXT NOT NULL)")
            db.execute("INSERT INTO receipts VALUES (?)", (value,))

    def run_restore(self) -> subprocess.CompletedProcess[str]:
        source = SCRIPT.read_text()
        # Execute the same guard and restore body without the root-only CLI
        # setup, so this regression also runs on an unprivileged CI runner.
        definitions = source[: source.index('[[ "${EUID}" == "0" ]]')]
        body = source[source.index("log() {") :]
        command = (
            definitions
            + "\nacquire_restore_runtime_lock\nrequire_standby_restore\n"
            + body
        )
        environment = {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "DR_ROOT": str(self.root),
            "ARCHIVE": str(self.archive),
            "STATE": str(self.state),
            "ROLE_ENV": str(self.role),
            "RUNTIME_LOCK": str(self.lock),
            "LOG": str(self.root / "restore.log"),
            "PG_CONTAINER": "isolated-test-postgres",
            "FORCE": "1",
            "HOST_EVENTS": str(self.events),
        }
        return subprocess.run(
            ["bash", "-c", command],
            env=environment,
            text=True,
            capture_output=True,
            timeout=10,
        )

    def assert_blocked_without_mutation(self) -> None:
        result = self.run_restore()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.database.read_bytes(), self.original_database)
        self.assertEqual(self.marker.read_text(), "previous-snapshot\n")
        self.assertEqual(self.success.read_text(), "previous-success\n")
        self.assertEqual(self.events.read_text(), "")

    def test_cli_checks_role_under_lock_before_snapshot_or_host_mutations(self) -> None:
        text = SCRIPT.read_text()
        gate = text.index("acquire_restore_runtime_lock\nrequire_standby_restore\n")
        self.assertLess(gate, text.index('mkdir -p "$STATE"'))
        self.assertLess(gate, text.index('latest="$(readlink'))

    def test_promoted_role_cannot_overwrite_business_data_even_with_force(self) -> None:
        self.write_role("promoted")
        self.assert_blocked_without_mutation()

    def test_promoted_receipt_blocks_even_if_role_file_still_says_standby(self) -> None:
        (self.state / "promoted_at").write_text("1795435200\n")
        self.assert_blocked_without_mutation()

    def test_serving_peer_cannot_restore_old_local_business_data(self) -> None:
        self.write_role("active-peer")
        self.assert_blocked_without_mutation()

    def test_unknown_missing_duplicate_and_insecure_roles_fail_closed(self) -> None:
        for case in ("unknown", "missing", "duplicate", "insecure", "symlink"):
            with self.subTest(case=case):
                self.role.unlink(missing_ok=True)
                self.write_role("standby")
                if case == "unknown":
                    self.write_role("unexpected")
                elif case == "missing":
                    self.role.unlink()
                elif case == "duplicate":
                    self.role.write_text(
                        "XCMAX_DR_SAVED_RUNTIME_MODE=promoted\n"
                        "XCMAX_DR_SAVED_RUNTIME_MODE=standby\n"
                    )
                elif case == "insecure":
                    self.role.chmod(0o644)
                else:
                    original = self.root / "private-role.env"
                    self.role.rename(original)
                    self.role.symlink_to(original)
                self.assert_blocked_without_mutation()

    def test_uncertain_component_activation_blocks_restore(self) -> None:
        for component in ("modstore", "fhd"):
            with self.subTest(component=component):
                pending = self.state / f"release_apply_{component}.pending"
                pending.mkdir()
                self.assert_blocked_without_mutation()
                pending.rmdir()

    def test_release_or_promotion_lock_prevents_any_restore_mutation(self) -> None:
        with self.lock.open("w") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assert_blocked_without_mutation()

    def test_explicit_standby_retains_native_sqlite_restore_and_receipts(self) -> None:
        result = self.run_restore()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("PRAGMA quick_check").fetchall(), [("ok",)])
            self.assertEqual(
                db.execute("SELECT customer FROM receipts").fetchall(),
                [("old-backup-customer",)],
            )
        self.assertEqual(self.marker.read_text(), self.snapshot.name + "\n")
        self.assertTrue(self.success.read_text().strip().isdigit())
        self.assertIn(
            "systemctl stop xcmax-dr-modstore.service", self.events.read_text()
        )
        self.assertIn(
            "systemctl start xcmax-dr-modstore.service", self.events.read_text()
        )


if __name__ == "__main__":
    unittest.main()
