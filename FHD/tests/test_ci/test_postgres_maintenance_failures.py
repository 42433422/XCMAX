"""Execute maintenance scripts with failed PostgreSQL commands, without production I/O."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "scripts" / "deploy"


@pytest.fixture
def environment(tmp_path):
    scripts = {
        "coscmd": """
case " $* " in
  *" list "*) echo 20261122-010000.json ;;
  *manifest.json*) cp "$FIXTURE_DIR/manifest.json" "${@: -1}" ;;
  *) touch "${@: -1}" ;;
esac
""",
        "docker": """
echo "$*" >> "$FIXTURE_DIR/commands"
case " $* " in
  *"pg_restore --list"*) cat >/dev/null; exit 0 ;;
  *pg_restore*) cat >/dev/null; stage=restore ;;
  *"DROP DATABASE"*) stage=cleanup ;;
  *"CREATE DATABASE"*) stage=create ;;
  *to_regclass*) stage=table; answer=t ;;
  *information_schema.columns*) stage=column; answer=t ;;
  *information_schema.tables*) stage=restored_tables; answer=1 ;;
  *"SELECT 1"*) stage=connect; answer=1 ;;
  *"WITH d AS"*) stage=delete; answer=0 ;;
  *"SELECT count(*)"*) stage=count; answer=2 ;;
  *) exit 99 ;;
esac
if [[ "$FAIL_STAGE" == "$stage" ]]; then echo "injected PostgreSQL failure" >&2; exit 23; fi
if [[ "$FAIL_STAGE" == "invalid-$stage" ]]; then echo invalid; exit 0; fi
if [[ -n "${answer:-}" ]]; then echo "$answer"; fi
""",
    }
    for name, body in scripts.items():
        target = tmp_path / name
        target.write_text("#!/bin/bash\nset -eu\n" + body)
        target.chmod(0o700)
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "modstore": {
                    "dump": "backup.dump",
                    "sha256": hashlib.sha256(b"").hexdigest(),
                    "row_counts": {"events": 2},
                    "row_count_evidence": {
                        "status": "verified",
                        "method": "pg_export_snapshot_count_v1",
                        "snapshot_id": "test-snapshot",
                        "schema": "public",
                        "missing_tables": [],
                        "requested_tables": ["events"],
                    },
                }
            }
        )
    )
    (tmp_path / "retention.conf").write_text("events|created_at|30|100\n")
    return {
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "LANG": "C.UTF-8",
        "FIXTURE_DIR": str(tmp_path),
        "FHD_MODSTORE_PG_CONTAINER": "test-postgres",
        "FHD_PG_RETENTION_CONF": str(tmp_path / "retention.conf"),
        "FHD_PG_RETENTION_LOG": str(tmp_path / "retention.log"),
        "FAIL_STAGE": "",
    }


def execute(script, environment, *args):
    return subprocess.run(
        ["bash", str(DEPLOY / script), *args],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )


@pytest.mark.parametrize("stage", ["restore", "restored_tables", "count", "invalid-count", ""])
def test_restore_requires_successful_restore_and_valid_counts(environment, stage):
    environment["FAIL_STAGE"] = stage
    result = execute("fhd-restore-drill.sh", environment)
    assert (result.returncode == 0) is (not stage), result.stdout + result.stderr
    assert ("恢复演练完成" in result.stdout) is (not stage)
    trace = Path(environment["FIXTURE_DIR"], "commands").read_text()
    assert "DROP DATABASE" in trace
    if stage == "restore":
        assert "information_schema.tables" not in trace


@pytest.mark.parametrize(
    "stage,dry",
    [
        ("delete", False),
        ("invalid-delete", False),
        ("count", True),
        ("invalid-count", True),
        ("table", False),
        ("column", False),
        ("", False),
    ],
)
def test_retention_does_not_report_failed_queries_as_zero_rows(environment, stage, dry):
    environment["FAIL_STAGE"] = stage
    result = execute("fhd-pg-retention.sh", environment, *(["--dry-run"] if dry else []))
    assert (result.returncode == 0) is (not stage), result.stdout + result.stderr
    assert ("行级保留完成" in result.stdout) is (not stage)
    if stage:
        assert "行级保留失败" in result.stdout
