"""Execute the production shell scripts with deterministic CLI failure fixtures."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "deploy"


@pytest.fixture
def commands(tmp_path):
    binary = tmp_path / "bin"
    binary.mkdir()
    runner = binary / "docker"
    runner.write_text(f"#!{sys.executable}\n" + r'''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['CLI_LOG'], 'a') as log:
    log.write(json.dumps([Path(sys.argv[0]).name, *args]) + '\n')
if Path(sys.argv[0]).name == 'coscmd':
    if 'list' in args:
        print('manifests/20261121-000000.json')
    else:
        Path(args[-1]).write_text(json.dumps({'modstore': {'dump':'present', 'row_counts':{'tickets':10}}}) if args[-1].endswith('.json') else 'fixture dump')
elif 'pg_restore' in args:
    sys.stdin.buffer.read()
    if '--list' not in args and os.environ.get('FAIL_OPERATION') == 'restore':
        print('fixture constraint restore failure', file=sys.stderr)
        sys.exit(3)
else:
    sql = args[-1]
    failure = os.environ.get('FAIL_OPERATION')
    if ((sql.startswith('DROP') and failure == 'cleanup')
        or (sql.startswith('WITH d') and ' tickets ' in sql and failure == 'delete')
        or (sql.startswith('SELECT count(*) FROM tickets WHERE') and failure == 'count')):
        print('fixture SQL command failure', file=sys.stderr)
        sys.exit(3)
    if sql == 'SELECT 1': print(1)
    elif sql.startswith(('SELECT to_regclass', 'SELECT EXISTS')): print('t')
    elif sql.startswith('WITH d'): print(0)
    elif 'information_schema.tables' in sql: print(1)
    elif sql.startswith('SELECT count(*)'): print(10)
''')
    runner.chmod(0o700)
    (binary / "coscmd").symlink_to(runner)
    config = tmp_path / "retention.conf"
    config.write_text("tickets|created_at|30|100\nother_events|created_at|30|100\n")
    return {
        **os.environ, "PATH": str(binary) + os.pathsep + os.environ["PATH"],
        "FHD_MODSTORE_PG_CONTAINER": "fixture-postgres", "CLI_LOG": str(tmp_path / "calls.jsonl"),
        "FHD_PG_RETENTION_CONF": str(config), "FHD_PG_RETENTION_LOG": str(tmp_path / "retention.log"),
    }


def execute(name, env, *args):
    return subprocess.run(["bash", str(SCRIPTS / name), *args], env=env, capture_output=True, text=True, timeout=20)


def calls(env):
    return [json.loads(line) for line in Path(env["CLI_LOG"]).read_text().splitlines()]


def test_restore_command_failure_cannot_be_hidden_by_valid_row_counts(commands):
    result = execute("fhd-restore-drill.sh", {**commands, "FAIL_OPERATION": "restore"})
    assert result.returncode != 0
    assert "constraint restore failure" in result.stderr
    assert "恢复演练完成" not in result.stdout
    invocations = calls(commands)
    assert any("DROP DATABASE" in row[-1] for row in invocations)
    assert not any("SELECT count(*)" in row[-1] for row in invocations)
    restore = next(row for row in invocations if "pg_restore" in row and "--list" not in row)
    assert "--exit-on-error" in restore and "--single-transaction" in restore


@pytest.mark.parametrize("failure,success", [("", True), ("cleanup", False)])
def test_successful_restore_requires_cleanup(commands, failure, success):
    result = execute("fhd-restore-drill.sh", {**commands, "FAIL_OPERATION": failure})
    assert (result.returncode == 0) is success, result.stderr
    assert any("SELECT count(*) FROM tickets" in row[-1] for row in calls(commands))


@pytest.mark.parametrize("failure,args", [("delete", ()), ("count", ("--dry-run",))])
def test_retention_sql_failure_is_not_zero_rows_and_other_tables_continue(commands, failure, args):
    result = execute("fhd-pg-retention.sh", {**commands, "FAIL_OPERATION": failure}, *args)
    assert result.returncode != 0
    assert "行级保留失败" in result.stdout
    assert "行级保留完成" not in result.stdout
    assert any("other_events" in row[-1] for row in calls(commands))


def test_retention_genuine_zero_rows_is_success(commands):
    result = execute("fhd-pg-retention.sh", commands)
    assert result.returncode == 0, result.stderr
    assert "删除 0 行" in result.stdout
