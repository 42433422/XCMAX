from __future__ import annotations

import os
from unittest.mock import patch

import pytest

import app.mod_sdk.edition_bootstrap  # force real module load before stub injection in other test files
from app.mod_sdk.edition_policy import (
    configure_edition_defaults,
    resolve_edition,
    seed_edition_mods_from_bundle,
    should_register_host_legacy_routes,
)
from app.mod_sdk.platform_shell import GENERIC_HOST_MOD_IDS, MINIMAL_HOST_MOD_IDS


@pytest.fixture(autouse=True)
def _isolate_edition_and_sku_env(monkeypatch):
    """全量套件中其它用例可能写入 SKU/EDITION，导致本文件断言 full。"""
    for key in (
        "XCAGI_PRODUCT_SKU",
        "XCAGI_EDITION",
        "XCAGI_GENERIC_EDITION",
        "XCAGI_MINIMAL_EDITION",
        "XCAGI_DEFAULT_EDITION",
        "XCAGI_PRODUCT_SKU_FILE",
        "XCAGI_RESOURCES_DIR",
        "XCAGI_DESKTOP_RESOURCES",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        "app.mod_sdk.product_skus.resolve_product_sku",
        lambda: None,
    )
    monkeypatch.setattr(
        "app.mod_sdk.host_profile._resolve_product_sku",
        lambda: None,
    )


def test_resolve_edition_generic(monkeypatch):
    monkeypatch.delenv("XCAGI_EDITION", raising=False)
    monkeypatch.setenv("XCAGI_GENERIC_EDITION", "1")
    monkeypatch.delenv("XCAGI_MINIMAL_EDITION", raising=False)
    assert resolve_edition() == "generic"


def test_resolve_edition_minimal(monkeypatch):
    monkeypatch.setenv("XCAGI_MINIMAL_EDITION", "1")
    monkeypatch.delenv("XCAGI_GENERIC_EDITION", raising=False)
    assert resolve_edition() == "minimal"


def test_legacy_routes_skipped_for_generic(monkeypatch):
    monkeypatch.setenv("XCAGI_GENERIC_EDITION", "1")
    monkeypatch.delenv("XCAGI_REGISTER_LEGACY_ROUTES", raising=False)
    assert should_register_host_legacy_routes() is False


def test_legacy_routes_for_full(monkeypatch):
    monkeypatch.delenv("XCAGI_GENERIC_EDITION", raising=False)
    monkeypatch.delenv("XCAGI_MINIMAL_EDITION", raising=False)
    monkeypatch.delenv("XCAGI_EDITION", raising=False)
    assert should_register_host_legacy_routes() is True


def test_configure_edition_defaults_desktop(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("PYTEST_VERSION", raising=False)
    monkeypatch.delenv("XCAGI_GENERIC_EDITION", raising=False)
    monkeypatch.delenv("XCAGI_EDITION", raising=False)
    configure_edition_defaults(desktop=True)
    assert resolve_edition() == "generic"


def test_seed_refreshes_stale_existing_and_archives_it(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    mods = bundle / "xcagi-planner-bridge"
    mods.mkdir(parents=True)
    (mods / "manifest.json").write_text(
        '{"id":"xcagi-planner-bridge","name":"p"}', encoding="utf-8"
    )
    target = tmp_path / "user-mods"
    target.mkdir()
    existing = target / "xcagi-planner-bridge"
    existing.mkdir()
    (existing / "legacy.py").write_text("old bridge", encoding="utf-8")
    monkeypatch.setenv("XCAGI_BUNDLED_MODS_DIR", str(bundle))
    from app.infrastructure.mods.mod_manager import ModManager

    mm = ModManager(mods_root=str(target))
    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        lambda: mm,
    )
    out = seed_edition_mods_from_bundle("minimal")
    row = next(r for r in out if r["mod_id"] == "xcagi-planner-bridge")
    assert row["status"] == "refreshed"
    assert (existing / "manifest.json").is_file()
    assert not (existing / "legacy.py").exists()
    backups = list((target.parent / "bundled-mod-backups" / "xcagi-planner-bridge").iterdir())
    assert len(backups) == 1
    assert (backups[0] / "legacy.py").read_text(encoding="utf-8") == "old bridge"


def test_seed_skips_existing_when_content_matches_bundle(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    source = bundle / "xcagi-planner-bridge"
    source.mkdir(parents=True)
    (source / "manifest.json").write_text('{"id":"xcagi-planner-bridge"}', encoding="utf-8")
    target = tmp_path / "user-mods"
    existing = target / "xcagi-planner-bridge"
    existing.mkdir(parents=True)
    (existing / "manifest.json").write_text('{"id":"xcagi-planner-bridge"}', encoding="utf-8")
    (existing / "__pycache__").mkdir()
    (existing / "__pycache__" / "legacy.pyc").write_bytes(b"runtime cache")
    monkeypatch.setenv("XCAGI_BUNDLED_MODS_DIR", str(bundle))
    from app.infrastructure.mods.mod_manager import ModManager

    mm = ModManager(mods_root=str(target))
    monkeypatch.setattr("app.infrastructure.mods.mod_manager.get_mod_manager", lambda: mm)
    monkeypatch.setattr(
        "app.mod_sdk.edition_policy.edition_mod_ids", lambda _edition: ("xcagi-planner-bridge",)
    )

    out = seed_edition_mods_from_bundle("minimal")

    assert out[0]["status"] == "skipped"
    assert not (target.parent / "bundled-mod-backups").exists()


def test_seed_refresh_rolls_back_when_atomic_install_fails(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    source = bundle / "xcagi-planner-bridge"
    source.mkdir(parents=True)
    (source / "bridge.py").write_text("new bridge", encoding="utf-8")
    target = tmp_path / "user-mods"
    existing = target / "xcagi-planner-bridge"
    existing.mkdir(parents=True)
    (existing / "bridge.py").write_text("old bridge", encoding="utf-8")
    monkeypatch.setenv("XCAGI_BUNDLED_MODS_DIR", str(bundle))
    from app.infrastructure.mods.mod_manager import ModManager

    mm = ModManager(mods_root=str(target))
    monkeypatch.setattr("app.infrastructure.mods.mod_manager.get_mod_manager", lambda: mm)
    monkeypatch.setattr(
        "app.mod_sdk.edition_policy.edition_mod_ids", lambda _edition: ("xcagi-planner-bridge",)
    )

    real_replace = os.replace
    replace_calls = 0

    def fail_new_copy_once(source_path, destination_path):
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 2:
            raise OSError("simulated install failure")
        return real_replace(source_path, destination_path)

    with patch("app.mod_sdk.edition_policy.os.replace", side_effect=fail_new_copy_once):
        out = seed_edition_mods_from_bundle("minimal")

    assert out[0]["status"] == "error"
    assert (existing / "bridge.py").read_text(encoding="utf-8") == "old bridge"
    assert not list(target.glob(".xcagi-seed-*"))


def test_seed_copies_bundled_employee_packs_without_overwriting_existing(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    employees = bundle / "_employees"
    for pack_id in ("pdf-generate-employee", "pdf-full-read-employee"):
        pack = employees / pack_id
        pack.mkdir(parents=True)
        (pack / "manifest.json").write_text(
            f'{{"id":"{pack_id}","artifact":"employee_pack"}}', encoding="utf-8"
        )
    target = tmp_path / "user-mods"
    existing = target / "_employees" / "pdf-generate-employee"
    existing.mkdir(parents=True)
    (existing / "manifest.json").write_text('{"local":true}', encoding="utf-8")
    monkeypatch.setenv("XCAGI_BUNDLED_MODS_DIR", str(bundle))

    from app.infrastructure.mods.mod_manager import ModManager

    mm = ModManager(mods_root=str(target))
    monkeypatch.setattr("app.infrastructure.mods.mod_manager.get_mod_manager", lambda: mm)
    monkeypatch.setattr("app.mod_sdk.edition_policy.edition_mod_ids", lambda _edition: ())

    result = seed_edition_mods_from_bundle("minimal", mods_root=target)

    rows = {row["mod_id"]: row for row in result}
    assert rows["_employees/pdf-generate-employee"]["status"] == "skipped"
    assert rows["_employees/pdf-full-read-employee"]["status"] == "seeded"
    assert (target / "_employees" / "pdf-full-read-employee" / "manifest.json").is_file()
    assert (existing / "manifest.json").read_text(encoding="utf-8") == '{"local":true}'


def test_seed_edition_does_not_include_open_industry_mods():
    from app.mod_sdk.edition_policy import edition_mod_ids
    from app.mod_sdk.industry_seed import open_industry_seed_mod_ids

    edition_ids = set(edition_mod_ids("generic"))
    for mid in open_industry_seed_mod_ids():
        assert mid not in edition_ids


def test_decoupling_adcdfg_complete():
    from app.mod_sdk.decoupling_progress import build_decoupling_progress_payload

    payload = build_decoupling_progress_payload(list(GENERIC_HOST_MOD_IDS))
    assert payload.get("adcdfg_complete") is True
    assert payload.get("composite_percent") == 100
    assert any(m["id"] == "T" for m in payload.get("milestones", []))


@pytest.mark.asyncio
async def test_bootstrap_edition_pack_smoke(monkeypatch, tmp_path):
    bundle = tmp_path / "bundle"
    for mid in MINIMAL_HOST_MOD_IDS:
        d = bundle / mid
        d.mkdir(parents=True)
        (d / "manifest.json").write_text(
            f'{{"id":"{mid}","name":"{mid}","version":"1.0.0"}}',
            encoding="utf-8",
        )
    target = tmp_path / "mods"
    target.mkdir()
    monkeypatch.setenv("XCAGI_BUNDLED_MODS_DIR", str(bundle))
    monkeypatch.setenv("XCAGI_MODS_ROOT", str(target))
    monkeypatch.setenv("XCAGI_MINIMAL_EDITION", "1")

    from app.infrastructure.mods.mod_manager import ModManager

    mm = ModManager(mods_root=str(target))
    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        lambda: mm,
    )

    from app.mod_sdk.edition_bootstrap import bootstrap_edition_pack

    data = await bootstrap_edition_pack("minimal")
    assert data["edition"] == "minimal"
    assert data["expected_count"] == len(MINIMAL_HOST_MOD_IDS)
