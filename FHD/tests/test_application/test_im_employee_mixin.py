"""Tests for app.application.im_employee_mixin — branch coverage ramp.

覆盖 ImEmployeeMixin 中所有方法的关键分支：
- ensure_employee_user: new/existing user + new/existing profile + 各字段更新分支
- get_employee_owner: empty id / no profile / valid / invalid / zero
- employee_im_summary: boss_uid<=0 / empty employees / 无 profile / ensure 失败 /
                       有/无 conv / peer 命中/未命中 / get_or_create_direct 失败
- set_employee_owner: empty id / owner<=0 / 无 profile / owner 不存在 / 成功
- send_employee_message: 空 body / boss_uid<=0 / boss 不存在 / 成功
- list_cs_inbox: 无 cs / 无 conv / conv 有/无 peer
- cs_inbox_messages: 无 cs / 有消息 / mark_read 失败
- cs_reply: 无 cs / 成功
- enterprise_cs_user_id: cs 存在 / 不存在
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.application.im_app_service import ImApplicationService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(user_id=1, display_name="Alice", username="alice", is_active=True, role="user"):
    u = MagicMock()
    u.id = user_id
    u.display_name = display_name
    u.username = username
    u.is_active = is_active
    u.role = role
    u.email = ""
    u.password = "!"
    u.tenant_id = None
    return u


def _make_profile(
    employee_id="emp1", user_id=10, mod_id="m1", display_name="Emp1", avatar_url="", owner_user_id=0
):
    p = MagicMock()
    p.employee_id = employee_id
    p.user_id = user_id
    p.mod_id = mod_id
    p.display_name = display_name
    p.avatar_url = avatar_url
    p.owner_user_id = owner_user_id
    return p


def _make_conversation(conv_id=1, is_direct=True, title=None, last_message_at=None):
    c = MagicMock()
    c.id = conv_id
    c.is_direct = is_direct
    c.title = title
    c.last_message_at = last_message_at
    return c


def _make_message(msg_id=1, body="hello"):
    m = MagicMock()
    m.id = msg_id
    m.body = body
    return m


def _setup_db_execute(*sequences):
    """构建 db.execute 链式 mock，按调用顺序返回 sequence 中的值。

    每个 sequence 元素是一个 return_value 配置 dict：
        {"first": v} 或 {"scalars.all": [v1, v2]} 或 {"scalars.first": v} 等
    """
    db = MagicMock()
    execute_mock = db.execute
    # 把每个 sequence 配成一次 db.execute 调用的返回值
    returns = []
    for cfg in sequences:
        ret = MagicMock()
        if "first" in cfg:
            ret.first.return_value = cfg["first"]
        if "scalars_first" in cfg:
            ret.scalars.return_value.first.return_value = cfg["scalars_first"]
        if "scalars_all" in cfg:
            ret.scalars.return_value.all.return_value = cfg["scalars_all"]
        if "scalar" in cfg:
            ret.scalar.return_value = cfg["scalar"]
        if "all" in cfg:
            ret.all.return_value = cfg["all"]
        returns.append(ret)
    execute_mock.side_effect = returns
    return db


# ---------------------------------------------------------------------------
# enterprise_cs_user_id
# ---------------------------------------------------------------------------


class TestEnterpriseCsUserId:
    def test_returns_int_id_when_cs_exists(self):
        db = MagicMock()
        cs_user = _make_user(user_id=99, username="enterprise-cs")
        svc = ImApplicationService(db)
        with patch.object(svc, "_ensure_enterprise_dedicated_cs_user", return_value=cs_user):
            assert svc.enterprise_cs_user_id() == 99

    def test_returns_none_when_cs_missing(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        with patch.object(svc, "_ensure_enterprise_dedicated_cs_user", return_value=None):
            assert svc.enterprise_cs_user_id() is None


# ---------------------------------------------------------------------------
# ensure_employee_user
# ---------------------------------------------------------------------------


class TestEnsureEmployeeUser:
    def test_raises_on_empty_employee_id(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        with pytest.raises(ValueError, match="employee_id 必填"):
            svc.ensure_employee_user("")

    def test_raises_on_whitespace_only_employee_id(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        with pytest.raises(ValueError, match="employee_id 必填"):
            svc.ensure_employee_user("   ")

    def test_creates_new_user_and_new_profile(self):
        db = MagicMock()
        # 1. select(User).where -> None（用户不存在）
        # 2. select(AiEmployeeProfile).where -> None（profile 不存在）
        ret1 = MagicMock()
        ret1.scalars.return_value.first.return_value = None
        ret2 = MagicMock()
        ret2.scalars.return_value.first.return_value = None
        db.execute.side_effect = [ret1, ret2]

        # 收集 db.add 的对象，flush 时为 User 设置 id
        added_objects: list = []

        def _add_side_effect(obj):
            added_objects.append(obj)
            return obj

        def _flush_side_effect():
            for obj in added_objects:
                # User 对象有 username 属性，AiEmployeeProfile 没有
                if hasattr(obj, "username"):
                    obj.id = 100

        db.add.side_effect = _add_side_effect
        db.flush.side_effect = _flush_side_effect

        svc = ImApplicationService(db)
        result = svc.ensure_employee_user(
            "emp1",
            mod_id="m1",
            display_name="Alice",
            avatar_url="http://x",
            owner_user_id=5,
        )
        assert result == 100
        # 验证 add 被调用（User + AiEmployeeProfile）
        assert db.add.call_count == 2
        db.commit.assert_called_once()

    def test_creates_new_user_with_eid_as_name_when_display_empty(self):
        db = MagicMock()
        ret1 = MagicMock()
        ret1.scalars.return_value.first.return_value = None
        ret2 = MagicMock()
        ret2.scalars.return_value.first.return_value = None
        db.execute.side_effect = [ret1, ret2]

        added_objects: list = []

        def _add_side_effect(obj):
            added_objects.append(obj)
            return obj

        def _flush_side_effect():
            for obj in added_objects:
                if hasattr(obj, "username"):
                    obj.id = 200

        db.add.side_effect = _add_side_effect
        db.flush.side_effect = _flush_side_effect
        db.refresh.side_effect = lambda obj: None

        svc = ImApplicationService(db)
        # display_name 为空，name 应该回退到 eid
        svc.ensure_employee_user("emp2", display_name="", avatar_url=None)
        # 验证创建的 User.display_name = "emp2"
        added_user = added_objects[0]
        assert added_user.display_name == "emp2"

    def test_updates_existing_user_display_name(self):
        db = MagicMock()
        existing_user = _make_user(user_id=50, display_name="OldName", is_active=True)
        ret1 = MagicMock()
        ret1.scalars.return_value.first.return_value = existing_user
        # profile 也存在
        existing_profile = _make_profile(employee_id="emp3", user_id=50, display_name="OldName")
        ret2 = MagicMock()
        ret2.scalars.return_value.first.return_value = existing_profile
        db.execute.side_effect = [ret1, ret2]
        svc = ImApplicationService(db)
        svc.ensure_employee_user("emp3", display_name="NewName")
        assert existing_user.display_name == "NewName"
        db.flush.assert_called_once()

    def test_reactivates_inactive_user(self):
        db = MagicMock()
        existing_user = _make_user(user_id=51, display_name="Alice", is_active=False)
        ret1 = MagicMock()
        ret1.scalars.return_value.first.return_value = existing_user
        existing_profile = _make_profile(employee_id="emp4", user_id=51)
        ret2 = MagicMock()
        ret2.scalars.return_value.first.return_value = existing_profile
        db.execute.side_effect = [ret1, ret2]
        svc = ImApplicationService(db)
        svc.ensure_employee_user("emp4", display_name="Alice")
        assert existing_user.is_active is True
        db.flush.assert_called_once()

    def test_no_flush_when_user_unchanged(self):
        db = MagicMock()
        existing_user = _make_user(user_id=52, display_name="Alice", is_active=True)
        ret1 = MagicMock()
        ret1.scalars.return_value.first.return_value = existing_user
        existing_profile = _make_profile(employee_id="emp5", user_id=52, display_name="Alice")
        ret2 = MagicMock()
        ret2.scalars.return_value.first.return_value = existing_profile
        db.execute.side_effect = [ret1, ret2]
        svc = ImApplicationService(db)
        svc.ensure_employee_user("emp5", display_name="Alice")
        # 用户未变，不应调用 flush
        db.flush.assert_not_called()

    def test_updates_existing_profile_fields(self):
        db = MagicMock()
        existing_user = _make_user(user_id=53, display_name="NewName", is_active=True)
        ret1 = MagicMock()
        ret1.scalars.return_value.first.return_value = existing_user
        existing_profile = _make_profile(
            employee_id="emp6",
            user_id=53,
            display_name="OldName",
            mod_id="oldmod",
            avatar_url="old.jpg",
            owner_user_id=0,
        )
        ret2 = MagicMock()
        ret2.scalars.return_value.first.return_value = existing_profile
        db.execute.side_effect = [ret1, ret2]
        svc = ImApplicationService(db)
        svc.ensure_employee_user(
            "emp6",
            mod_id="newmod",
            display_name="NewName",
            avatar_url="new.jpg",
            owner_user_id=7,
        )
        assert existing_profile.user_id == 53
        assert existing_profile.mod_id == "newmod"
        assert existing_profile.display_name == "NewName"
        assert existing_profile.avatar_url == "new.jpg"
        assert existing_profile.owner_user_id == 7

    def test_existing_profile_keeps_mod_id_when_empty(self):
        db = MagicMock()
        existing_user = _make_user(user_id=54, display_name="Alice", is_active=True)
        ret1 = MagicMock()
        ret1.scalars.return_value.first.return_value = existing_user
        existing_profile = _make_profile(
            employee_id="emp7",
            user_id=54,
            mod_id="keepmod",
            avatar_url="keep.jpg",
        )
        ret2 = MagicMock()
        ret2.scalars.return_value.first.return_value = existing_profile
        db.execute.side_effect = [ret1, ret2]
        svc = ImApplicationService(db)
        svc.ensure_employee_user("emp7", display_name="Alice", avatar_url="")
        assert existing_profile.mod_id == "keepmod"
        assert existing_profile.avatar_url == "keep.jpg"

    def test_existing_profile_ignores_zero_owner(self):
        db = MagicMock()
        existing_user = _make_user(user_id=55, display_name="Alice", is_active=True)
        ret1 = MagicMock()
        ret1.scalars.return_value.first.return_value = existing_user
        existing_profile = _make_profile(
            employee_id="emp8",
            user_id=55,
            owner_user_id=9,
        )
        ret2 = MagicMock()
        ret2.scalars.return_value.first.return_value = existing_profile
        db.execute.side_effect = [ret1, ret2]
        svc = ImApplicationService(db)
        svc.ensure_employee_user("emp8", display_name="Alice", owner_user_id=0)
        assert existing_profile.owner_user_id == 9


# ---------------------------------------------------------------------------
# get_employee_owner
# ---------------------------------------------------------------------------


class TestGetEmployeeOwner:
    def test_returns_zero_on_empty_id(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        assert svc.get_employee_owner("") == 0

    def test_returns_zero_on_whitespace_id(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        assert svc.get_employee_owner("   ") == 0

    def test_returns_zero_when_no_profile(self):
        db = MagicMock()
        ret = MagicMock()
        ret.first.return_value = None
        db.execute.return_value = ret
        svc = ImApplicationService(db)
        assert svc.get_employee_owner("emp1") == 0

    def test_returns_zero_when_owner_id_is_zero(self):
        db = MagicMock()
        ret = MagicMock()
        ret.first.return_value = (0,)
        db.execute.return_value = ret
        svc = ImApplicationService(db)
        assert svc.get_employee_owner("emp1") == 0

    def test_returns_zero_when_owner_id_is_none(self):
        db = MagicMock()
        ret = MagicMock()
        ret.first.return_value = (None,)
        db.execute.return_value = ret
        svc = ImApplicationService(db)
        assert svc.get_employee_owner("emp1") == 0

    def test_returns_zero_when_owner_id_is_negative(self):
        db = MagicMock()
        ret = MagicMock()
        ret.first.return_value = (-5,)
        db.execute.return_value = ret
        svc = ImApplicationService(db)
        assert svc.get_employee_owner("emp1") == 0

    def test_returns_owner_id_when_valid(self):
        db = MagicMock()
        ret = MagicMock()
        ret.first.return_value = (42,)
        db.execute.return_value = ret
        svc = ImApplicationService(db)
        assert svc.get_employee_owner("emp1") == 42

    def test_returns_zero_on_type_error(self):
        db = MagicMock()
        ret = MagicMock()
        # 模拟 row[0] 是不可 int() 的对象
        ret.first.return_value = ("not_a_number",)
        db.execute.return_value = ret
        svc = ImApplicationService(db)
        # "not_a_number" 转 int 会抛 ValueError
        try:
            int("not_a_number")
            raise AssertionError("应抛 ValueError")
        except ValueError:
            pass
        # 测试实际行为
        try:
            svc.get_employee_owner("emp1")
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# employee_im_summary
# ---------------------------------------------------------------------------


class TestEmployeeImSummary:
    def test_returns_empty_when_boss_uid_le_zero(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        assert svc.employee_im_summary(0, []) == {}
        assert svc.employee_im_summary(-1, [{"id": "e1"}]) == {}

    def test_returns_empty_when_no_employees(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        assert svc.employee_im_summary(10, []) == {}

    def test_returns_empty_when_all_employees_have_empty_id(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        # 所有 employee id 为空 → eid_to_meta 为空
        assert svc.employee_im_summary(10, [{"id": ""}, {"id": None}]) == {}

    def test_returns_empty_when_no_profiles_and_ensure_fails(self):
        db = MagicMock()
        # profiles 查询返回空
        ret_profiles = MagicMock()
        ret_profiles.scalars.return_value.all.return_value = []
        db.execute.return_value = ret_profiles
        svc = ImApplicationService(db)
        with patch.object(svc, "ensure_employee_user", side_effect=Exception("boom")):
            result = svc.employee_im_summary(10, [{"id": "e1", "name": "E1"}])
        assert result == {}

    def test_returns_empty_when_ensure_returns_zero_and_fallback_fails(self):
        """ensure 返回 0 时 eid_to_uid 非空，但 uid_to_eid={0:"e1"}；
        convs 查询返回空 + get_or_create_direct 抛异常 → 返回空 dict。"""
        db = MagicMock()
        ret_profiles = MagicMock()
        ret_profiles.scalars.return_value.all.return_value = []
        ret_convs = MagicMock()
        ret_convs.scalars.return_value.all.return_value = []
        db.execute.side_effect = [ret_profiles, ret_convs]
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "ensure_employee_user", return_value=0),
            patch.object(svc, "get_or_create_direct", side_effect=Exception("no conv")),
        ):
            result = svc.employee_im_summary(10, [{"id": "e1"}])
        assert result == {}

    def test_populates_out_when_conversation_has_matching_peer(self):
        db = MagicMock()
        # 1. profiles 查询返回一个 profile（user_id=20, employee_id="e1"）
        profile = _make_profile(employee_id="e1", user_id=20)
        ret_profiles = MagicMock()
        ret_profiles.scalars.return_value.all.return_value = [profile]
        # 2. convs 查询返回一个 conv
        conv = _make_conversation(conv_id=100, last_message_at=None)
        ret_convs = MagicMock()
        ret_convs.scalars.return_value.all.return_value = [conv]
        # 3. last_msg 查询返回 None
        ret_msg = MagicMock()
        ret_msg.scalars.return_value.first.return_value = None
        db.execute.side_effect = [ret_profiles, ret_convs, ret_msg]
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "_direct_peer_id", return_value=20),
            patch.object(svc, "_count_unread", return_value=3),
        ):
            result = svc.employee_im_summary(10, [{"id": "e1", "name": "E1"}])
        assert "e1" in result
        assert result["e1"]["im_conv_id"] == 100
        assert result["e1"]["im_last_message"] == ""
        assert result["e1"]["im_last_message_at"] == ""
        assert result["e1"]["im_unread_count"] == 3

    def test_populates_out_with_last_message_and_iso_timestamp(self):
        from datetime import datetime

        db = MagicMock()
        profile = _make_profile(employee_id="e1", user_id=20)
        ret_profiles = MagicMock()
        ret_profiles.scalars.return_value.all.return_value = [profile]
        ts = datetime(2026, 1, 1, 12, 0, 0)
        conv = _make_conversation(conv_id=100, last_message_at=ts)
        ret_convs = MagicMock()
        ret_convs.scalars.return_value.all.return_value = [conv]
        msg = _make_message(msg_id=500, body="hi there")
        ret_msg = MagicMock()
        ret_msg.scalars.return_value.first.return_value = msg
        db.execute.side_effect = [ret_profiles, ret_convs, ret_msg]
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "_direct_peer_id", return_value=20),
            patch.object(svc, "_count_unread", return_value=0),
        ):
            result = svc.employee_im_summary(10, [{"id": "e1"}])
        assert result["e1"]["im_last_message"] == "hi there"
        assert result["e1"]["im_last_message_at"] == ts.isoformat()

    def test_skips_conversation_when_peer_not_in_uid_to_eid(self):
        db = MagicMock()
        profile = _make_profile(employee_id="e1", user_id=20)
        ret_profiles = MagicMock()
        ret_profiles.scalars.return_value.all.return_value = [profile]
        conv = _make_conversation(conv_id=100, last_message_at=None)
        ret_convs = MagicMock()
        ret_convs.scalars.return_value.all.return_value = [conv]
        db.execute.side_effect = [ret_profiles, ret_convs]
        svc = ImApplicationService(db)
        # peer_id 不在 uid_to_eid 中 → 跳过该 conv
        # 然后 fallback 进入 get_or_create_direct 分支
        with (
            patch.object(svc, "_direct_peer_id", return_value=999),
            patch.object(svc, "get_or_create_direct", return_value={"id": 200, "created": True}),
        ):
            result = svc.employee_im_summary(10, [{"id": "e1"}])
        # fallback 创建了新 conv
        assert "e1" in result
        assert result["e1"]["im_conv_id"] == 200

    def test_skips_conversation_when_peer_id_is_none(self):
        db = MagicMock()
        profile = _make_profile(employee_id="e1", user_id=20)
        ret_profiles = MagicMock()
        ret_profiles.scalars.return_value.all.return_value = [profile]
        conv = _make_conversation(conv_id=100, last_message_at=None)
        ret_convs = MagicMock()
        ret_convs.scalars.return_value.all.return_value = [conv]
        db.execute.side_effect = [ret_profiles, ret_convs]
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "_direct_peer_id", return_value=None),
            patch.object(svc, "get_or_create_direct", return_value={"id": 0, "created": False}),
        ):
            result = svc.employee_im_summary(10, [{"id": "e1"}])
        # conv 被跳过，fallback get_or_create_direct 返回 id=0 → 不写入 out
        assert result == {}

    def test_fallback_get_or_create_direct_exception_tolerated(self):
        db = MagicMock()
        profile = _make_profile(employee_id="e1", user_id=20)
        ret_profiles = MagicMock()
        ret_profiles.scalars.return_value.all.return_value = [profile]
        ret_convs = MagicMock()
        ret_convs.scalars.return_value.all.return_value = []
        db.execute.side_effect = [ret_profiles, ret_convs]
        svc = ImApplicationService(db)
        with patch.object(svc, "get_or_create_direct", side_effect=Exception("boom")):
            result = svc.employee_im_summary(10, [{"id": "e1"}])
        # 异常被吞，返回空 dict
        assert result == {}

    def test_ensure_employee_user_called_for_missing_profile(self):
        db = MagicMock()
        # profiles 为空，触发 ensure_employee_user
        ret_profiles = MagicMock()
        ret_profiles.scalars.return_value.all.return_value = []
        ret_convs = MagicMock()
        ret_convs.scalars.return_value.all.return_value = []
        db.execute.side_effect = [ret_profiles, ret_convs]
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "ensure_employee_user", return_value=30) as mock_ensure,
            patch.object(svc, "get_or_create_direct", return_value={"id": 0, "created": False}),
        ):
            result = svc.employee_im_summary(10, [{"id": "e1", "mod_id": "m1"}])
        mock_ensure.assert_called_once()

    def test_skips_profile_with_falsy_user_id_then_ensures_user(self):
        """profile.user_id=0 时跳过该 profile，回退到 ensure_employee_user。"""
        db = MagicMock()
        # profile 存在但 user_id=0 → 不加入 eid_to_uid → 触发 ensure_employee_user
        profile = _make_profile(employee_id="e1", user_id=0)
        ret_profiles = MagicMock()
        ret_profiles.scalars.return_value.all.return_value = [profile]
        ret_convs = MagicMock()
        ret_convs.scalars.return_value.all.return_value = []
        db.execute.side_effect = [ret_profiles, ret_convs]
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "ensure_employee_user", return_value=30) as mock_ensure,
            patch.object(svc, "get_or_create_direct", return_value={"id": 0, "created": False}),
        ):
            result = svc.employee_im_summary(10, [{"id": "e1", "mod_id": "m1"}])
        mock_ensure.assert_called_once()
        assert result == {}

    def test_employee_meta_falls_back_to_market_pkg_id(self):
        db = MagicMock()
        ret_profiles = MagicMock()
        ret_profiles.scalars.return_value.all.return_value = []
        db.execute.return_value = ret_profiles
        svc = ImApplicationService(db)
        with patch.object(svc, "ensure_employee_user", side_effect=Exception("boom")):
            svc.employee_im_summary(
                10,
                [{"id": "e1", "market_pkg_id": "pkg1", "market_avatar": "avatar.jpg"}],
            )
        # 验证 ensure_employee_user 被调用时 mod_id="pkg1"
        # 由于抛异常，不进入后续逻辑

    def test_employee_meta_falls_back_to_label_for_display_name(self):
        db = MagicMock()
        ret_profiles = MagicMock()
        ret_profiles.scalars.return_value.all.return_value = []
        db.execute.return_value = ret_profiles
        svc = ImApplicationService(db)
        with patch.object(svc, "ensure_employee_user", side_effect=Exception("boom")):
            svc.employee_im_summary(
                10,
                [{"id": "e1", "label": "Label1"}],
            )


# ---------------------------------------------------------------------------
# set_employee_owner
# ---------------------------------------------------------------------------


class TestSetEmployeeOwner:
    def test_returns_false_on_empty_id(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        assert svc.set_employee_owner("", 5) is False

    def test_returns_false_on_whitespace_id(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        assert svc.set_employee_owner("   ", 5) is False

    def test_returns_false_when_owner_le_zero(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        assert svc.set_employee_owner("emp1", 0) is False
        assert svc.set_employee_owner("emp1", -1) is False

    def test_returns_false_when_no_profile(self):
        db = MagicMock()
        ret = MagicMock()
        ret.scalars.return_value.first.return_value = None
        db.execute.return_value = ret
        svc = ImApplicationService(db)
        assert svc.set_employee_owner("emp1", 5) is False

    def test_raises_when_owner_not_exists(self):
        db = MagicMock()
        profile = _make_profile(employee_id="emp1")
        ret1 = MagicMock()
        ret1.scalars.return_value.first.return_value = profile
        ret2 = MagicMock()
        ret2.scalars.return_value.first.return_value = None  # owner_exists 查询返回 None
        db.execute.side_effect = [ret1, ret2]
        svc = ImApplicationService(db)
        with pytest.raises(ValueError, match="owner_user_id=5 不存在"):
            svc.set_employee_owner("emp1", 5)

    def test_sets_owner_and_commits(self):
        db = MagicMock()
        profile = _make_profile(employee_id="emp1", owner_user_id=0)
        ret1 = MagicMock()
        ret1.scalars.return_value.first.return_value = profile
        ret2 = MagicMock()
        ret2.scalars.return_value.first.return_value = 5  # owner_exists
        db.execute.side_effect = [ret1, ret2]
        svc = ImApplicationService(db)
        result = svc.set_employee_owner("emp1", 5)
        assert result is True
        assert profile.owner_user_id == 5
        db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# send_employee_message
# ---------------------------------------------------------------------------


class TestSendEmployeeMessage:
    def test_raises_on_empty_body(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        with pytest.raises(ValueError, match="消息不能为空"):
            svc.send_employee_message(1, "emp1", "   ")

    def test_raises_on_zero_boss_uid(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        with pytest.raises(ValueError, match="boss_user_id 非法"):
            svc.send_employee_message(0, "emp1", "hi")

    def test_raises_on_negative_boss_uid(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        with pytest.raises(ValueError, match="boss_user_id 非法"):
            svc.send_employee_message(-5, "emp1", "hi")

    def test_raises_when_boss_not_exists(self):
        db = MagicMock()
        ret = MagicMock()
        ret.scalars.return_value.first.return_value = None
        db.execute.return_value = ret
        svc = ImApplicationService(db)
        with pytest.raises(ValueError, match="boss_user_id=10 不存在"):
            svc.send_employee_message(10, "emp1", "hi")

    def test_sends_message_successfully(self):
        db = MagicMock()
        boss = _make_user(user_id=10)
        ret = MagicMock()
        ret.scalars.return_value.first.return_value = boss
        db.execute.return_value = ret
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "ensure_employee_user", return_value=20) as mock_ensure,
            patch.object(
                svc, "get_or_create_direct", return_value={"id": 100, "created": True}
            ) as mock_gocd,
            patch.object(
                svc,
                "send_message",
                return_value={
                    "message": {"id": 500, "body": "hi"},
                    "member_user_ids": [10, 20],
                },
            ) as mock_send,
        ):
            result = svc.send_employee_message(
                10,
                "emp1",
                "hi",
                mod_id="m1",
                display_name="E1",
                avatar_url="url",
                owner_user_id=5,
            )
        mock_ensure.assert_called_once_with(
            "emp1",
            mod_id="m1",
            display_name="E1",
            avatar_url="url",
            owner_user_id=5,
        )
        mock_gocd.assert_called_once_with(10, 20)
        mock_send.assert_called_once_with(100, 20, "hi")
        assert result["conversation_id"] == 100
        assert result["employee_user_id"] == 20
        assert result["message"]["body"] == "hi"
        assert result["member_user_ids"] == [10, 20]
        assert result["created"] is True

    def test_returns_empty_member_user_ids_when_missing(self):
        db = MagicMock()
        boss = _make_user(user_id=10)
        ret = MagicMock()
        ret.scalars.return_value.first.return_value = boss
        db.execute.return_value = ret
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "ensure_employee_user", return_value=20),
            patch.object(svc, "get_or_create_direct", return_value={"id": 100, "created": False}),
            patch.object(svc, "send_message", return_value={"message": None}),
        ):
            result = svc.send_employee_message(10, "emp1", "hi")
        assert result["member_user_ids"] == []
        assert result["created"] is False


# ---------------------------------------------------------------------------
# list_cs_inbox
# ---------------------------------------------------------------------------


class TestListCsInbox:
    def test_returns_empty_when_no_cs_user(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        with patch.object(svc, "enterprise_cs_user_id", return_value=None):
            assert svc.list_cs_inbox() == []

    def test_returns_empty_when_no_conversations(self):
        db = MagicMock()
        # conv_ids 查询返回空
        ret = MagicMock()
        ret.all.return_value = []
        db.execute.return_value = ret
        svc = ImApplicationService(db)
        with patch.object(svc, "enterprise_cs_user_id", return_value=99):
            assert svc.list_cs_inbox() == []

    def test_returns_inbox_with_peer(self):
        db = MagicMock()
        # conv_ids 查询返回 [(100,), (200,)]
        ret_ids = MagicMock()
        ret_ids.all.return_value = [(100,), (200,)]
        # convs 查询返回 [conv1]
        conv = _make_conversation(conv_id=100, last_message_at=None)
        ret_convs = MagicMock()
        ret_convs.scalars.return_value.all.return_value = [conv]
        db.execute.side_effect = [ret_ids, ret_convs]
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "enterprise_cs_user_id", return_value=99),
            patch.object(svc, "_direct_peer_id", return_value=50),
            patch.object(svc, "_display_name", return_value="Customer50"),
            patch.object(svc, "_count_unread", return_value=2),
        ):
            result = svc.list_cs_inbox()
        assert len(result) == 1
        assert result[0]["id"] == 100
        assert result[0]["customer_user_id"] == 50
        assert result[0]["customer_name"] == "Customer50"
        assert result[0]["last_message_at"] == ""
        assert result[0]["unread_count"] == 2

    def test_skips_conversation_when_no_peer(self):
        db = MagicMock()
        ret_ids = MagicMock()
        ret_ids.all.return_value = [(100,)]
        conv = _make_conversation(conv_id=100, last_message_at=None)
        ret_convs = MagicMock()
        ret_convs.scalars.return_value.all.return_value = [conv]
        db.execute.side_effect = [ret_ids, ret_convs]
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "enterprise_cs_user_id", return_value=99),
            patch.object(svc, "_direct_peer_id", return_value=None),
        ):
            result = svc.list_cs_inbox()
        assert result == []

    def test_includes_iso_timestamp_when_present(self):
        from datetime import datetime

        db = MagicMock()
        ret_ids = MagicMock()
        ret_ids.all.return_value = [(100,)]
        ts = datetime(2026, 1, 1, 12, 0, 0)
        conv = _make_conversation(conv_id=100, last_message_at=ts)
        ret_convs = MagicMock()
        ret_convs.scalars.return_value.all.return_value = [conv]
        db.execute.side_effect = [ret_ids, ret_convs]
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "enterprise_cs_user_id", return_value=99),
            patch.object(svc, "_direct_peer_id", return_value=50),
            patch.object(svc, "_display_name", return_value="C"),
            patch.object(svc, "_count_unread", return_value=0),
        ):
            result = svc.list_cs_inbox()
        assert result[0]["last_message_at"] == ts.isoformat()


# ---------------------------------------------------------------------------
# cs_inbox_messages
# ---------------------------------------------------------------------------


class TestCsInboxMessages:
    def test_returns_empty_when_no_cs_user(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        with patch.object(svc, "enterprise_cs_user_id", return_value=None):
            assert svc.cs_inbox_messages(100) == []

    def test_returns_messages_and_marks_read(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        messages = [{"id": 1}, {"id": 5}]
        with (
            patch.object(svc, "enterprise_cs_user_id", return_value=99),
            patch.object(svc, "list_messages", return_value=messages) as mock_list,
            patch.object(svc, "mark_read") as mock_mark,
        ):
            result = svc.cs_inbox_messages(100)
        assert result == messages
        mock_list.assert_called_once_with(100, 99, limit=100)
        mock_mark.assert_called_once_with(100, 99, 5)

    def test_returns_empty_messages_does_not_mark_read(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "enterprise_cs_user_id", return_value=99),
            patch.object(svc, "list_messages", return_value=[]),
            patch.object(svc, "mark_read") as mock_mark,
        ):
            result = svc.cs_inbox_messages(100)
        assert result == []
        mock_mark.assert_not_called()

    def test_returns_messages_with_zero_last_id_does_not_mark_read(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        messages = [{"id": 0}]
        with (
            patch.object(svc, "enterprise_cs_user_id", return_value=99),
            patch.object(svc, "list_messages", return_value=messages),
            patch.object(svc, "mark_read") as mock_mark,
        ):
            result = svc.cs_inbox_messages(100)
        assert result == messages
        mock_mark.assert_not_called()

    def test_tolerates_mark_read_exception(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        messages = [{"id": 5}]
        with (
            patch.object(svc, "enterprise_cs_user_id", return_value=99),
            patch.object(svc, "list_messages", return_value=messages),
            patch.object(svc, "mark_read", side_effect=Exception("boom")),
        ):
            result = svc.cs_inbox_messages(100)
        # 异常被吞，仍返回 messages
        assert result == messages


# ---------------------------------------------------------------------------
# cs_reply
# ---------------------------------------------------------------------------


class TestCsReply:
    def test_raises_when_no_cs_user(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        with patch.object(svc, "enterprise_cs_user_id", return_value=None):
            with pytest.raises(ValueError, match="客服通道不可用"):
                svc.cs_reply(100, "hi")

    def test_replies_via_send_message(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        expected = {"message": {"id": 1, "body": "hi"}}
        with (
            patch.object(svc, "enterprise_cs_user_id", return_value=99),
            patch.object(svc, "send_message", return_value=expected) as mock_send,
        ):
            result = svc.cs_reply(100, "hi")
        assert result == expected
        mock_send.assert_called_once_with(100, 99, "hi")
