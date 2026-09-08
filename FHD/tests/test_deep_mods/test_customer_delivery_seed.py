"""Actual authenticated seed route and filesystem preservation contracts."""

import json
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.mod_sdk.attendance_roster import read_attendance_roster
from app.mod_sdk.customer_delivery_seed import (
    extract_customer_delivery_seed,
    install_customer_delivery_seed_package,
)
from app.mod_sdk.owner_workspace import owner_context, owner_workspace


def seed_zip(path, *, name="Seed Person", extra=None):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "config/sunbird-roster.json",
            json.dumps({"employees": [{"name": name, "dept": "Assembly", "group": "Day"}]}),
        )
        archive.writestr("424/考勤-2026-3月份考勤统计表.xlsx", b"fixture-template")
        archive.writestr(
            "mods/attendance-industry/backend/code.py", b"legacy-code-must-not-execute"
        )
        archive.writestr("data/mod_dbs/taiyangniao_pro.db", b"legacy-db-must-not-be-claimed")
        if extra:
            archive.writestr(*extra)
    return path


def test_create_only_seed_preserves_modified_template_and_even_empty_roster(mod_accounts, tmp_path):
    archive = seed_zip(tmp_path / "seed.zip")
    with owner_context("tenant:1"):
        first = extract_customer_delivery_seed(archive)
        assert first["roster_initialized"] is True
        assert read_attendance_roster() == [("Assembly", "Day", "Seed Person")]
        root = owner_workspace("sunbird-attendance-custom").root
        template = root / "attendance-template.xlsx"
        template.write_bytes(b"user-edited-template")
        import sqlite3

        db = owner_workspace("attendance-industry").root / "attendance.db"
        with sqlite3.connect(db) as connection:
            connection.execute("DELETE FROM attendance_employees")
        before = db.read_bytes()
        second = extract_customer_delivery_seed(
            seed_zip(tmp_path / "v2.zip", name="Unexpected New Name")
        )
        assert second["roster_initialized"] is False
        assert sorted(second["preserved_files"]) == [
            "attendance-template.xlsx",
            "seed-roster.json",
        ]
        assert template.read_bytes() == b"user-edited-template"
        assert read_attendance_roster() == []
        assert db.read_bytes() == before
        assert not (root / "mods").exists()
    with owner_context("tenant:2"):
        assert read_attendance_roster() == []
        assert not owner_workspace("sunbird-attendance-custom").root.exists()
    assert not (mod_accounts.root / "data/mod_dbs/taiyangniao_pro.db").exists()


@pytest.mark.parametrize(
    "member",
    [
        "/etc/passwd",
        "../outside",
        "config/../escape",
        "unknown/file",
        "config/a/../../escape",
    ],
)
def test_archive_validation_precedes_all_writes(mod_accounts, tmp_path, member):
    archive = seed_zip(tmp_path / "bad.zip", extra=(member, b"forbidden"))
    with owner_context("tenant:1"):
        with pytest.raises(ValueError):
            extract_customer_delivery_seed(archive)
        assert not owner_workspace("sunbird-attendance-custom").root.exists()


def test_ownerless_seed_and_prelogin_legacy_entry_points_do_not_write(mod_accounts, tmp_path):
    from fastapi import HTTPException

    from app.desktop_runtime.sunbird_delivery_seed import (
        apply_sunbird_roster_seed_if_needed,
        sync_sunbird_delivery_files,
    )

    archive = seed_zip(tmp_path / "seed.zip")
    with pytest.raises(HTTPException) as caught:
        extract_customer_delivery_seed(archive)
    assert caught.value.status_code == 401
    assert sync_sunbird_delivery_files(tmp_path) == 0
    assert apply_sunbird_roster_seed_if_needed(tmp_path) is False
    assert not mod_accounts.root.exists()


@pytest.fixture
def seed_client(mod_accounts, tmp_path, monkeypatch):
    archive = seed_zip(tmp_path / "seed.zip")
    downloads = []

    async def download(endpoint, target, *, headers):
        downloads.append((endpoint, headers))
        target.write_bytes(archive.read_bytes())

    monkeypatch.setattr("app.mod_sdk.customer_delivery_seed.catalog_download_to", download)
    monkeypatch.setattr(
        "app.fastapi_routes.market_account.resolve_valid_market_access_token",
        AsyncMock(return_value="current-session-token"),
    )
    app = FastAPI()

    @app.post("/seed")
    async def seed(request: Request):
        return await install_customer_delivery_seed_package(
            request=request,
            mod_id="taiyangniao-pro",
            account_username="SUNBIRD",
            market_token="body-other-account-token",
        )

    with TestClient(app) as client:
        yield client, downloads


@pytest.mark.parametrize(
    "session,status", [("forged", 401), ("mod-session-4", 401), ("mod-session-2", 403)]
)
def test_normal_session_and_entitlement_precede_download(seed_client, session, status):
    client, downloads = seed_client
    client.cookies.set("session_id", session)
    assert client.post("/seed").status_code == status
    assert downloads == []


def test_download_uses_current_session_token_and_authenticated_owner(seed_client, mod_accounts):
    client, downloads = seed_client
    client.cookies.set("session_id", "mod-session-1")
    response = client.post("/seed")
    assert response.status_code == 200, response.text
    assert response.json()["owner_scope"] == "tenant:1"
    assert downloads[0][1] == {"Authorization": "Bearer current-session-token"}
    assert "mod_id=taiyangniao-pro" in downloads[0][0]
    with owner_context("tenant:1"):
        assert len(read_attendance_roster()) == 1
