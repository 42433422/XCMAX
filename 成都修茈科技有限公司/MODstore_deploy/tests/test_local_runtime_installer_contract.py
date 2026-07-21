from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]


def test_local_runtime_installer_is_exact_clean_audited_and_recoverable() -> None:
    script = (ROOT / "scripts/install-local-autonomy-runtime.sh").read_text(encoding="utf-8")

    assert "source checkout must be clean" in script
    assert 'git -C "$SOURCE_ROOT" archive --format=tar "$TARGET_SHA"' in script
    assert ".xcmax-runtime-provenance.json" in script
    assert '"files": hashes' in script
    assert "rollback()" in script
    assert "rsync -a --delete" in script
    assert "reset --hard" not in script
    assert "git clean" not in script


def test_manual_trigger_requires_manifest_and_uses_absolute_sqlite_url() -> None:
    script = (REPO_ROOT / "trigger_loop_manual.sh").read_text(encoding="utf-8")

    assert "runtime provenance manifest missing" in script
    assert 'DATABASE_URL="sqlite:///$MODSTORE_RUNTIME_DB_PATH"' in script
    assert 'MODSTORE_CATALOG_DIR="$STATE_ROOT/catalog"' in script
    assert 'XCAGI_FHD_RUNTIME_ROOT="$RUNTIME_ROOT/FHD"' in script
    assert "Desktop/XCMAX/FHD" not in script


def test_sync_runtime_to_source_script_exists_and_is_append_safe() -> None:
    sync = (ROOT / "scripts/sync-runtime-to-source.sh").read_text(encoding="utf-8")
    cron = (ROOT / "scripts/install-sync-runtime-to-source-cron.sh").read_text(encoding="utf-8")

    assert "evolution_decisions.jsonl" in sync
    assert "self_maintenance_loop_runs.jsonl" in sync
    assert "skip smaller runtime copy" in sync
    assert "--commit" in sync
    assert "sync-runtime-to-source.sh" in cron
    assert "crontab" in cron
