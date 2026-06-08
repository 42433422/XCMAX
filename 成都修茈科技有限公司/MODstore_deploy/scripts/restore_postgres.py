#!/usr/bin/env python3
"""Restore a PostgreSQL custom dump into the MODstore compose database."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore MODstore PostgreSQL from backup.")
    parser.add_argument("dump", help="Path to postgres.dump produced by scripts/backup_modstore.py")
    parser.add_argument("--confirm", action="store_true", help="Required to execute the restore")
    parser.add_argument("--clean", action="store_true", help="Pass --clean --if-exists to pg_restore")
    args = parser.parse_args()

    dump = Path(args.dump).resolve()
    if not dump.is_file():
        raise SystemExit(f"Dump not found: {dump}")
    if not args.confirm:
        print("Dry run only. Re-run with --confirm after verifying the target database.")
        print(f"Would restore {dump} into compose service postgres.")
        return 0

    db = os.environ.get("POSTGRES_DB", "modstore")
    user = os.environ.get("POSTGRES_USER", "modstore")
    command = ["docker", "compose", "exec", "-T", "postgres", "pg_restore", "-U", user, "-d", db]
    if args.clean:
        command.extend(["--clean", "--if-exists"])

    with dump.open("rb") as handle:
        proc = subprocess.run(command, cwd=ROOT, stdin=handle)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
