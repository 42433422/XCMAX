from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "dev" / "install_modstore_daily_launchd.sh"


def _installer_text() -> str:
    return INSTALLER.read_text(encoding="utf-8")


def test_modstore_catalog_lives_outside_delete_mirror() -> None:
    script = _installer_text()

    assert 'RUNTIME_CATALOG_ROOT="${STATE_ROOT}/catalog"' in script
    assert '--exclude "modstore_server/catalog_data/"' in script
    assert '_env_snapshot_put MODSTORE_CATALOG_DIR "${RUNTIME_CATALOG_ROOT}"' in script
    assert 'export MODSTORE_CATALOG_DIR="${RUNTIME_CATALOG_ROOT}"' in script


def test_legacy_catalog_is_migrated_before_code_rsync() -> None:
    script = _installer_text()
    migration = 'rsync -a --ignore-existing "${legacy_catalog}/" "${RUNTIME_CATALOG_ROOT}/"'
    code_sync = script.index("rsync -a --delete")
    catalog_exclude = script.index('--exclude "modstore_server/catalog_data/"', code_sync)

    assert migration in script
    assert script.index(migration) < code_sync < catalog_exclude


def test_clean_install_materializes_validated_duty_seed() -> None:
    script = _installer_text()

    assert 'MODSTORE_CATALOG_DIR="${RUNTIME_CATALOG_ROOT}" \\' in script
    assert "from modstore_server.duty_employee_registry import load_duty_registry" in script
