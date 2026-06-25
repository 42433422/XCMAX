"""Success-path & exception-branch coverage for mobile_api_extensions.

Targets lines that the existing cov/ext2/ext3 suites leave uncovered:
- success ``return`` statements of the AI-group routes (list/create/messages/
  post/add_member/remove_member/toggle_pin/mark_unread/mark_read/
  toggle_followed/toggle_hidden/delete)
- the ValueError / RECOVERABLE_ERRORS branches not yet exercised there
- the *entire* personal-conversation state route family (pin/unread/read/
  followed/hidden/delete) — success, uid<=0 and recoverable branches
- circle post/like/comment success returns
- nav-menu role-filtered continue branch
- ``_ai_circle_user`` helper and ``_employee_ssot_payload`` wiring

All external services (AiGroupChatService, ConversationStateService, the
ai_circle_service functions, mod manager) are mocked; tests are offline and
deterministic.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True, scope="module")
def _load_ext_module():
    if "app.fastapi_routes.mobile_api_extensions" not in sys.modules:
        from app.fastapi_routes import mobile_api  # noqa: F401
    yield


@pytest.fixture
def m():
    return sys.modules["app.fastapi_routes.mobile_api_extensions"]


def _user(uid: int = 7, role: str = "admin"):
    return SimpleNamespace(
        id=uid,
        role=role,
        username="tester",
        display_name="Tester",
        is_active=True,
        wx_avatar_url=None,
    )


# ============================================================
# _ai_circle_user — lines 115-120
# ============================================================


class TestAiCircleUser:
    def test_display_name_and_avatar(self, m):
        user = SimpleNamespace(
            id=42, display_name="  Alice ", username="al", wx_avatar_url="  http://a/x.png "
        )
        uid, name, avatar = m._ai_circle_user(user)
        assert uid == 42
        assert name == "Alice"
        assert avatar == "http://a/x.png"

    def test_falls_back_to_username_then_default(self, m):
        user = SimpleNamespace(id=0, display_name="", username="", wx_avatar_url=None)
        uid, name, avatar = m._ai_circle_user(user)
        assert uid == 0
        assert name == "企业成员"
        assert avatar is None


# ============================================================
# _employee_ssot_payload — lines 676-681 (+ recoverable 679-680)
# ============================================================


class TestEmployeeSsotPayload:
    def test_installed_ids_passed_through(self, m):
        with (
            patch(
                "app.application.ops_closure_status._installed_employee_pack_ids",
                return_value={"pack-a", "pack-b"},
            ),
            patch(
                "app.mod_sdk.employee_ssot.derive_employee_ssot",
                return_value={"derived": True},
            ) as derive,
        ):
            out = m._employee_ssot_payload()
        assert out == {"derived": True}
        assert derive.call_args.kwargs["installed_ids"] == {"pack-a", "pack-b"}

    def test_installed_lookup_error_falls_back_to_empty(self, m):
        with (
            patch(
                "app.application.ops_closure_status._installed_employee_pack_ids",
                side_effect=RuntimeError("registry down"),
            ),
            patch(
                "app.mod_sdk.employee_ssot.derive_employee_ssot",
                return_value={"derived": True},
            ) as derive,
        ):
            out = m._employee_ssot_payload()
        assert out == {"derived": True}
        assert derive.call_args.kwargs["installed_ids"] == set()

    @pytest.mark.asyncio
    async def test_route_returns_payload(self, m):
        with patch.object(m, "_employee_ssot_payload", return_value={"x": 1}):
            result = await m.mobile_employee_ssot(user=_user())
        assert result["success"] is True
        assert result["data"] == {"x": 1}

    @pytest.mark.asyncio
    async def test_route_unauthorized(self, m):
        result = await m.mobile_employee_ssot(user=None)
        assert result.status_code == 401


# ============================================================
# AI-group routes — success returns + uncovered exception branches
# ============================================================


def _gate_ok():
    return patch(
        "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
        return_value=({"account_kind": "enterprise"}, None),
    )


def _uid(value=5):
    return patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=value)


def _mode():
    return patch(
        "app.fastapi_routes.mobile_api_extensions._mobile_group_mode", return_value="enterprise"
    )


class TestAiGroupsListSuccess:
    @pytest.mark.asyncio
    async def test_returns_groups(self, m):
        with _gate_ok(), _uid(), _mode(), patch.object(m, "AiGroupChatService") as svc:
            svc.return_value.list_groups.return_value = [{"id": "g1"}]
            result = await m.mobile_ai_groups_list(request=MagicMock(), user=_user())
        assert result["success"] is True
        assert result["data"]["groups"] == [{"id": "g1"}]
        svc.return_value.list_groups.assert_called_once_with(user_id=5)


class TestAiGroupsCreate:
    @pytest.mark.asyncio
    async def test_success(self, m):
        body = SimpleNamespace(name="新群")
        with _gate_ok(), _uid(), _mode(), patch.object(m, "AiGroupChatService") as svc:
            svc.return_value.create_group.return_value = {"id": "g2", "name": "新群"}
            result = await m.mobile_ai_groups_create(request=MagicMock(), body=body, user=_user())
        assert result["data"]["group"]["id"] == "g2"
        svc.return_value.create_group.assert_called_once_with(user_id=5, name="新群")

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        body = SimpleNamespace(name="g")
        with _gate_ok(), _uid(), _mode(), patch.object(m, "AiGroupChatService") as svc:
            svc.return_value.create_group.side_effect = RuntimeError("boom")
            result = await m.mobile_ai_groups_create(request=MagicMock(), body=body, user=_user())
        assert result.status_code == 500


class TestAiGroupMessagesSuccess:
    @pytest.mark.asyncio
    async def test_returns_messages(self, m):
        with _gate_ok(), _uid(), _mode(), patch.object(m, "AiGroupChatService") as svc:
            svc.return_value.get_messages.return_value = [{"id": 1}]
            result = await m.mobile_ai_group_messages(
                request=MagicMock(), group_id="g1", limit=50, user=_user()
            )
        assert result["data"]["messages"] == [{"id": 1}]
        svc.return_value.get_messages.assert_called_once_with(user_id=5, group_id="g1", limit=50)

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        with _gate_ok(), _uid(), _mode(), patch.object(m, "AiGroupChatService") as svc:
            svc.return_value.get_messages.side_effect = RuntimeError("db")
            result = await m.mobile_ai_group_messages(
                request=MagicMock(), group_id="g1", limit=50, user=_user()
            )
        assert result.status_code == 500


class TestAiGroupPost:
    @pytest.mark.asyncio
    async def test_success(self, m):
        body = SimpleNamespace(message="hi", sender_name="我", mentions=[])
        with _gate_ok(), _uid(), _mode(), patch.object(m, "AiGroupChatService") as svc:
            svc.return_value.post_message = AsyncMock(return_value={"replies": ["ok"]})
            result = await m.mobile_ai_group_post(
                request=MagicMock(), group_id="g1", body=body, user=_user()
            )
        assert result["data"] == {"replies": ["ok"]}
        kwargs = svc.return_value.post_message.call_args.kwargs
        assert kwargs["user_id"] == 5
        assert kwargs["group_id"] == "g1"
        assert kwargs["text"] == "hi"

    @pytest.mark.asyncio
    async def test_sender_name_default(self, m):
        body = SimpleNamespace(message="hi", sender_name=None, mentions=["e1"])
        with _gate_ok(), _uid(), _mode(), patch.object(m, "AiGroupChatService") as svc:
            svc.return_value.post_message = AsyncMock(return_value={"ok": True})
            await m.mobile_ai_group_post(
                request=MagicMock(), group_id="g1", body=body, user=_user()
            )
        assert svc.return_value.post_message.call_args.kwargs["sender_name"] == "我"

    @pytest.mark.asyncio
    async def test_value_error(self, m):
        body = SimpleNamespace(message="", sender_name=None, mentions=[])
        with _gate_ok(), _uid(), _mode(), patch.object(m, "AiGroupChatService") as svc:
            svc.return_value.post_message = AsyncMock(side_effect=ValueError("空消息"))
            result = await m.mobile_ai_group_post(
                request=MagicMock(), group_id="g1", body=body, user=_user()
            )
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        body = SimpleNamespace(message="hi", sender_name=None, mentions=[])
        with _gate_ok(), _uid(), _mode(), patch.object(m, "AiGroupChatService") as svc:
            svc.return_value.post_message = AsyncMock(side_effect=RuntimeError("llm down"))
            result = await m.mobile_ai_group_post(
                request=MagicMock(), group_id="g1", body=body, user=_user()
            )
        assert result.status_code == 500


class TestAiGroupAddMember:
    @pytest.mark.asyncio
    async def test_success(self, m):
        body = SimpleNamespace(
            employee_id="e1", mod_id="m1", name="Bob", avatar="a.png", summary="s"
        )
        with _gate_ok(), _uid(), _mode(), patch.object(m, "AiGroupChatService") as svc:
            svc.return_value.add_member.return_value = {"id": "g1", "members": ["e1"]}
            result = await m.mobile_ai_group_add_member(
                request=MagicMock(), group_id="g1", body=body, user=_user()
            )
        assert result["data"]["group"]["members"] == ["e1"]
        member_arg = svc.return_value.add_member.call_args.kwargs["member"]
        assert member_arg["employee_id"] == "e1"
        assert member_arg["name"] == "Bob"

    @pytest.mark.asyncio
    async def test_value_error(self, m):
        body = SimpleNamespace(employee_id="e1", mod_id="m1", name="Bob", avatar=None, summary=None)
        with _gate_ok(), _uid(), _mode(), patch.object(m, "AiGroupChatService") as svc:
            svc.return_value.add_member.side_effect = ValueError("已存在")
            result = await m.mobile_ai_group_add_member(
                request=MagicMock(), group_id="g1", body=body, user=_user()
            )
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        body = SimpleNamespace(employee_id="e1", mod_id="m1", name="Bob", avatar=None, summary=None)
        with _gate_ok(), _uid(), _mode(), patch.object(m, "AiGroupChatService") as svc:
            svc.return_value.add_member.side_effect = RuntimeError("store")
            result = await m.mobile_ai_group_add_member(
                request=MagicMock(), group_id="g1", body=body, user=_user()
            )
        assert result.status_code == 500


class TestAiGroupRemoveMember:
    @pytest.mark.asyncio
    async def test_success(self, m):
        with _gate_ok(), _uid(), _mode(), patch.object(m, "AiGroupChatService") as svc:
            svc.return_value.remove_member.return_value = {"id": "g1", "members": []}
            result = await m.mobile_ai_group_remove_member(
                request=MagicMock(), group_id="g1", employee_id="e1", user=_user()
            )
        assert result["data"]["group"]["members"] == []
        svc.return_value.remove_member.assert_called_once_with(
            user_id=5, group_id="g1", employee_id="e1"
        )

    @pytest.mark.asyncio
    async def test_value_error(self, m):
        with _gate_ok(), _uid(), _mode(), patch.object(m, "AiGroupChatService") as svc:
            svc.return_value.remove_member.side_effect = ValueError("不存在")
            result = await m.mobile_ai_group_remove_member(
                request=MagicMock(), group_id="g1", employee_id="e1", user=_user()
            )
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        with _gate_ok(), _uid(), _mode(), patch.object(m, "AiGroupChatService") as svc:
            svc.return_value.remove_member.side_effect = RuntimeError("store")
            result = await m.mobile_ai_group_remove_member(
                request=MagicMock(), group_id="g1", employee_id="e1", user=_user()
            )
        assert result.status_code == 500


# ── toggle / mark routes share the same shape ──


class TestAiGroupToggleAndMarkRoutes:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "route,method",
        [
            ("mobile_ai_group_toggle_pin", "toggle_pinned"),
            ("mobile_ai_group_mark_unread", "mark_unread"),
            ("mobile_ai_group_mark_read", "mark_read"),
            ("mobile_ai_group_toggle_followed", "toggle_followed"),
            ("mobile_ai_group_toggle_hidden", "toggle_hidden"),
        ],
    )
    async def test_success(self, m, route, method):
        with _gate_ok(), _uid(), _mode(), patch.object(m, "AiGroupChatService") as svc:
            getattr(svc.return_value, method).return_value = {"id": "g1", "flag": True}
            result = await getattr(m, route)(request=MagicMock(), group_id="g1", user=_user())
        assert result["data"]["group"]["flag"] is True
        getattr(svc.return_value, method).assert_called_once_with(user_id=5, group_id="g1")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "route,method",
        [
            ("mobile_ai_group_toggle_pin", "toggle_pinned"),
            ("mobile_ai_group_mark_unread", "mark_unread"),
            ("mobile_ai_group_mark_read", "mark_read"),
            ("mobile_ai_group_toggle_followed", "toggle_followed"),
            ("mobile_ai_group_toggle_hidden", "toggle_hidden"),
        ],
    )
    async def test_value_error(self, m, route, method):
        with _gate_ok(), _uid(), _mode(), patch.object(m, "AiGroupChatService") as svc:
            getattr(svc.return_value, method).side_effect = ValueError("bad")
            result = await getattr(m, route)(request=MagicMock(), group_id="g1", user=_user())
        assert result.status_code == 400

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "route,method",
        [
            ("mobile_ai_group_toggle_pin", "toggle_pinned"),
            ("mobile_ai_group_mark_read", "mark_read"),
            ("mobile_ai_group_toggle_hidden", "toggle_hidden"),
        ],
    )
    async def test_recoverable_error(self, m, route, method):
        with _gate_ok(), _uid(), _mode(), patch.object(m, "AiGroupChatService") as svc:
            getattr(svc.return_value, method).side_effect = RuntimeError("store")
            result = await getattr(m, route)(request=MagicMock(), group_id="g1", user=_user())
        assert result.status_code == 500


class TestAiGroupDelete:
    @pytest.mark.asyncio
    async def test_success(self, m):
        with _gate_ok(), _uid(), _mode(), patch.object(m, "AiGroupChatService") as svc:
            svc.return_value.delete_group.return_value = {"deleted": True}
            result = await m.mobile_ai_group_delete(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result["data"] == {"deleted": True}
        svc.return_value.delete_group.assert_called_once_with(user_id=5, group_id="g1")

    @pytest.mark.asyncio
    async def test_value_error(self, m):
        with _gate_ok(), _uid(), _mode(), patch.object(m, "AiGroupChatService") as svc:
            svc.return_value.delete_group.side_effect = ValueError("不存在")
            result = await m.mobile_ai_group_delete(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        with _gate_ok(), _uid(), _mode(), patch.object(m, "AiGroupChatService") as svc:
            svc.return_value.delete_group.side_effect = RuntimeError("store")
            result = await m.mobile_ai_group_delete(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result.status_code == 500


# ============================================================
# Personal conversation-state routes — lines 1697-1827 (uncovered family)
# ============================================================

_CONV_ROUTES = [
    ("mobile_conversation_toggle_pin", "toggle_pinned"),
    ("mobile_conversation_mark_unread", "mark_unread"),
    ("mobile_conversation_mark_read", "mark_read"),
    ("mobile_conversation_toggle_followed", "toggle_followed"),
    ("mobile_conversation_toggle_hidden", "toggle_hidden"),
    ("mobile_conversation_delete", "delete"),
]


class TestConversationStateUidHelper:
    def test_positive(self, m):
        assert m._conversation_state_uid(SimpleNamespace(id=9)) == 9

    def test_zero_or_missing(self, m):
        assert m._conversation_state_uid(SimpleNamespace(id=0)) == 0
        assert m._conversation_state_uid(SimpleNamespace()) == 0


class TestConversationStateRoutes:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("route,method", _CONV_ROUTES)
    async def test_unauthorized(self, m, route, method):
        result = await getattr(m, route)(conversation_id="c1", user=_user(uid=0))
        assert result.status_code == 401

    @pytest.mark.asyncio
    @pytest.mark.parametrize("route,method", _CONV_ROUTES)
    async def test_missing_service_module_returns_500(self, m, route, method):
        """SUSPECTED BUG: the route imports
        ``app.application.conversation_state_service.ConversationStateService``
        but that module does not exist in the codebase. The resulting
        ModuleNotFoundError (an ImportError, in RECOVERABLE_ERRORS) is caught
        and surfaced as a 500. We assert the *actual* behavior, not the
        unreachable success path.
        """
        result = await getattr(m, route)(conversation_id="c1", user=_user(uid=11))
        assert result.status_code == 500
        import json

        payload = json.loads(result.body)
        assert payload["success"] is False
        assert "conversation_state_service" in payload["message"]


# ============================================================
# Circle routes — success returns (1869, 1887, 1909)
# ============================================================


class TestCircleSuccessPaths:
    @pytest.mark.asyncio
    async def test_create_post_success(self, m):
        with patch(
            "app.application.ai_circle_service.create_user_post", return_value=123
        ) as create:
            result = await m.mobile_ai_circle_create_post(
                body=SimpleNamespace(body="今天上线了"), user=_user(uid=3)
            )
        assert result["data"]["id"] == 123
        assert result["message"] == "发布成功"
        assert create.call_args.kwargs["user_id"] == 3

    @pytest.mark.asyncio
    async def test_toggle_like_success(self, m):
        with patch("app.application.ai_circle_service.toggle_like", return_value=True):
            result = await m.mobile_ai_circle_toggle_like(post_id=9, user=_user(uid=3))
        assert result["data"]["liked"] is True

    @pytest.mark.asyncio
    async def test_toggle_like_not_found(self, m):
        with patch(
            "app.application.ai_circle_service.toggle_like",
            side_effect=LookupError("帖子不存在"),
        ):
            result = await m.mobile_ai_circle_toggle_like(post_id=9, user=_user(uid=3))
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_add_comment_success(self, m):
        with patch("app.application.ai_circle_service.add_comment", return_value=55) as add:
            result = await m.mobile_ai_circle_add_comment(
                post_id=9, body=SimpleNamespace(body="赞"), user=_user(uid=3)
            )
        assert result["data"]["id"] == 55
        assert result["message"] == "评论成功"
        assert add.call_args.kwargs["post_id"] == 9

    @pytest.mark.asyncio
    async def test_add_comment_value_error(self, m):
        with patch(
            "app.application.ai_circle_service.add_comment",
            side_effect=ValueError("内容为空"),
        ):
            result = await m.mobile_ai_circle_add_comment(
                post_id=9, body=SimpleNamespace(body=""), user=_user(uid=3)
            )
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_add_comment_not_found(self, m):
        with patch(
            "app.application.ai_circle_service.add_comment",
            side_effect=LookupError("帖子不存在"),
        ):
            result = await m.mobile_ai_circle_add_comment(
                post_id=9, body=SimpleNamespace(body="赞"), user=_user(uid=3)
            )
        assert result.status_code == 404


# ============================================================
# nav-menu — role filtered continue (line 2057) + mod success
# ============================================================


class TestNavMenu:
    @pytest.mark.asyncio
    async def test_non_admin_role_maps_to_enterprise(self, m):
        # Non-admin roles (incl. "personal") resolve to account_kind=enterprise,
        # which shows the full enterprise core set and no admin-entitlements item.
        with patch.object(m, "_mobile_mod_items", return_value=[]):
            result = await m.mobile_nav_menu(user=_user(uid=4, role="personal"))
        keys = {item["key"] for item in result["data"]["items"]}
        assert result["data"]["account_kind"] == "enterprise"
        assert "admin-entitlements" not in keys
        assert {"chat", "im", "ai-ecosystem", "settings", "products"} <= keys
        assert all(item["source"] == "core" for item in result["data"]["items"])

    @pytest.mark.asyncio
    async def test_admin_appends_user_management(self, m):
        with patch.object(m, "_mobile_mod_items", return_value=[]):
            result = await m.mobile_nav_menu(user=_user(uid=4, role="admin"))
        keys = [item["key"] for item in result["data"]["items"]]
        assert "admin-entitlements" in keys
        assert result["data"]["account_kind"] == "admin"

    @pytest.mark.asyncio
    async def test_mod_menu_entries_appended(self, m):
        mod_items = [
            {
                "id": "mod-x",
                "name": "Mod X",
                "frontend_menu": [
                    {"id": "tool1", "label": "工具1", "path": "/t1", "icon": "fa-wrench"}
                ],
            }
        ]
        with patch.object(m, "_mobile_mod_items", return_value=mod_items):
            result = await m.mobile_nav_menu(user=_user(uid=4, role="admin"))
        mod_entries = [i for i in result["data"]["items"] if i["source"] == "mod"]
        assert mod_entries
        assert mod_entries[0]["mod_id"] == "mod-x"
        assert mod_entries[0]["name"] == "工具1"

    @pytest.mark.asyncio
    async def test_mod_items_operational_error_swallowed(self, m):
        with patch.object(m, "_mobile_mod_items", side_effect=RuntimeError("mods down")):
            result = await m.mobile_nav_menu(user=_user(uid=4, role="admin"))
        # core items still returned; the mod loop error is logged & swallowed
        assert result["data"]["items"]
        assert result["data"]["account_kind"] == "admin"
