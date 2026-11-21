"""员工空间 API 复用会话与既有 Mod 安装归属，账号切换不能泄露宿主或其他租户。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.fastapi_routes.platform_shell_routes import router
from app.fastapi_routes.system_routes import router as system_router
from app.infrastructure.auth import dependencies
from app.mod_sdk import employee_directory, runtime_frontend

HOST = "fhd-core-maintainer"
ENDPOINTS = ("employee-directory", "employee-ssot")


@pytest.fixture
def client(monkeypatch):
    users = {
        "a": (1, "user", "enterprise", 11),
        "b": (2, "user", "enterprise", 22),
        "platform": (9, "admin", "admin", None),
        "tenant-admin": (1, "admin", "admin", 11),
        "role-only": (3, "admin", "enterprise", None),
        "tier-only": (4, "user", "admin", None),
        "disabled": (5, "admin", "admin", None),
    }

    def session_user(request):
        sid = dependencies.session_id_from_request(request)
        if sid not in users:
            return None
        uid, role, tier, tenant = users[sid]
        return SimpleNamespace(
            id=uid, role=role, tier=tier, tenant_id=tenant, is_active=sid != "disabled"
        )

    monkeypatch.setattr(dependencies, "resolve_session_user", session_user)
    monkeypatch.setattr(
        "app.application.session_account_meta.enrich_session_meta_with_tenant",
        lambda sid, user: {"tenant_id": user.tenant_id, "local_user_id": user.id},
    )
    manifests = {
        eid: {
            "id": eid,
            "version": "1.0.0",
            "name": f"员工 {eid}",
            "scope": "account" if eid.startswith("private-") else "global",
            "enterprise_layer": "service",
            "employee_config_v2": {"cognition": {"agent": {"system_prompt": "已配置提示词"}}},
        }
        for eid in (HOST, "shared", "prompt", "private-a", "private-b", "private-unverified")
    }
    manifests["runtime-a"] = {
        "id": "runtime-a",
        "version": "1.0.0",
        "name": "拥有者的全局运行扩展",
        "scope": "global",
        "frontend": {"runtime": {"sdk_version": 1}},
    }
    records = [{"pack_id": eid, "manifest": manifest} for eid, manifest in manifests.items()]
    monkeypatch.setattr(employee_directory, "list_installed_pack_records", lambda: records)
    monkeypatch.setattr(
        "app.mod_sdk.employee_ssot_contacts.load_employee_manifest_meta",
        lambda: {eid: {"name": row["name"], "description": eid} for eid, row in manifests.items()},
    )
    monkeypatch.setattr(
        "app.mod_sdk.employee_ssot.load_enterprise_employees",
        lambda: {
            eid: {
                "id": eid,
                "label": row["name"],
                "enterprise_layer": "service",
                "listing": "listed",
                "source": "mod",
                "mod_id": eid,
            }
            for eid, row in manifests.items()
            if eid != HOST
        },
    )
    monkeypatch.setattr(
        "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
        lambda: {
            "employee_pack_tools": [
                {"pack_id": eid, "runtime_ok": eid != "prompt", "handlers": []} for eid in manifests
            ]
        },
    )

    def verified_install(mod_id):
        if mod_id == "private-unverified":
            raise HTTPException(409, "未验证安装")
        owner = "tenant:22" if mod_id == "private-b" else "tenant:11"
        return {"mod_id": mod_id, "owner_scope": owner, "package_version": "1.0.0"}

    # Only the receipt bytes are fixtures; authorized_install's owner and
    # account-bound entitlement checks execute unchanged through the real route.
    monkeypatch.setattr(runtime_frontend, "_verified_install", verified_install)
    monkeypatch.setattr(
        runtime_frontend,
        "_verified_file",
        lambda install, path: json.dumps(manifests[install["mod_id"]]).encode(),
    )
    monkeypatch.setattr(
        runtime_frontend,
        "load_session_private_delivery_binding",
        lambda sid: {
            "market_user_id": sid,
            "mod_ids": {"private-b"} if sid == "b" else {"private-a"},
        },
    )
    app = FastAPI()
    app.include_router(router)
    app.include_router(system_router)
    with TestClient(app) as api:
        yield api


def get(client, endpoint, session):
    return client.get(f"/api/platform-shell/{endpoint}", headers={"X-Session-ID": session})


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_requires_real_active_session(client, monkeypatch, endpoint):
    # Even a development write-lock bypass and a forged identity header do not
    # turn this read into an anonymous inventory of host employees.
    monkeypatch.setenv("FHD_DISABLE_DB_WRITE_LOCK", "1")
    monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "1")
    response = client.get(f"/api/platform-shell/{endpoint}", headers={"X-User-ID": "9"})
    assert response.status_code == 401
    assert get(client, endpoint, "disabled").status_code == 403


def test_directory_uses_private_install_owner_and_no_shared_response_cache(client):
    for session, expected in (
        ("a", {"shared", "prompt", "private-a", "runtime-a"}),
        ("b", {"shared", "prompt", "private-b"}),
        ("a", {"shared", "prompt", "private-a", "runtime-a"}),
    ):
        response = get(client, "employee-directory", session)
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "private, no-store"
        data = response.json()["data"]
        assert data["scope"] == "tenant"
        assert {row["pack_id"] for row in data["employees"]} == expected
        assert data["count"] == len(expected)
        prompt = next(row for row in data["employees"] if row["pack_id"] == "prompt")
        assert prompt["prompt_only"] and not prompt["runtime_ok"]


def test_private_employee_still_requires_session_entitlement(client, monkeypatch):
    monkeypatch.setattr(runtime_frontend, "load_session_private_delivery_binding", lambda sid: {})
    data = get(client, "employee-directory", "a").json()["data"]
    assert "private-a" not in {row["pack_id"] for row in data["employees"]}


@pytest.mark.parametrize("session", ["a", "b", "tenant-admin", "role-only", "tier-only"])
def test_enterprise_ssot_cannot_leak_admin_roster_or_private_contacts(client, session):
    directory = get(client, "employee-directory", session).json()["data"]
    allowed = {row["pack_id"] for row in directory["employees"]}
    response = get(client, "employee-ssot", session)
    data = response.json()["data"]
    assert response.headers["Cache-Control"] == "private, no-store"
    assert HOST not in allowed
    assert data["scope"] == "tenant"
    assert data["admin"] == {
        "departments": [],
        "planned_employee_ids": [],
        "on_duty_employee_ids": [],
    }
    assert len(data["enterprise"]["layers"]) == 4
    assert set(data["enterprise"]["listed_employee_ids"]) == allowed
    assert {
        row["id"] for layer in data["enterprise"]["layers"] for row in layer["employees"]
    } == allowed
    assert {row["employee_id"] for row in data["contacts"]} == allowed
    assert set(data["employee_labels"]) == allowed
    assert set(data["employee_descriptions"]) == allowed
    prompt = next(row for row in data["contacts"] if row["employee_id"] == "prompt")
    assert prompt["installed"] is True and prompt["runnable"] is False


def test_platform_admin_sees_real_host_directory_and_six_departments(client):
    directory = get(client, "employee-directory", "platform").json()["data"]
    assert directory["scope"] == "platform"
    assert {row["pack_id"] for row in directory["employees"]} == {HOST, "shared", "prompt"}
    data = get(client, "employee-ssot", "platform").json()["data"]
    assert data["scope"] == "platform"
    assert len(data["admin"]["departments"]) == 6
    assert data["admin"]["on_duty_employee_ids"] == [HOST]
    assert HOST in {row["employee_id"] for row in data["contacts"]}
    assert "private-a" not in data["employee_labels"]


def test_pure_directory_remains_enterprise_by_default(client):
    assert HOST not in {row["pack_id"] for row in employee_directory.build_employee_directory()}
    assert HOST in {
        row["pack_id"] for row in employee_directory.build_employee_directory(include_admin=True)
    }


@pytest.mark.parametrize("endpoint", ["duty-roster", "workflow-employee-catalog"])
def test_system_employee_views_require_real_active_session(client, monkeypatch, endpoint):
    monkeypatch.setenv("FHD_DISABLE_DB_WRITE_LOCK", "1")
    monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "1")
    url = f"/api/system/{endpoint}"
    assert client.get(url, headers={"X-User-ID": "9"}).status_code == 401
    assert client.get(url, headers={"X-Session-ID": "disabled"}).status_code == 403


@pytest.mark.parametrize("session", ["a", "tenant-admin", "role-only", "tier-only"])
def test_non_platform_account_keeps_empty_host_views(client, session):
    headers = {"X-Session-ID": session}
    roster = client.get("/api/system/duty-roster", headers=headers)
    assert roster.status_code == 200
    assert roster.json()["data"]["scope"] == "tenant"
    for key in ("departments", "all_planned_ids", "employee_labels"):
        assert not roster.json()["data"][key]
    catalog = client.get("/api/system/workflow-employee-catalog", headers=headers)
    assert catalog.status_code == 200
    assert catalog.json()["data"] == {"catalog": [], "static_catalog": [], "scope": "tenant"}


def test_real_platform_session_receives_six_departments_and_ssot_employee_ids(client):
    from app.mod_sdk.duty_roster import all_planned_duty_employee_ids

    headers = {"X-Session-ID": "platform"}
    roster = client.get("/api/system/duty-roster", headers=headers)
    assert roster.status_code == 200
    data = roster.json()["data"]
    assert data["scope"] == "platform"
    assert len(data["departments"]) == 6
    assert set(data["all_planned_ids"]) == set(all_planned_duty_employee_ids())
    assert HOST in data["all_planned_ids"]
    catalog = client.get("/api/system/workflow-employee-catalog", headers=headers)
    assert catalog.status_code == 200
    assert catalog.json()["data"]["scope"] == "platform"
    assert catalog.json()["data"]["catalog"]
