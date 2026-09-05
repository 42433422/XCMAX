import importlib.util
import logging
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.mod_sdk.owner_workspace import attendance_database_path, owner_workspace


@pytest.fixture
def attendance_client(mod_accounts):
    source = (
        Path(__file__).resolve().parents[2]
        / "XCAGI/mods/attendance-industry/backend/management_routes.py"
    )
    spec = importlib.util.spec_from_file_location("isolated_attendance_management", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = FastAPI()
    for prefix in ("/api/mod/attendance-industry", "/api/mods/attendance-industry"):
        router = APIRouter(prefix=prefix)
        module.register(
            router,
            logger=logging.getLogger(__name__),
            get_database_path=attendance_database_path,
        )
        app.include_router(router)
    with TestClient(app) as client:
        yield client


def login(client, uid):
    client.cookies.set("session_id", f"mod-session-{uid}")


@pytest.mark.parametrize(
    "prefix", ["/api/mod/attendance-industry", "/api/mods/attendance-industry"]
)
@pytest.mark.parametrize("session", [None, "mod-session-4", "forged"])
def test_all_aliases_deny_missing_expired_or_forged_session(attendance_client, prefix, session):
    if session:
        attendance_client.cookies.set("session_id", session)
    assert attendance_client.get(prefix + "/employees").status_code == 401
    assert (
        attendance_client.post(prefix + "/employees", json={"employee_name": "Blocked"}).status_code
        == 401
    )


def test_disabled_account_cannot_use_shared_attendance(attendance_client):
    login(attendance_client, 3)
    assert attendance_client.get("/api/mod/attendance-industry/employees").status_code == 403


def test_public_crud_and_roster_are_isolated_after_switching_accounts(
    attendance_client, mod_accounts
):
    base = "/api/mod/attendance-industry"
    login(attendance_client, 1)
    created = attendance_client.post(
        base + "/employees",
        json={"employee_name": "Owner One", "department": "Assembly"},
    )
    assert created.status_code == 200
    employee_id = created.json()["data"]["id"]
    assert attendance_client.get(base + "/roster").json()["data"] == [["Assembly", "", "Owner One"]]
    login(attendance_client, 2)
    assert attendance_client.get(base + "/employees").json()["data"]["total"] == 0
    assert attendance_client.get(base + "/roster").json()["data"] == []
    assert attendance_client.delete(base + f"/employees/{employee_id}").status_code == 404
    created_other = attendance_client.post(base + "/employees", json={"employee_name": "Owner Two"})
    assert created_other.status_code == 200
    login(attendance_client, 1)
    assert [
        row["employee_name"]
        for row in attendance_client.get(base + "/employees").json()["data"]["items"]
    ] == ["Owner One"]


def test_unowned_legacy_database_is_never_adopted_or_modified(attendance_client, mod_accounts):
    old = mod_accounts.root / "data/mod_dbs/taiyangniao_pro.db"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"unclaimed-customer-database")
    login(attendance_client, 1)
    response = attendance_client.get("/api/mod/attendance-industry/employees")
    assert response.status_code == 200
    assert response.json()["data"]["total"] == 0
    assert old.read_bytes() == b"unclaimed-customer-database"


def test_workspace_rejects_redirecting_symlink(mod_accounts):
    outside = mod_accounts.root.parent / "other-account"
    outside.mkdir()
    mod_accounts.root.mkdir()
    (mod_accounts.root / "mod-workspaces").symlink_to(outside, target_is_directory=True)
    with pytest.raises(HTTPException) as error:
        owner_workspace("attendance-industry", owner_id="tenant:1")
    assert error.value.status_code == 409
    assert list(outside.iterdir()) == []
