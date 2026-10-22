"""Private seed builds cannot repopulate source or ship executable legacy trees."""

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

from scripts.package.private_delivery_paths import private_path


def load_publisher():
    path = (
        Path(__file__).resolve().parents[2]
        / "scripts/package/publish-sunbird-delivery-seed.py"
    )
    spec = importlib.util.spec_from_file_location("private_seed_publisher", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_checkout_and_missing_destination_are_rejected(tmp_path):
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    (checkout / ".git/HEAD").write_text("ref: refs/heads/main\n")
    with pytest.raises(ValueError, match="explicitly"):
        private_path(None, "seed_root")
    with pytest.raises(ValueError, match="Git checkout"):
        private_path(checkout / "delivery", "seed_root")
    assert not (checkout / "delivery").exists()


def test_seed_contains_only_private_data_and_registers_outside_source(tmp_path):
    publisher = load_publisher()
    seed = tmp_path / "seed"
    (seed / "config").mkdir(parents=True)
    (seed / "config/sunbird-roster.json").write_text('{"employees": []}')
    (seed / "424").mkdir()
    (seed / "424/考勤-2026-3月份考勤统计表.xlsx").write_bytes(b"synthetic fixture")
    (seed / "mods/legacy/backend").mkdir(parents=True)
    legacy = seed / "mods/legacy/backend/code.py"
    legacy.write_text("raise RuntimeError('must not ship')")
    artifact = publisher._build_zip(seed, tmp_path / "build", "1.0.0")
    with zipfile.ZipFile(artifact) as archive:
        assert set(archive.namelist()) == {
            "config/sunbird-roster.json",
            "424/考勤-2026-3月份考勤统计表.xlsx",
            "delivery-manifest.json",
        }
    record = publisher._upsert_package(tmp_path / "catalog", artifact, "1.0.0")
    assert record["visibility"] == "private"
    assert record["public_listing"] is False
    assert record["customer_account"] == "SUNBIRD"
    saved = json.loads((tmp_path / "catalog/packages.json").read_text())
    assert saved["packages"] == [record]
    assert legacy.is_file()
