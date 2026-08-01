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
    assert 'SOURCE_ALEMBIC="$STAGE/成都修茈科技有限公司/MODstore_deploy/alembic"' in script
    assert "RUNTIME_FILE_RELATIVES=(" in script
    assert '"FHD/app/services/capability_proposal_recorder.py"' in script
    assert '"FHD/app/services/intent_confirmation_service.py"' in script
    assert '"FHD/config/duty_employee_work_contracts.json"' in script
    assert '"FHD/scripts/dev/capability_proposal_to_issue.py"' in script
    assert 'SOURCE_EMPLOYEES="$STAGE/FHD/mods/_employees"' in script
    assert '"$BACKUP/employees/"' in script
    assert '"$TARGET_ROOT/FHD/mods/_employees/"' in script
    assert '("*/manifest.json", "*/backend/employees/*.py")' in script
    assert '"MODstore_deploy/modstore_server/customer_value_reconciler.py"' in script
    assert '"MODstore_deploy/modstore_server/dead_letter_reconciler.py"' in script
    assert "MODSTORE_LAUNCHCTL_BIN" in script
    assert "MODSTORE_CURL_BIN" in script
    assert "MODSTORE_INSTALL_HEALTH_ATTEMPTS" in script
    assert "MODSTORE_INSTALL_HEALTH_SLEEP_SECONDS" in script
    assert 'if [[ "$READY" != 1 ]]; then' in script
    assert "  rollback\n  exit 5" in script
    assert "reset --hard" not in script
    assert "git clean" not in script


def test_manual_trigger_requires_manifest_and_uses_absolute_sqlite_url() -> None:
    script = (REPO_ROOT / "trigger_loop_manual.sh").read_text(encoding="utf-8")

    assert "runtime provenance manifest missing" in script
    assert 'DATABASE_URL="sqlite:///$MODSTORE_RUNTIME_DB_PATH"' in script
    assert 'MODSTORE_CATALOG_DIR="$STATE_ROOT/catalog"' in script
    assert 'XCAGI_FHD_RUNTIME_ROOT="$RUNTIME_ROOT/FHD"' in script
    assert "Desktop/XCMAX/FHD" not in script
