"""Exercise backups on the CI job's explicit disposable PostgreSQL 16 service.

FHD_TEST_PG_CONTAINER must be job.services.postgres.id, never a business service.
Only cloud transfer/config packaging are faked; PostgreSQL commands run natively.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "deploy"


def run(*args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=30, **kwargs)


@pytest.fixture(scope="module")
def postgres():
    container = os.environ.get("FHD_TEST_PG_CONTAINER")
    if not container:
        pytest.skip("requires the CI job's disposable PostgreSQL service")
    assert re.fullmatch(r"[a-f0-9]{64}", container), "use job.services.postgres.id"
    docker = shutil.which("docker")
    assert docker, "configured PostgreSQL integration tests require Docker"
    prefix = [docker, "exec", "-i", container]
    identity = run(
        *prefix,
        "psql",
        "-XAt",
        "-U",
        "agent_test",
        "-d",
        "agent_test",
        "-c",
        "SELECT current_database() || '|' || current_user || '|' || current_setting('server_version_num')",
    ).stdout.strip()
    assert identity.startswith("agent_test|agent_test|16"), "not the disposable PG16 test service"
    binary = run(*prefix, "sh", "-c", 'dirname "$(command -v pg_dump)"').stdout.strip()
    original_path = run(*prefix, "sh", "-c", 'printf "%s" "$PATH"').stdout
    remote = "/tmp/fhd-snapshot-test-" + uuid.uuid4().hex
    wrapper = """#!/bin/sh
set -eu
if [ "${DUMP_FAILURE:-}" = 1 ]; then
  echo 'injected pg_dump failure' >&2
  exit 7
fi
if [ "${CONCURRENT_WRITE:-}" = 1 ]; then
  psql -X -v ON_ERROR_STOP=1 -c 'INSERT INTO tickets SELECT generate_series(11,30); DELETE FROM tickets WHERE id < 4; INSERT INTO events VALUES (1)' >/dev/null
fi
"$FHD_TEST_REAL_PG_DUMP" "$@"
if [ "${COUNT_FAILURE:-}" = 1 ]; then
  psql -X -v ON_ERROR_STOP=1 -c 'DROP TABLE tickets' >/dev/null
fi
"""
    run(
        *prefix,
        "sh",
        "-c",
        f"mkdir -m 700 {remote}; cat > {remote}/pg_dump; chmod 700 {remote}/pg_dump",
        input=wrapper,
    )
    env = {
        **os.environ,
        "REAL_DOCKER": docker,
        "TEST_PG_CONTAINER": container,
        "REAL_PG_BIN": binary,
        "TEST_PG_PATH": remote + ":" + original_path,
    }
    run(
        *prefix,
        "psql",
        "-X",
        "-U",
        "agent_test",
        "-d",
        "postgres",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        "CREATE DATABASE xcagi",
    )
    try:
        yield prefix, env
    finally:
        for database in ("modstore", "xcagi"):
            run(
                *prefix,
                "psql",
                "-X",
                "-U",
                "agent_test",
                "-d",
                "postgres",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                f"DROP DATABASE IF EXISTS {database}",
            )
        run(*prefix, "rm", "-rf", "--", remote)


@pytest.fixture
def backup(postgres, tmp_path):
    prefix, base = postgres
    query = [
        *prefix,
        "psql",
        "-X",
        "-U",
        "agent_test",
        "-d",
        "postgres",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
    ]
    run(*query, "DROP DATABASE IF EXISTS modstore")
    run(*query, "CREATE DATABASE modstore")
    run(
        *prefix,
        "psql",
        "-X",
        "-U",
        "agent_test",
        "-d",
        "modstore",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        "CREATE TABLE tickets (id int PRIMARY KEY) WITH (autovacuum_enabled=false); "
        "CREATE TABLE events (id int); INSERT INTO tickets SELECT generate_series(1,10)",
        env=base,
    )
    run(*prefix, "psql", "-X", "-U", "agent_test", "-d", "modstore", "-c", "SELECT pg_stat_reset()")
    proxy = tmp_path / "bin"
    proxy.mkdir()
    driver = proxy / "docker"
    driver.write_text(
        f"#!{sys.executable}\n"
        + r"""
import json, os, shutil, sys
from pathlib import Path
args = sys.argv[1:]
name = Path(sys.argv[0]).name
binary = Path(os.environ['REAL_PG_BIN'])
with open(os.environ['CLI_LOG'], 'a') as log:
    log.write(json.dumps([name, *args]) + '\n')
if name == 'docker':
    if args[0] == 'ps':
        print('fixture-main\nfixture-modstore')
    else:
        args.pop(0)
        if args[0] == '-i': args.pop(0)
        args.pop(0)
        command = [os.environ['REAL_DOCKER'], 'exec', '-i', '-e', 'PATH=' + os.environ['TEST_PG_PATH'],
                   '-e', 'FHD_TEST_REAL_PG_DUMP=' + str(binary/'pg_dump')]
        for flag in ('DUMP_FAILURE', 'CONCURRENT_WRITE', 'COUNT_FAILURE'):
            command.extend(['-e', flag + '=' + os.environ.get(flag, '')])
        command.extend([os.environ['TEST_PG_CONTAINER'], str(binary/args[0]), *args[1:]])
        os.execv(command[0], command)
elif name == 'tar':
    Path(args[1]).write_bytes(b'isolated config fixture')
elif name == 'coscmd':
    bucket = Path(os.environ['TEST_BUCKET'])
    operation = next(x for x in args if x in ('list', 'upload', 'download', 'copy'))
    if operation == 'list':
        for entry in sorted((bucket / args[-1]).glob('*')): print(entry.name)
    else:
        source, destination = args[-2:]
        source = bucket/source if operation in ('download', 'copy') else Path(source)
        destination = bucket/destination if operation in ('upload', 'copy') else Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
"""
    )
    driver.chmod(0o700)
    for name in ("tar", "coscmd"):
        (proxy / name).symlink_to(driver)
    env = {
        **base,
        "PATH": str(proxy) + os.pathsep + base["PATH"],
        "TEST_BUCKET": str(tmp_path / "bucket"),
        "CLI_LOG": str(tmp_path / "calls.jsonl"),
        "FHD_BACKUP_ROOT": str(tmp_path / "backups"),
        "FHD_BACKUP_LOG": str(tmp_path / "backup.log"),
        "FHD_DEPLOY_ROOT": str(tmp_path / "empty-deploy"),
        "FHD_PG_CONTAINER": "fixture-main",
        "FHD_PG_USER": "agent_test",
        "FHD_MODSTORE_PG_CONTAINER": "fixture-modstore",
        "FHD_MODSTORE_PG_USER": "agent_test",
        "FHD_MODSTORE_DB": "modstore",
        "FHD_MODSTORE_REQUIRED": "1",
        "FHD_BACKUP_ROWCOUNT_TABLES": "tickets,events",
        "DRY_RUN": "0",
    }
    return prefix, env


def script(name, env):
    return subprocess.run(
        ["bash", str(SCRIPTS / name)], env=env, capture_output=True, text=True, timeout=30
    )


def manifest(env):
    return json.loads(next((Path(env["TEST_BUCKET"]) / "manifests").glob("*.json")).read_text())


def test_dump_and_counts_share_snapshot_despite_stale_stats_and_concurrent_writes(backup):
    prefix, env = backup
    query = [*prefix, "psql", "-XAt", "-U", "agent_test", "-d", "modstore", "-c"]
    estimate = run(
        *query, "SELECT n_live_tup FROM pg_stat_user_tables WHERE relname='tickets'", env=env
    )
    assert estimate.stdout.strip() == "0"
    result = script("fhd-backup-daily.sh", {**env, "CONCURRENT_WRITE": "1"})
    assert result.returncode == 0, result.stdout + result.stderr
    data = manifest(env)["modstore"]
    assert data["row_counts"] == {"tickets": 10, "events": 0}
    assert data["row_count_evidence"]["status"] == "verified"
    assert data["row_count_evidence"]["snapshot_id"]
    assert run(*query, "SELECT count(*) FROM tickets", env=env).stdout.strip() == "27"
    restored = script("fhd-restore-drill.sh", env)
    assert restored.returncode == 0, restored.stdout + restored.stderr
    assert "恢复演练完成" in restored.stdout
    leftover = run(
        *query, "SELECT count(*) FROM pg_database WHERE datname LIKE 'fhd_drill_%'", env=env
    )
    assert leftover.stdout.strip() == "0"


@pytest.mark.parametrize("failure", ["DUMP_FAILURE", "COUNT_FAILURE"])
def test_native_command_failure_never_publishes_verified_manifest(backup, failure):
    _binary, env = backup
    result = script("fhd-backup-daily.sh", {**env, failure: "1"})
    assert result.returncode != 0
    assert "未核验，不发布 manifest" in result.stdout
    assert "完成" not in result.stdout
    assert not list(Path(env["TEST_BUCKET"]).glob("manifests/*.json"))
    assert not list(Path(env["FHD_BACKUP_ROOT"]).glob("*/manifest.json"))


def test_missing_snapshot_table_remains_unverified(backup):
    _binary, env = backup
    result = script("fhd-backup-daily.sh", {**env, "FHD_BACKUP_ROWCOUNT_TABLES": "tickets,missing"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert manifest(env)["modstore"]["row_count_evidence"]["status"] == "unverified"
    restored = script("fhd-restore-drill.sh", env)
    assert restored.returncode == 2
    assert "UNVERIFIED" in restored.stdout + restored.stderr
    assert "恢复演练完成" not in restored.stdout


def test_different_valid_archive_is_rejected_before_restore(backup):
    _binary, env = backup
    result = script("fhd-backup-daily.sh", env)
    assert result.returncode == 0, result.stdout + result.stderr
    data = manifest(env)
    archive = Path(env["TEST_BUCKET"]) / data["cos_paths"]["modstore"]
    shutil.copyfile(next(Path(env["FHD_BACKUP_ROOT"]).glob("*/xcagi.dump")), archive)
    Path(env["CLI_LOG"]).write_text("")
    restored = script("fhd-restore-drill.sh", env)
    assert restored.returncode != 0
    assert "SHA256 不匹配" in restored.stderr
    calls = [json.loads(line) for line in Path(env["CLI_LOG"]).read_text().splitlines()]
    assert not any("pg_restore" in call or "CREATE DATABASE" in call[-1] for call in calls)


@pytest.mark.parametrize(
    "case",
    [
        "dry-run",
        "restore",
        "missing-verifier",
        "wrong-digest",
        "uploads-fail",
        "rsync-fail",
        "config-fail",
    ],
)
def test_cos_restore_verifies_before_restore_and_reports_partial_failure(tmp_path, case):
    """Exercise CLI failure contracts only; these stubs are not a native restore drill."""
    proxy = tmp_path / "bin"
    proxy.mkdir()
    for command in ("date", "mkdir", "cat", "sha256sum", "awk"):
        (proxy / command).symlink_to(shutil.which(command))
    if case != "missing-verifier":
        (proxy / "python3").symlink_to(sys.executable)
    archive = b"isolated archive fixture, not a PostgreSQL dump"
    expected = hashlib.sha256(archive).hexdigest() if case != "wrong-digest" else "0" * 64
    (tmp_path / "manifest.json").write_text(json.dumps({"sha256": {"xcagi.dump": expected}}))
    (tmp_path / "xcagi.dump").write_bytes(archive)
    driver = proxy / "docker"
    driver.write_text(
        f"#!{sys.executable}\n"
        + r"""
import json, os, shutil, sys
from pathlib import Path
args = sys.argv[1:]
name = Path(sys.argv[0]).name
with open(os.environ['CLI_LOG'], 'a') as log:
    log.write(json.dumps([name, *args]) + '\n')
case = os.environ['TEST_CASE']
if name == 'docker':
    if 'pg_dump' in args:
        sys.stdout.buffer.write(b'pre-restore snapshot fixture')
    else:
        sys.stdin.buffer.read()
elif name == 'coscmd':
    source, destination = args[-2:]
    if destination in ('manifest.json', 'xcagi.dump'):
        shutil.copyfile(Path(os.environ['TEST_SOURCE']) / destination, destination)
    elif destination in ('uploads/', 'mods/'):
        if destination == 'uploads/' and case == 'uploads-fail':
            raise SystemExit(9)
        Path(destination).mkdir()
    else:
        if case == 'config-fail':
            raise SystemExit(9)
        Path(destination).write_bytes(b'config fixture')
elif name == 'rsync' and case == 'rsync-fail':
    raise SystemExit(9)
"""
    )
    driver.chmod(0o700)
    for name in ("coscmd", "rsync"):
        (proxy / name).symlink_to(driver)
    log = tmp_path / "calls.jsonl"
    env = {
        **os.environ,
        "PATH": str(proxy),
        "CLI_LOG": str(log),
        "TEST_CASE": case,
        "TEST_SOURCE": str(tmp_path),
        "FHD_RESTORE_ROOT": str(tmp_path / "restore"),
        "FHD_PRE_RESTORE_SNAP": str(tmp_path / "pre-restore"),
        "FHD_DEPLOY_ROOT": str(tmp_path / "deploy"),
        "FHD_PG_CONTAINER": "isolated-cli-fixture",
    }
    args = [shutil.which("bash"), str(SCRIPTS / "fhd-restore-from-cos.sh"), "20261123-120000"]
    if case in {"dry-run", "missing-verifier", "wrong-digest"}:
        args.append("--dry-run")
    result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=30)
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    if case in {"missing-verifier", "wrong-digest"}:
        assert result.returncode != 0, result.stdout + result.stderr
        assert not any("pg_restore" in call for call in calls)
    elif case in {"uploads-fail", "rsync-fail", "config-fail"}:
        assert result.returncode != 0, result.stdout + result.stderr
        assert "恢复完成" not in result.stdout
        assert str(tmp_path / "pre-restore") in result.stdout
    elif case == "dry-run":
        assert result.returncode == 0, result.stdout + result.stderr
        assert "sha256 OK" in result.stdout
        assert not any("-d" in call for call in calls if "pg_restore" in call)
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        restore = next(call for call in calls if "pg_restore" in call and "-d" in call)
        assert {"--exit-on-error", "--single-transaction"} <= set(restore)
