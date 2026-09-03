"""Regression coverage for failures discovered in the installed macOS app."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_clear_missing_local_mod_also_clears_runtime_integrity_issue() -> None:
    from app.infrastructure.mods import missing_local_state

    missing_local_state._MISSING_LOCAL.add("coating-industry")
    with patch("app.runtime_integrity.clear_runtime_issue") as clear_issue:
        missing_local_state.clear_mod_missing_locally("coating-industry")

    assert "coating-industry" not in missing_local_state._MISSING_LOCAL
    clear_issue.assert_called_once_with("industry_mod:coating-industry")


def test_missing_open_industry_mod_is_restored_from_bundled_seed_before_mount() -> None:
    from app.infrastructure.mods.mod_manager import ensure_mod_api_ready

    mm = MagicMock()
    mm._loaded_mods = set()
    mm._http_routes_registered = set()
    mm.resolve_mod_directory.return_value = None

    def seed_industry(mod_id: str) -> dict[str, object]:
        mm._loaded_mods.add(mod_id)
        return {"success": True, "status": "seeded", "mod_id": mod_id}

    with (
        patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
        patch("app.infrastructure.mods.mod_manager._restore_entitlements_from_session_id"),
        patch("app.infrastructure.mods.mod_manager._mod_allowed_for_api_load", return_value=True),
        patch("app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mm),
        patch(
            "app.mod_sdk.industry_seed.open_industry_seed_mod_ids",
            return_value=["coating-industry"],
        ),
        patch("app.mod_sdk.industry_seed.seed_industry_mod", side_effect=seed_industry) as seed,
        patch("app.infrastructure.mods.mod_manager.clear_mod_missing_locally") as clear_missing,
        patch("app.fastapi_app.get_fastapi_app", return_value="app"),
        patch(
            "app.infrastructure.mods.mod_manager._register_single_mod_http_routes",
            return_value=True,
        ) as register,
    ):
        assert ensure_mod_api_ready("coating-industry", session_id="session") is True

    seed.assert_called_once_with("coating-industry")
    mm.load_mod.assert_not_called()
    clear_missing.assert_called_with("coating-industry")
    register.assert_called_once_with("app", mm, "coating-industry")


def test_pick_recovery_revision_prefers_latest_known_revision_on_or_before_stamp_date() -> None:
    from app.desktop_runtime.migrate import _pick_recovery_revision

    known = {
        "2026_06_22_baseline_squashed_schema",
        "2026_08_10_erp_absorb_orthogonal",
        "2026_08_20_repair_products_uom",
        "2026_08_31_enterprise_cs_ai",
    }
    # 事故复现：2026_08_24_erp_hr_attendance 已从链中删除，恢复点应落在 08_20。
    assert (
        _pick_recovery_revision("2026_08_24_erp_hr_attendance", known)
        == "2026_08_20_repair_products_uom"
    )
    # 时间早于链中所有节点 → 回退到链上最早的日期节点。
    assert (
        _pick_recovery_revision("2026_01_01_something", known)
        == "2026_06_22_baseline_squashed_schema"
    )
    # 戳本身不带日期前缀 → 同样回退到最早节点。
    assert (
        _pick_recovery_revision("legacy_plain_stamp", known)
        == "2026_06_22_baseline_squashed_schema"
    )


def test_repair_unknown_stamped_revision_snapshots_and_restamps(tmp_path) -> None:
    import sqlite3

    from app.desktop_runtime import migrate

    data_dir = tmp_path / "xcagi-root"
    db_dir = data_dir / "data"
    db_dir.mkdir(parents=True)
    db = db_dir / "xcagi.db"
    with sqlite3.connect(str(db)) as conn:
        conn.execute("create table alembic_version (version_num varchar(32) not null)")
        conn.execute("insert into alembic_version values ('2026_08_24_erp_hr_attendance')")

    with (
        patch.object(
            migrate,
            "_known_alembic_revisions",
            return_value={"2026_08_20_repair_products_uom", "2026_08_31_enterprise_cs_ai"},
        ),
        patch.object(migrate, "_run_alembic_cli") as cli,
    ):
        result = migrate.repair_unknown_stamped_revision(data_dir)

    assert result == {
        "from": "2026_08_24_erp_hr_attendance",
        "to": "2026_08_20_repair_products_uom",
    }
    # 恢复点写入 alembic_version（直接覆写，不走 alembic CLI）。
    with sqlite3.connect(str(db)) as conn:
        assert (
            conn.execute("select version_num from alembic_version").fetchone()[0]
            == "2026_08_20_repair_products_uom"
        )
    # 修复路径不得再调用 alembic CLI（在线 stamp 会先解析链外旧戳并失败）。
    cli.assert_not_called()
    # 先留热备份快照再动版本表。
    backups = list((data_dir / "backups").glob("xcagi-pre-revfix-*.db"))
    assert len(backups) == 1


def test_repair_skips_when_stamp_is_in_chain(tmp_path) -> None:
    import sqlite3

    from app.desktop_runtime import migrate

    data_dir = tmp_path / "xcagi-root"
    db_dir = data_dir / "data"
    db_dir.mkdir(parents=True)
    db = db_dir / "xcagi.db"
    with sqlite3.connect(str(db)) as conn:
        conn.execute("create table alembic_version (version_num varchar(32) not null)")
        conn.execute("insert into alembic_version values ('2026_08_31_enterprise_cs_ai')")

    with (
        patch.object(
            migrate,
            "_known_alembic_revisions",
            return_value={"2026_08_31_enterprise_cs_ai"},
        ),
        patch.object(migrate, "_run_alembic_cli") as cli,
        patch.object(migrate, "backup_database") as backup,
    ):
        assert migrate.repair_unknown_stamped_revision(data_dir) is None

    cli.assert_not_called()
    backup.assert_not_called()


def test_repair_skips_without_alembic_version_table(tmp_path) -> None:
    import sqlite3

    from app.desktop_runtime import migrate

    data_dir = tmp_path / "xcagi-root"
    db_dir = data_dir / "data"
    db_dir.mkdir(parents=True)
    db = db_dir / "xcagi.db"
    with sqlite3.connect(str(db)) as conn:
        conn.execute("create table some_business_table (id integer)")

    with (
        patch.object(migrate, "_run_alembic_cli") as cli,
        patch.object(migrate, "backup_database") as backup,
    ):
        assert migrate.repair_unknown_stamped_revision(data_dir) is None

    cli.assert_not_called()
    backup.assert_not_called()
