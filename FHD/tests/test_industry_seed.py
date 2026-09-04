from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.mod_sdk.delivery_industry_runtime import ensure_delivery_industry_bundle_for_account
from app.mod_sdk.industry_seed import (
    deactivate_other_open_industry_mods,
    industry_mod_id_for,
    industry_seed_mod_ids_for,
    install_industry_seed_with_fallback,
    open_industry_seed_mod_ids,
    other_open_industry_mod_ids,
    refresh_installed_industry_mods_from_bundle,
    resolve_industry_or_mod_id,
    seed_industry_mod,
)


def test_open_industry_seed_mod_ids_matches_baseline():
    ids = open_industry_seed_mod_ids()
    assert "coating-industry" in ids
    assert "attendance-industry" in ids
    assert "accessories-packaging-industry" in ids
    assert "sz-qsm-pro" not in ids
    assert "taiyangniao-pro" not in ids


def test_industry_mod_id_for_coating():
    assert industry_mod_id_for("涂料") == "coating-industry"
    assert industry_mod_id_for("考勤") == "attendance-industry"
    assert industry_mod_id_for("饰品包装") == "accessories-packaging-industry"


def test_accessories_packaging_seed_bundle_includes_unified_attendance():
    assert industry_seed_mod_ids_for("饰品包装") == [
        "accessories-packaging-industry",
        "attendance-industry",
    ]


def test_resolve_industry_or_mod_id():
    iid, mid = resolve_industry_or_mod_id("涂料")
    assert iid == "涂料"
    assert mid == "coating-industry"
    iid2, mid2 = resolve_industry_or_mod_id("coating-industry")
    assert mid2 == "coating-industry"


def test_other_open_industry_mod_ids_excludes_keep():
    others = other_open_industry_mod_ids("coating-industry")
    assert "coating-industry" not in others
    assert "attendance-industry" in others


def test_seed_industry_mod_from_pool(tmp_path, monkeypatch):
    pool = tmp_path / "industry-seeds"
    src = pool / "coating-industry"
    src.mkdir(parents=True)
    (src / "manifest.json").write_text('{"id":"coating-industry","name":"涂料"}', encoding="utf-8")

    mods_root = tmp_path / "mods"
    mods_root.mkdir()

    monkeypatch.setenv("XCAGI_INDUSTRY_SEEDS_DIR", str(pool))
    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        lambda: type(
            "MM",
            (),
            {
                "mods_root": str(mods_root),
                "invalidate_scan_cache": lambda self: None,
                "load_mod": lambda self, mid: True,
                "unload_mod": lambda self, mid: True,
            },
        )(),
    )

    result = seed_industry_mod("涂料")
    assert result["success"] is True
    assert result["status"] in ("seeded", "already_present")
    assert (mods_root / "coating-industry" / "manifest.json").is_file()


def test_seed_industry_mod_pool_missing(tmp_path, monkeypatch):
    mods_root = tmp_path / "mods"
    mods_root.mkdir()
    monkeypatch.delenv("XCAGI_INDUSTRY_SEEDS_DIR", raising=False)
    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        lambda: type("MM", (), {"mods_root": str(mods_root)})(),
    )
    monkeypatch.setattr(
        "app.mod_sdk.industry_seed.bundled_industry_seeds_dir",
        lambda: None,
    )
    result = seed_industry_mod("涂料")
    assert result["success"] is False
    assert result["status"] == "pool_missing"


def test_refresh_installed_industry_mod_from_bundle_archives_stale_copy(tmp_path, monkeypatch):
    pool = tmp_path / "industry-seeds"
    source = pool / "attendance-industry"
    source.mkdir(parents=True)
    (source / "manifest.json").write_text('{"id":"attendance-industry","version":"2"}')
    (source / "dashboard.js").write_text("new dashboard")

    mods_root = tmp_path / "mods"
    installed = mods_root / "attendance-industry"
    installed.mkdir(parents=True)
    (installed / "manifest.json").write_text('{"id":"attendance-industry","version":"1"}')
    (installed / "local-only.txt").write_text("stale")

    invalidations: list[bool] = []

    class FakeMM:
        def __init__(self) -> None:
            self.mods_root = str(mods_root)

        def invalidate_scan_cache(self) -> None:
            invalidations.append(True)

    monkeypatch.setenv("XCAGI_INDUSTRY_SEEDS_DIR", str(pool))
    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        lambda: FakeMM(),
    )
    monkeypatch.setattr(
        "app.mod_sdk.industry_seed.open_industry_seed_mod_ids",
        lambda: ["attendance-industry", "coating-industry"],
    )

    result = refresh_installed_industry_mods_from_bundle()

    assert result[0]["mod_id"] == "attendance-industry"
    assert result[0]["status"] == "refreshed"
    assert invalidations == [True]
    assert (installed / "dashboard.js").read_text() == "new dashboard"
    assert not (installed / "local-only.txt").exists()
    archives = list(
        (tmp_path / "bundled-mod-backups" / "attendance-industry").glob("*/local-only.txt")
    )
    assert len(archives) == 1
    assert archives[0].read_text() == "stale"


def test_refresh_installed_industry_mods_does_not_install_unselected(tmp_path, monkeypatch):
    pool = tmp_path / "industry-seeds"
    source = pool / "coating-industry"
    source.mkdir(parents=True)
    (source / "manifest.json").write_text('{"id":"coating-industry"}')
    mods_root = tmp_path / "mods"
    mods_root.mkdir()

    monkeypatch.setenv("XCAGI_INDUSTRY_SEEDS_DIR", str(pool))
    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        lambda: type("MM", (), {"mods_root": str(mods_root)})(),
    )
    monkeypatch.setattr(
        "app.mod_sdk.industry_seed.open_industry_seed_mod_ids",
        lambda: ["coating-industry"],
    )

    assert refresh_installed_industry_mods_from_bundle() == []
    assert not (mods_root / "coating-industry").exists()


def test_deactivate_other_open_industry_mods(tmp_path, monkeypatch):
    keep = "coating-industry"
    other = "attendance-industry"
    mods_root = tmp_path / "mods"
    (mods_root / other).mkdir(parents=True)
    (mods_root / other / "manifest.json").write_text("{}", encoding="utf-8")

    unloaded: list[str] = []
    root = str(mods_root)

    class FakeMM:
        mods_root = root

        def unload_mod(self, mod_id: str) -> bool:
            unloaded.append(mod_id)
            return True

    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        lambda: FakeMM(),
    )
    rows = deactivate_other_open_industry_mods(keep, remove_files=True)
    assert other in unloaded
    assert not (mods_root / other).exists()
    assert any(r.get("mod_id") == other for r in rows)


@pytest.mark.asyncio
async def test_accessories_packaging_install_copies_shell_and_attendance(tmp_path, monkeypatch):
    pool = tmp_path / "industry-seeds"
    for mod_id in ("accessories-packaging-industry", "attendance-industry"):
        source = pool / mod_id
        source.mkdir(parents=True)
        (source / "manifest.json").write_text(
            f'{{"id":"{mod_id}","name":"{mod_id}"}}',
            encoding="utf-8",
        )
    mods_root = tmp_path / "mods"
    (mods_root / "coating-industry").mkdir(parents=True)
    loaded: list[str] = []
    unloaded: list[str] = []

    class FakeMM:
        def __init__(self) -> None:
            self.mods_root = str(mods_root)

        def invalidate_scan_cache(self) -> None:
            return None

        def load_mod(self, mod_id: str) -> bool:
            loaded.append(mod_id)
            return True

        def unload_mod(self, mod_id: str) -> bool:
            unloaded.append(mod_id)
            return True

    manager = FakeMM()
    monkeypatch.setenv("XCAGI_INDUSTRY_SEEDS_DIR", str(pool))
    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        lambda: manager,
    )

    result = await install_industry_seed_with_fallback("饰品包装")

    assert result["success"] is True
    assert result["installed_mod_ids"] == [
        "accessories-packaging-industry",
        "attendance-industry",
    ]
    assert loaded == result["installed_mod_ids"]
    assert (mods_root / "accessories-packaging-industry" / "manifest.json").is_file()
    assert (mods_root / "attendance-industry" / "manifest.json").is_file()
    assert not (mods_root / "coating-industry").exists()
    assert "coating-industry" in unloaded


@pytest.mark.asyncio
async def test_delivery_account_runtime_self_heal_installs_bundle_and_mounts_routes(monkeypatch):
    install = AsyncMock(
        return_value={
            "success": True,
            "status": "bundle",
            "industry_id": "饰品包装",
            "installed_mod_ids": [
                "accessories-packaging-industry",
                "attendance-industry",
            ],
        }
    )
    route_calls: list[str] = []

    class FakeMM:
        def scan_mods(self, *, use_cache: bool = True):
            assert use_cache is False
            return []

    def ensure_route(mod_id: str) -> bool:
        route_calls.append(mod_id)
        return True

    monkeypatch.setattr(
        "app.mod_sdk.delivery_industry_runtime.industry_id_for_account",
        lambda username: "饰品包装" if username.casefold() == "sunbird" else "",
    )
    monkeypatch.setattr(
        "app.mod_sdk.delivery_industry_runtime.install_industry_seed_with_fallback",
        install,
    )
    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        lambda: FakeMM(),
    )
    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.ensure_mod_api_ready",
        ensure_route,
    )

    result = await ensure_delivery_industry_bundle_for_account("SUNBIRD")

    install.assert_awaited_once_with("饰品包装")
    assert result["success"] is True
    assert result["installed_mod_ids"] == [
        "accessories-packaging-industry",
        "attendance-industry",
    ]
    assert result["route_ready_mod_ids"] == result["installed_mod_ids"]
    assert result["runtime_ready"] is True
    assert route_calls == result["installed_mod_ids"]


@pytest.mark.asyncio
async def test_delivery_account_runtime_self_heal_skips_unknown_account(monkeypatch):
    install = AsyncMock()
    monkeypatch.setattr(
        "app.mod_sdk.delivery_industry_runtime.industry_id_for_account",
        lambda _username: "",
    )
    monkeypatch.setattr(
        "app.mod_sdk.delivery_industry_runtime.install_industry_seed_with_fallback",
        install,
    )

    result = await ensure_delivery_industry_bundle_for_account("ordinary-user")

    assert result["success"] is True
    assert result["status"] == "not_customer_delivery_account"
    install.assert_not_awaited()


@pytest.mark.asyncio
async def test_delivery_account_runtime_self_heal_skips_empty_username():
    result = await ensure_delivery_industry_bundle_for_account("  ")

    assert result["success"] is True
    assert result["status"] == "skipped"
    assert result["installed_mod_ids"] == []


@pytest.mark.asyncio
async def test_delivery_account_runtime_self_heal_reports_install_failure(monkeypatch):
    monkeypatch.setattr(
        "app.mod_sdk.delivery_industry_runtime.industry_id_for_account",
        lambda _username: "饰品包装",
    )
    monkeypatch.setattr(
        "app.mod_sdk.delivery_industry_runtime.install_industry_seed_with_fallback",
        AsyncMock(return_value={"success": False, "status": "pool_missing"}),
    )

    result = await ensure_delivery_industry_bundle_for_account("SUNBIRD")

    assert result["success"] is False
    assert result["industry_id"] == "饰品包装"
    assert result["route_ready_mod_ids"] == []
