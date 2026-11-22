"""Exercise production-to-staging isolation and real bootstrap failure boundaries."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import shlex
import subprocess
import tarfile
from pathlib import Path

import pytest

FHD = Path(__file__).resolve().parents[2]
BOOTSTRAP = FHD / "scripts/deploy/fhd-bootstrap-staging-cvm.sh"
spec = importlib.util.spec_from_file_location(
    "staging_environment", FHD / "scripts/deploy/lib/staging_environment.py"
)
assert spec is not None and spec.loader is not None
staging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(staging)
PRODUCTION = """DATABASE_URL=postgresql+psycopg://user:password@localhost/xcagi?sslmode=require
VECTOR_DB_URL=postgresql+psycopg://user:password@localhost/xcagi
WORKSPACE_ROOT=/opt/fhd-full
XCAGI_API_PORT=5100
MODSTORE_DEPLOY_TIER=production
FHD_DEPLOY_TIER=production
XCAGI_NEURO_BUS_DEDUP=0
XCAGI_DATA_DIR=/var/lib/xcagi
MODEL_NAME=existing-platform-model
XCAGI_GIT_SHA=old-production-identity
"""


def render(source=PRODUCTION, **kwargs):
    return staging.render(
        source,
        **{
            "root": "/opt/fhd-staging",
            "port": 5101,
            "data_root": "/var/lib/xcagi-staging",
            **kwargs,
        },
    )


def settings(text):
    return {
        k: shlex.split(v)[0]
        for line in text.splitlines()
        if "=" in line
        for k, v in [line.split("=", 1)]
    }


def test_existing_production_values_are_replaced_and_runtime_is_isolated():
    value = settings(render())
    assert value["MODSTORE_DEPLOY_TIER"] == value["FHD_DEPLOY_TIER"] == "staging"
    assert (
        value["DATABASE_URL"]
        == value["VECTOR_DB_URL"]
        == "postgresql+psycopg://user:password@localhost/xcagi_staging?sslmode=require"
    )
    assert value["XCAGI_NEURO_BUS_DEDUP"] == "1"
    assert value["XCAGI_API_PORT"] == "5101"
    assert value["XCAGI_DATA_DIR"] == value["XCAGI_DESKTOP_DATA_DIR"] == "/var/lib/xcagi-staging"
    assert value["UPLOAD_FOLDER"] == "/var/lib/xcagi-staging/uploads"
    assert value["MODEL_NAME"] == "existing-platform-model"
    assert value["XCAGI_GIT_SHA"] == ""


@pytest.mark.parametrize(
    "change",
    [
        {"root": "/opt/fhd-full"},
        {"root": "/opt"},
        {"data_root": "/var/lib/xcagi"},
        {"port": 5100},
        {"port": 80},
    ],
)
def test_staging_cannot_overlap_production(change):
    with pytest.raises(ValueError):
        render(**change)


def test_unrecognized_database_is_rejected_instead_of_retaining_production_uri():
    with pytest.raises(ValueError, match="PostgreSQL source"):
        render(PRODUCTION.replace("/xcagi?", "/other?"))


@pytest.mark.parametrize(
    "isolated", [None, "redis://changed:password@cache:6379/0", "redis://cache/1?db=0"]
)
def test_celery_never_consumes_the_production_queue(monkeypatch, isolated):
    monkeypatch.delenv("FHD_STAGING_CELERY_BROKER_URL", raising=False)
    if isolated:
        monkeypatch.setenv("FHD_STAGING_CELERY_BROKER_URL", isolated)
    with pytest.raises(ValueError):
        render(PRODUCTION + "CELERY_BROKER_URL=redis://cache/0\n")


def test_explicit_isolated_redis_backend_is_used(monkeypatch):
    monkeypatch.setenv("FHD_STAGING_CELERY_BROKER_URL", "redis://cache:6379/3")
    assert (
        settings(render(PRODUCTION + "CELERY_BROKER_URL=redis://cache/0\n"))["CELERY_BROKER_URL"]
        == "redis://cache:6379/3"
    )


@pytest.mark.parametrize("restore_fails", [True, False])
def test_schema_restore_failure_or_empty_schema_stops_before_runtime_write(tmp_path, restore_fails):
    """Run the actual shell entrypoint with external PostgreSQL transport substituted."""
    source = tmp_path / "production.env"
    source.write_text(PRODUCTION)
    verifier = tmp_path / "verifier.py"
    verifier.write_text("print('verified test transport')\n")
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        member = tarfile.TarInfo("scripts/deploy/lib/verify_release_archive.py")
        member.size = len(verifier.read_bytes())
        bundle.addfile(member, io.BytesIO(verifier.read_bytes()))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "artifact": archive.name,
                "git_sha": "a" * 40,
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "archive_verifier_sha256": hashlib.sha256(verifier.read_bytes()).hexdigest(),
                "admin_console_sha256": "c" * 64,
            }
        )
    )
    commands = tmp_path / "commands"
    commands.mkdir()
    (commands / "id").write_text("#!/bin/sh\necho 0\n")
    (commands / "docker").write_text("""#!/bin/sh
printf '%s\\n' "$*" >> "$TEST_DOCKER_LOG"
case "$*" in
  *printenv*) echo placeholder ;;
  *"SELECT 1"*) echo 1 ;;
  *pg_dump*) echo '-- schema metadata' ;;
  *--single-transaction*) cat >/dev/null; exit "$TEST_RESTORE_EXIT" ;;
  *"xcagi_staging -tAc"*) echo 0 ;;
  *"xcagi -tAc"*) echo 20 ;;
  *) exit 10 ;;
esac
""")
    for executable in commands.iterdir():
        executable.chmod(0o755)
    target = tmp_path / "staging.env"
    log = tmp_path / "docker.log"
    result = subprocess.run(
        ["bash", str(BOOTSTRAP)],
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "PATH": str(commands) + os.pathsep + os.environ["PATH"],
            "FHD_PROD_ENV_FILE": str(source),
            "FHD_STAGING_ENV_FILE": str(target),
            "FHD_STABLE_MANIFEST": str(manifest),
            "FHD_TRUSTED_ARCHIVE_VERIFY": str(verifier),
            "FHD_STAGING_DEPLOY_ROOT": str(tmp_path / "runtime"),
            "FHD_STAGING_DATA_ROOT": str(tmp_path / "data"),
            "TEST_DOCKER_LOG": str(log),
            "TEST_RESTORE_EXIT": "3" if restore_fails else "0",
        },
        timeout=15,
    )
    assert result.returncode != 0, result.stdout
    assert not target.exists()
    assert source.read_text() == PRODUCTION
    restore = next(line for line in log.read_text().splitlines() if "--single-transaction" in line)
    assert "ON_ERROR_STOP=1" in restore
    assert "--table=public.alembic_version" in log.read_text()
    if not restore_fails:
        assert "staging schema is incomplete" in result.stderr
