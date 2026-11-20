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
    runner.write_text(
        f"#!{sys.executable}\n"
        + r"""
import hashlib, json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['CLI_LOG'], 'a') as log:
    log.write(json.dumps([Path(sys.argv[0]).name, *args]) + '\n')
if Path(sys.argv[0]).name == 'coscmd':
    if 'list' in args:
        print('manifests/20261121-000000.json')
    else:
        data = {'dump': 'present', 'sha256': hashlib.sha256(b'fixture dump').hexdigest(),
                'row_counts': {'tickets': int(os.environ.get('EXPECTED_ROWS', '10'))},
                'row_count_evidence': {'status': 'verified', 'method': 'pg_export_snapshot_count_v1',
                    'snapshot_id': '00000003-00000004-1', 'schema': 'public',
                    'requested_tables': ['tickets'], 'missing_tables': []}}
        if os.environ.get('LEGACY_MANIFEST'): data.pop('row_count_evidence')
        if os.environ.get('WRONG_DUMP'): data['sha256'] = 'a' * 64
        Path(args[-1]).write_text(json.dumps({'modstore': data}) if args[-1].endswith('.json') else 'fixture dump')
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
"""
    )
    runner.chmod(0o700)
    (binary / "coscmd").symlink_to(runner)
    config = tmp_path / "retention.conf"
    config.write_text("tickets|created_at|30|100\nother_events|created_at|30|100\n")
    return {
        **os.environ,
        "PATH": str(binary) + os.pathsep + os.environ["PATH"],
        "FHD_MODSTORE_PG_CONTAINER": "fixture-postgres",
        "CLI_LOG": str(tmp_path / "calls.jsonl"),
        "FHD_PG_RETENTION_CONF": str(config),
        "FHD_PG_RETENTION_LOG": str(tmp_path / "retention.log"),
    }


def execute(name, env, *args):
    return subprocess.run(
        ["bash", str(SCRIPTS / name), *args], env=env, capture_output=True, text=True, timeout=20
    )


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
    assert any('SELECT count(*) FROM public."tickets"' in row[-1] for row in calls(commands))


@pytest.mark.parametrize(
    "extra,code,message",
    [
        ({"LEGACY_MANIFEST": "1"}, 2, "UNVERIFIED"),
        ({"WRONG_DUMP": "1"}, 1, "SHA256"),
        ({"EXPECTED_ROWS": "11", "FHD_DRILL_ROW_TOLERANCE": "99"}, 1, "精确行数不匹配"),
    ],
)
def test_restore_requires_bound_exact_evidence(commands, extra, code, message):
    result = execute("fhd-restore-drill.sh", {**commands, **extra})
    assert result.returncode == code
    assert message in result.stdout + result.stderr
    assert "恢复演练完成" not in result.stdout
    if "EXPECTED_ROWS" not in extra:
        assert not any("CREATE DATABASE" in row[-1] for row in calls(commands))


def test_dry_run_does_not_claim_a_completed_restore(commands):
    result = execute("fhd-restore-drill.sh", commands, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "实际恢复和行数比对未执行" in result.stdout
    assert "恢复演练完成" not in result.stdout


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
