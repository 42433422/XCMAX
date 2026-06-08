"""``runtime_allowlist_api`` + ``package_allowlist`` 单测。"""

from __future__ import annotations

import json
import types
import uuid
from pathlib import Path

import pytest

pytest.importorskip("fastapi")


# ----------------------------- pure helpers ----------------------------- #


def test_upsert_and_remove_package(tmp_path: Path):
    from modstore_server.script_agent import package_allowlist as pa

    p = tmp_path / "allow.json"
    p.write_text(json.dumps({"packages": {}}), encoding="utf-8")

    meta = pa.upsert_package(
        "pandas",
        version_spec=">=2.0",
        approved_by="alice",
        notes="数据分析",
        path=p,
    )
    assert meta["version_spec"] == ">=2.0"
    assert meta["approved_by"] == "alice"
    assert "approved_at" in meta
    assert "pandas" in pa.allowed_packages(p)

    removed = pa.remove_package("pandas", path=p)
    assert removed is True
    assert "pandas" not in pa.allowed_packages(p)

    # 二次删除返回 False
    assert pa.remove_package("pandas", path=p) is False


def test_upsert_rejects_invalid_name(tmp_path: Path):
    from modstore_server.script_agent import package_allowlist as pa

    p = tmp_path / "allow.json"
    with pytest.raises(ValueError):
        pa.upsert_package("not a package!", path=p)


# ----------------------------- API ----------------------------- #


def _make_user(is_admin: bool = False):
    from modstore_server.models import User, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        user = User(
            username=f"al_user_{uuid.uuid4().hex[:8]}",
            email=f"al_{uuid.uuid4().hex[:8]}@pytest.local",
            password_hash="x",
            is_admin=is_admin,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return types.SimpleNamespace(id=user.id, username=user.username, is_admin=is_admin)


@pytest.fixture
def temp_allowlist(tmp_path, monkeypatch):
    """把 allowlist 路径指向 tmp_path 隔离测试。"""
    from modstore_server.script_agent import package_allowlist as pa

    p = tmp_path / "runtime_allowlist.json"
    p.write_text(json.dumps({"$schema_version": 1, "packages": {}}), encoding="utf-8")
    monkeypatch.setattr(pa, "DEFAULT_ALLOWLIST", p)
    return p


def test_list_endpoint_visible_to_any_user(client, temp_allowlist):
    from modstore_server import runtime_allowlist_api as al
    from modstore_server.app import app

    user = _make_user(is_admin=False)
    app.dependency_overrides[al._get_current_user] = lambda: user
    try:
        # 先植入一行
        from modstore_server.script_agent import package_allowlist as pa

        pa.upsert_package("openpyxl", version_spec=">=3", approved_by="seed", path=temp_allowlist)

        r = client.get("/api/admin/runtime-allowlist")
        assert r.status_code == 200
        body = r.json()
        names = [p["name"] for p in body["packages"]]
        assert "openpyxl" in names
        assert body["total"] == 1
    finally:
        app.dependency_overrides.pop(al._get_current_user, None)


def test_upsert_endpoint_requires_admin(client, temp_allowlist):
    from modstore_server import runtime_allowlist_api as al
    from modstore_server.app import app

    user = _make_user(is_admin=False)
    app.dependency_overrides[al._require_admin] = lambda: (_ for _ in ()).throw(
        __import__("fastapi").HTTPException(403, "需要管理员权限")
    )
    app.dependency_overrides[al._get_current_user] = lambda: user
    try:
        r = client.post(
            "/api/admin/runtime-allowlist",
            json={"name": "pandas", "version_spec": ">=2.0", "notes": "x"},
        )
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(al._require_admin, None)
        app.dependency_overrides.pop(al._get_current_user, None)


def test_admin_can_upsert_and_delete(client, temp_allowlist):
    from modstore_server import runtime_allowlist_api as al
    from modstore_server.app import app

    admin = _make_user(is_admin=True)
    app.dependency_overrides[al._require_admin] = lambda: admin
    app.dependency_overrides[al._get_current_user] = lambda: admin
    try:
        r = client.post(
            "/api/admin/runtime-allowlist",
            json={"name": "numpy", "version_spec": ">=1.20", "notes": "数学"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["approved_by"] == admin.username

        r2 = client.get("/api/admin/runtime-allowlist")
        names = [p["name"] for p in r2.json()["packages"]]
        assert "numpy" in names

        r3 = client.delete("/api/admin/runtime-allowlist/numpy")
        assert r3.status_code == 200
        r4 = client.get("/api/admin/runtime-allowlist")
        names2 = [p["name"] for p in r4.json()["packages"]]
        assert "numpy" not in names2
    finally:
        app.dependency_overrides.pop(al._require_admin, None)
        app.dependency_overrides.pop(al._get_current_user, None)


def test_static_checker_picks_up_admin_added_package(client, temp_allowlist, monkeypatch):
    """端到端：管理员加包后，static_checker 立刻接受 import。"""
    from modstore_server import runtime_allowlist_api as al
    from modstore_server.app import app
    from modstore_server.script_agent.static_checker import validate_script

    admin = _make_user(is_admin=True)
    app.dependency_overrides[al._require_admin] = lambda: admin
    app.dependency_overrides[al._get_current_user] = lambda: admin
    try:
        # 加包前 import 被拒
        assert validate_script("import requests\n", allowlist_path=temp_allowlist)

        # 管理员审核加包
        r = client.post(
            "/api/admin/runtime-allowlist",
            json={"name": "requests", "version_spec": ">=2", "notes": "http client"},
        )
        assert r.status_code == 200

        # 再校验：放行
        assert not validate_script("import requests\n", allowlist_path=temp_allowlist)
    finally:
        app.dependency_overrides.pop(al._require_admin, None)
        app.dependency_overrides.pop(al._get_current_user, None)
