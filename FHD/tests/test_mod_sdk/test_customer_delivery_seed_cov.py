"""Seed archive robustness; authentication and owner isolation use real route tests."""

import json
import zipfile
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.mod_sdk.customer_delivery_seed import (
    _resolve_version,
    _safe_member_relpath,
    extract_customer_delivery_seed,
)
from app.mod_sdk.owner_workspace import owner_context, owner_workspace


@pytest.fixture
def seed_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "workspace"))
    with owner_context("tenant:seed-contract"):
        yield owner_workspace("sunbird-attendance-custom")


@pytest.mark.parametrize(
    "name",
    ["/etc/passwd", "../file", "config/../file", "config/./file", "config//file"],
)
def test_rejects_ambiguous_or_escaping_member_paths(name):
    with pytest.raises(ValueError, match="非法路径"):
        _safe_member_relpath(name)


@pytest.mark.parametrize(
    "rows,expected",
    [([], ""), ([{"version": " 1.2.0 "}], "1.2.0"), (["2.0.0"], "2.0.0"), ([None], "")],
)
async def test_version_discovery_uses_catalog_contract(monkeypatch, rows, expected):
    get = AsyncMock(return_value={"versions": rows})
    monkeypatch.setattr("app.mod_sdk.customer_delivery_seed.catalog_get_json", get)
    assert await _resolve_version("seed-fixture", "") == expected
    get.assert_awaited_once_with("/packages/by-id/seed-fixture/versions")


async def test_explicit_version_does_not_fetch_or_float(monkeypatch):
    get = AsyncMock()
    monkeypatch.setattr("app.mod_sdk.customer_delivery_seed.catalog_get_json", get)
    assert await _resolve_version("seed-fixture", "1.0.0") == "1.0.0"
    get.assert_not_awaited()


def test_duplicate_and_symlink_members_fail_before_any_write(tmp_path, seed_workspace):
    archive = tmp_path / "seed.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("config/sunbird-roster.json", json.dumps({"employees": []}))
        entry = zipfile.ZipInfo("424/考勤-2026-3月份考勤统计表.xlsx")
        entry.create_system = 3
        entry.external_attr = 0o120777 << 16
        package.writestr(entry, "../../private.xlsx")
    with pytest.raises(ValueError, match="符号链接"):
        extract_customer_delivery_seed(archive)
    assert not seed_workspace.root.exists()
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("config/sunbird-roster.json", json.dumps({"employees": []}))
        with pytest.warns(UserWarning, match="Duplicate"):
            package.writestr("config/sunbird-roster.json", json.dumps({"employees": []}))
    with pytest.raises(ValueError, match="重复"):
        extract_customer_delivery_seed(archive)
    assert not seed_workspace.root.exists()


def test_preexisting_template_symlink_is_not_followed(tmp_path, seed_workspace):
    outside = tmp_path / "outside.xlsx"
    outside.write_bytes(b"keep")
    seed_workspace.root.mkdir(parents=True)
    (seed_workspace.root / "attendance-template.xlsx").symlink_to(outside)
    archive = tmp_path / "seed.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("424/考勤-2026-3月份考勤统计表.xlsx", b"new")
    with pytest.raises(HTTPException) as caught:
        extract_customer_delivery_seed(archive)
    assert caught.value.status_code == 409
    assert outside.read_bytes() == b"keep"


def test_declared_archive_limit_prevents_extraction(tmp_path, seed_workspace, monkeypatch):
    archive = tmp_path / "seed.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("424/考勤-2026-3月份考勤统计表.xlsx", b"0123456789")
    monkeypatch.setattr("app.mod_sdk.customer_delivery_seed._MAX_SEED_BYTES", 5)
    with pytest.raises(ValueError, match="64 MB"):
        extract_customer_delivery_seed(archive)
    assert not seed_workspace.root.exists()
