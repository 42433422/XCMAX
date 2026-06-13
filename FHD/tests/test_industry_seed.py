# -*- coding: utf-8 -*-
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.mod_sdk.industry_seed import (
    deactivate_other_open_industry_mods,
    industry_mod_id_for,
    open_industry_seed_mod_ids,
    other_open_industry_mod_ids,
    resolve_industry_or_mod_id,
    seed_industry_mod,
)


def test_open_industry_seed_mod_ids_matches_baseline():
    ids = open_industry_seed_mod_ids()
    assert "coating-industry" in ids
    assert "attendance-industry" in ids
    assert "sz-qsm-pro" not in ids
    assert "taiyangniao-pro" not in ids


def test_industry_mod_id_for_coating():
    assert industry_mod_id_for("涂料") == "coating-industry"
    assert industry_mod_id_for("考勤") == "attendance-industry"


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
