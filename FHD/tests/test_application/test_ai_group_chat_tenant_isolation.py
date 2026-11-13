"""Synthetic tenant A/B isolation for AI group chat JSONL and route entry points."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.application.ai_group_chat_service import AiGroupChatService
from app.infrastructure.tenant_scope import tenant_scope


async def _complete(_history: list[dict[str, str]]) -> dict[str, Any]:
    return {"success": True, "content": "已记录"}


def _service(tmp_path: Path) -> AiGroupChatService:
    return AiGroupChatService(
        storage_root=tmp_path,
        completion_fn=_complete,
        department_loader=lambda: {},
        employee_loader=lambda: [{"employee_id": "worker", "name": "同事", "department_key": ""}],
    )


@pytest.fixture(autouse=True)
def _secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "ai-group-tenant-isolation-test-secret")
    monkeypatch.delenv("XCAGI_TENANT_ALLOW_LEGACY_NULL_VISIBLE", raising=False)


@pytest.mark.asyncio
async def test_same_user_id_is_isolated_across_tenants_for_all_group_paths(tmp_path: Path) -> None:
    user_id = 1
    with tenant_scope(11):
        tenant_a = _service(tmp_path)
        group = tenant_a.create_group(user_id=user_id, name="甲的群")
        group_id = group["id"]
        tenant_a.add_member(user_id=user_id, group_id=group_id, member={"employee_id": "worker"})
        await tenant_a.post_message(user_id=user_id, group_id=group_id, text="甲的机密")
        tenant_a.toggle_pinned(user_id=user_id, group_id=group_id)
        tenant_a.mark_unread(user_id=user_id, group_id=group_id)
        tenant_a.mark_read(user_id=user_id, group_id=group_id)
        a_path = tenant_a._storage._groups_path

    with tenant_scope(22):
        tenant_b = _service(tmp_path)
        b_names = [row["name"] for row in tenant_b.list_groups(user_id=user_id)]
        assert "甲的群" not in b_names
        assert tenant_b.get_messages(user_id=user_id, group_id=group_id) == []
        with pytest.raises(ValueError, match="群不存在"):
            tenant_b.toggle_pinned(user_id=user_id, group_id=group_id)
        with pytest.raises(ValueError, match="群不存在"):
            tenant_b.toggle_hidden(user_id=user_id, group_id=group_id)
        with pytest.raises(ValueError, match="群不存在"):
            tenant_b.mark_read(user_id=user_id, group_id=group_id)
        with pytest.raises(ValueError, match="群不存在"):
            tenant_b.add_member(
                user_id=user_id, group_id=group_id, member={"employee_id": "worker"}
            )
        with pytest.raises(ValueError, match="群不存在"):
            await tenant_b.post_message(user_id=user_id, group_id=group_id, text="试探")
        other = tenant_b.create_group(user_id=user_id, name="乙的群")
        assert other["id"] != ""
        b_path = tenant_b._storage._groups_path

    with tenant_scope(11):
        tenant_a = _service(tmp_path)
        names = [row["name"] for row in tenant_a.list_groups(user_id=user_id)]
        assert names == ["甲的群"]
        bodies = [row["body"] for row in tenant_a.get_messages(user_id=user_id, group_id=group_id)]
        assert "甲的机密" in bodies
        assert "试探" not in bodies
        assert all("乙的群" not in name for name in names)

    assert "tenants/11/" in a_path.as_posix()
    assert "tenants/22/" in b_path.as_posix()
    assert a_path != b_path


def test_legacy_untagged_rows_are_fail_closed_and_not_migrated(tmp_path: Path) -> None:
    with tenant_scope(11):
        tenant_a = _service(tmp_path)
        visible = tenant_a.create_group(user_id=1, name="可见群")
        groups_path = tenant_a._storage._groups_path
        with groups_path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {"id": "legacy-group", "user_id": 1, "name": "未标注租户的旧群", "members": []},
                    ensure_ascii=False,
                )
                + "\n"
            )
        listed = tenant_a.list_groups(user_id=1)
        assert [row["name"] for row in listed] == ["可见群"]
        assert tenant_a.get_messages(user_id=1, group_id="legacy-group") == []
        with pytest.raises(ValueError, match="群不存在"):
            tenant_a.toggle_hidden(user_id=1, group_id="legacy-group")
        with pytest.raises(ValueError, match="群不存在"):
            tenant_a.delete_group(user_id=1, group_id="legacy-group")
        raw = groups_path.read_text(encoding="utf-8")
        assert "未标注租户的旧群" in raw
        assert visible["id"] in raw


def test_unscoped_default_store_does_not_read_or_write_legacy_jsonl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.application.group_chat.storage.get_app_data_dir", lambda **_k: str(tmp_path)
    )
    legacy = tmp_path / "ai_group_chat"
    legacy.mkdir()
    (legacy / "groups.jsonl").write_text(
        json.dumps({"id": "legacy", "user_id": 1, "name": "共享目录旧群"}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    service = AiGroupChatService(
        storage_root=None,
        department_loader=lambda: {},
        employee_loader=lambda: [],
    )
    assert service.list_groups(user_id=1) == []
    assert service.get_messages(user_id=1, group_id="legacy") == []
    with pytest.raises(ValueError, match="群不存在"):
        service.create_group(user_id=1, name="不应写入")
    raw = (legacy / "groups.jsonl").read_text(encoding="utf-8")
    assert "共享目录旧群" in raw
    assert "不应写入" not in raw
    denied = tmp_path / "tenants" / "_unscoped_denied" / "ai_group_chat" / "groups.jsonl"
    assert not denied.exists()


def test_admin_routes_list_read_and_members_respect_tenant_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.fastapi_routes import im_ai_group_routes as routes

    facade = routes._facade()
    monkeypatch.setattr(facade, "_ai_group_guard", lambda _request: None)
    monkeypatch.setattr(facade, "_uid", lambda _user: 1)
    monkeypatch.setattr(
        facade,
        "AiGroupChatService",
        lambda **kw: AiGroupChatService(
            storage_root=tmp_path,
            completion_fn=_complete,
            department_loader=lambda: {},
            employee_loader=lambda: [{"employee_id": "worker", "name": "同事"}],
            **kw,
        ),
    )
    request = MagicMock()
    user = SimpleNamespace(user_id=1)

    with tenant_scope(11):
        created = routes.admin_ai_groups_create(request, {"name": "甲的群"}, user)
        group_id = created["group"]["id"]
        added = routes.admin_ai_group_add_member(
            request, group_id, {"employee_id": "worker", "name": "同事"}, user
        )
        assert added["success"] is True

    with tenant_scope(22):
        listed = routes.admin_ai_groups_list(request, user)
        assert listed["success"] is True
        assert "甲的群" not in [row["name"] for row in listed["groups"]]
        messages = routes.admin_ai_group_messages(request, group_id, 100, user)
        assert messages["success"] is True
        assert messages["messages"] == []
        missing = routes.admin_ai_group_add_member(
            request, group_id, {"employee_id": "worker", "name": "同事"}, user
        )
        assert missing.status_code == 400

    with tenant_scope(11):
        listed = routes.admin_ai_groups_list(request, user)
        assert [row["name"] for row in listed["groups"]] == ["甲的群"]
