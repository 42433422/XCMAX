from __future__ import annotations

from pathlib import Path

import pytest

from app.application.ai_group_chat_service import AiGroupChatService
from app.domain.enterprise_org_layers import resolve_enterprise_org_layer


def fake_departments() -> dict[str, dict[str, str]]:
    return {
        "ops_acquisition": {"label": "O-A 获客部"},
        "ops_partner": {"label": "O-B 伙伴部"},
        "prod_web": {"label": "P-W 网站部"},
        "prod_mod": {"label": "P-M Mod 部"},
        "prod_software": {"label": "P-S 软件部"},
        "shared_retention": {"label": "S-R 归档部"},
    }


def fake_enterprise_departments() -> dict[str, dict[str, str]]:
    return {
        "tools": {"label": "工具层"},
        "execution": {"label": "执行层"},
        "service": {"label": "服务层"},
        "management": {"label": "管理层"},
    }


def make_completion(seen: list[dict] | None = None):
    async def completion(messages):
        if seen is not None:
            seen.append({"system": messages[0]["content"], "user": messages[1]["content"]})
        # 回声出系统提示里的成员身份，便于断言"谁在回复"。
        system = messages[0]["content"]
        who = system.split("「", 2)[2].split("」", 1)[0] if system.count("「") >= 2 else "AI"
        return {"success": True, "content": f"{who} 收到", "error": ""}

    return completion


def make_service(
    tmp_path: Path, seen: list[dict] | None = None, employees=None, mode: str = "admin"
) -> AiGroupChatService:
    return AiGroupChatService(
        storage_root=tmp_path,
        completion_fn=make_completion(seen),
        department_loader=fake_enterprise_departments if mode == "enterprise" else fake_departments,
        employee_loader=(employees if callable(employees) else (lambda: employees or [])),
        mode=mode,
    )


def test_seeds_six_department_groups(tmp_path: Path):
    svc = make_service(tmp_path)
    groups = svc.list_groups(user_id=1)
    assert len(groups) == 6
    names = [g["name"] for g in groups]
    assert "O-A 获客部" in names
    assert all(g["member_count"] == 0 for g in groups)
    # 幂等：再次 list 不会重复种。
    assert len(svc.list_groups(user_id=1)) == 6


def test_groups_are_user_scoped(tmp_path: Path):
    svc = make_service(tmp_path)
    svc.list_groups(user_id=1)
    svc.list_groups(user_id=2)
    assert len(svc.list_groups(user_id=1)) == 6
    assert len(svc.list_groups(user_id=2)) == 6


def test_add_and_remove_member(tmp_path: Path):
    svc = make_service(tmp_path)
    gid = svc.list_groups(user_id=1)[0]["id"]
    g = svc.add_member(
        user_id=1,
        group_id=gid,
        member={"employee_id": "e1", "mod_id": "m1", "name": "小销", "summary": "负责获客"},
    )
    assert g["member_count"] == 1
    # 幂等去重
    g = svc.add_member(user_id=1, group_id=gid, member={"employee_id": "e1", "name": "小销"})
    assert g["member_count"] == 1
    g = svc.remove_member(user_id=1, group_id=gid, employee_id="e1")
    assert g["member_count"] == 0


@pytest.mark.asyncio
async def test_post_message_all_members_reply(tmp_path: Path):
    seen: list[dict] = []
    svc = make_service(tmp_path, seen)
    gid = svc.list_groups(user_id=1)[0]["id"]
    svc.add_member(user_id=1, group_id=gid, member={"employee_id": "e1", "name": "小销"})
    svc.add_member(user_id=1, group_id=gid, member={"employee_id": "e2", "name": "小服"})

    result = await svc.post_message(user_id=1, group_id=gid, text="今天有什么进展？")

    # 1 条用户消息 + 2 条 AI 回复
    roles = [m["role"] for m in result["messages"]]
    assert roles == ["user", "ai", "ai"]
    senders = [m["sender_name"] for m in result["messages"] if m["role"] == "ai"]
    assert set(senders) == {"小销", "小服"}
    # 历史落盘
    msgs = svc.get_messages(user_id=1, group_id=gid)
    assert len(msgs) == 3


@pytest.mark.asyncio
async def test_post_message_mention_targets_one(tmp_path: Path):
    svc = make_service(tmp_path)
    gid = svc.list_groups(user_id=1)[0]["id"]
    svc.add_member(user_id=1, group_id=gid, member={"employee_id": "e1", "name": "小销"})
    svc.add_member(user_id=1, group_id=gid, member={"employee_id": "e2", "name": "小服"})

    # 显式 mentions：只有 e2 回复
    result = await svc.post_message(user_id=1, group_id=gid, text="帮忙看下", mentions=["e2"])
    ai = [m for m in result["messages"] if m["role"] == "ai"]
    assert len(ai) == 1
    assert ai[0]["sender_name"] == "小服"

    # 文本 @名字：只有 小销 回复
    result2 = await svc.post_message(user_id=1, group_id=gid, text="@小销 你怎么看")
    ai2 = [m for m in result2["messages"] if m["role"] == "ai"]
    assert len(ai2) == 1
    assert ai2[0]["sender_name"] == "小销"


@pytest.mark.asyncio
async def test_empty_group_only_stores_user_message(tmp_path: Path):
    svc = make_service(tmp_path)
    gid = svc.list_groups(user_id=1)[0]["id"]  # 无成员
    result = await svc.post_message(user_id=1, group_id=gid, text="有人吗")
    assert [m["role"] for m in result["messages"]] == ["user"]


def test_create_custom_group(tmp_path: Path):
    svc = make_service(tmp_path)
    svc.list_groups(user_id=1)
    g = svc.create_group(user_id=1, name="我的专属小队")
    assert g["name"] == "我的专属小队"
    assert len(svc.list_groups(user_id=1)) == 7


def test_seed_populates_members_by_department(tmp_path: Path):
    """种子群按编制把员工填进对应部门群。"""
    emps = [
        {
            "employee_id": "e1",
            "mod_id": "m1",
            "name": "小销",
            "summary": "获客",
            "department_key": "ops_acquisition",
        },
        {
            "employee_id": "e2",
            "mod_id": "m1",
            "name": "小伴",
            "summary": "伙伴",
            "department_key": "ops_partner",
        },
        {
            "employee_id": "e3",
            "mod_id": "m2",
            "name": "小网",
            "summary": "网站",
            "department_key": "prod_web",
        },
        {
            "employee_id": "e4",
            "mod_id": "m2",
            "name": "小软",
            "summary": "软件",
            "department_key": "prod_software",
        },
        {
            "employee_id": "e_no_dept",
            "mod_id": "m2",
            "name": "游离",
            "summary": "无部门",
            "department_key": "",
        },
    ]
    svc = make_service(tmp_path, employees=emps)
    groups = svc.list_groups(user_id=1)
    by_key = {g["department_key"]: g for g in groups}
    assert by_key["ops_acquisition"]["member_count"] == 1
    assert by_key["ops_acquisition"]["members"][0]["name"] == "小销"
    assert by_key["ops_partner"]["member_count"] == 1
    assert by_key["prod_web"]["member_count"] == 1
    assert by_key["prod_mod"]["member_count"] == 0  # 无对应员工
    # 游离员工不进任何部门群
    all_ids = {m["employee_id"] for g in groups for m in g["members"]}
    assert "e_no_dept" not in all_ids


def test_backfill_existing_empty_groups(tmp_path: Path):
    """已存在的空部门群首次访问时回填成员（仅一次，用户移人后不覆盖）。"""
    # 先用空员工建群
    svc = make_service(tmp_path, employees=[])
    groups = svc.list_groups(user_id=1)
    assert all(g["member_count"] == 0 for g in groups)

    # 换一个带员工的服务实例（模拟"员工后同步"），再次 list 应回填
    emps = [
        {
            "employee_id": "e1",
            "mod_id": "m1",
            "name": "小销",
            "summary": "获客",
            "department_key": "ops_acquisition",
        },
    ]
    svc2 = make_service(tmp_path, employees=emps)
    groups2 = svc2.list_groups(user_id=1)
    by_key = {g["department_key"]: g for g in groups2}
    assert by_key["ops_acquisition"]["member_count"] == 1

    # 用户手动移人后，再次 list 不会自动加回（members_seeded 已置 True）
    svc2.remove_member(user_id=1, group_id="dept:ops_acquisition", employee_id="e1")
    groups3 = svc2.list_groups(user_id=1)
    by_key3 = {g["department_key"]: g for g in groups3}
    assert by_key3["ops_acquisition"]["member_count"] == 0


# ── Enterprise 模式（4 部门）──


def test_enterprise_seeds_four_department_groups(tmp_path: Path):
    """enterprise 模式种出 4 个部门群（工具层/执行层/服务层/管理层）。"""
    svc = make_service(tmp_path, mode="enterprise")
    groups = svc.list_groups(user_id=1)
    assert len(groups) == 4
    names = [g["name"] for g in groups]
    assert "工具层" in names
    assert "执行层" in names
    assert "服务层" in names
    assert "管理层" in names
    assert all(g["member_count"] == 0 for g in groups)


def test_enterprise_seed_populates_members_by_layer(tmp_path: Path):
    """enterprise 模式种子群按 resolve_enterprise_org_layer 派生结果填员。"""
    emps = [
        {
            "employee_id": "label_print",
            "mod_id": "m1",
            "name": "标签打印",
            "summary": "执行",
            "department_key": resolve_enterprise_org_layer("label_print", "标签打印"),
        },
        {
            "employee_id": "wechat_msg",
            "mod_id": "m2",
            "name": "微信消息",
            "summary": "服务",
            "department_key": resolve_enterprise_org_layer("wechat_msg", "微信消息"),
        },
        {
            "employee_id": "lan_gate",
            "mod_id": "m3",
            "name": "局域网网关",
            "summary": "工具",
            "department_key": resolve_enterprise_org_layer("lan_gate", "局域网网关"),
        },
        {
            "employee_id": "workflow_automator",
            "mod_id": "m4",
            "name": "流程编排器",
            "summary": "管理",
            "department_key": resolve_enterprise_org_layer("workflow_automator", "流程编排器"),
        },
    ]
    svc = make_service(tmp_path, employees=emps, mode="enterprise")
    groups = svc.list_groups(user_id=1)
    by_key = {g["department_key"]: g for g in groups}
    assert by_key["execution"]["member_count"] == 1
    assert by_key["execution"]["members"][0]["name"] == "标签打印"
    assert by_key["service"]["member_count"] == 1
    assert by_key["tools"]["member_count"] == 1
    assert by_key["management"]["member_count"] == 1


def test_resolve_enterprise_org_layer_manifest_priority():
    """manifest enterprise_layer 优先于 ID 表和关键词。"""
    assert resolve_enterprise_org_layer("unknown_id", "未知", "", "service") == "service"
    # ID 表优先于关键词
    assert resolve_enterprise_org_layer("label_print", "标签打印") == "execution"
    # 关键词匹配（"微信客服"只命中 service 规则）
    assert resolve_enterprise_org_layer("custom_contact", "微信客服") == "service"
    # 默认归入 management
    assert resolve_enterprise_org_layer("totally_unknown", "完全未知") == "management"


def test_enterprise_groups_user_scoped(tmp_path: Path):
    """enterprise 模式群同样按用户隔离。"""
    svc = make_service(tmp_path, mode="enterprise")
    svc.list_groups(user_id=1)
    svc.list_groups(user_id=2)
    assert len(svc.list_groups(user_id=1)) == 4
    assert len(svc.list_groups(user_id=2)) == 4


@pytest.mark.asyncio
async def test_discussion_prompt_is_collaborative(tmp_path: Path):
    """群聊回复编排应是「多成员协作讨论」（参考同事发言、向可执行结论收敛），而非各说各的。"""
    seen: list[dict] = []
    svc = make_service(tmp_path, seen)
    gid = svc.create_group(user_id=1, name="讨论组")["id"]
    svc.add_member(user_id=1, group_id=gid, member={"employee_id": "e1", "name": "小销"})
    svc.add_member(user_id=1, group_id=gid, member={"employee_id": "e2", "name": "小服"})
    await svc.post_message(user_id=1, group_id=gid, text="怎么提升复购？")
    assert seen, "应至少有一次 AI 回复"
    assert all("协作讨论" in s["system"] for s in seen)
    assert any("收敛" in s["system"] for s in seen)


@pytest.mark.asyncio
async def test_execute_after_discussion_dispatches_super_employee(tmp_path: Path, monkeypatch):
    """execute=True 时，讨论后把结论综合成任务，派群里的超级员工以「任务模式」执行，结果回群。"""
    from app.application.ai_group_chat_service import AiGroupChatService

    svc = make_service(tmp_path)
    gid = svc.create_group(user_id=1, name="执行组")["id"]
    svc.add_member(user_id=1, group_id=gid, member={"employee_id": "e1", "name": "小销"})
    svc.add_member(
        user_id=1,
        group_id=gid,
        member={"employee_id": "claude-super-employee", "name": "超级员工-Claude"},
    )

    # 讨论阶段：超员回复打桩，避免真跑 CLI。
    async def fake_super_reply(self, group, member, history, *, user_id):
        return "超级员工-Claude：建议先改复购页文案"

    monkeypatch.setattr(AiGroupChatService, "_super_employee_reply", fake_super_reply)

    # 执行阶段：打桩服务，捕获 invoke 入参。
    captured: dict = {}

    class FakeService:
        def invoke(self, *, user_id, message, context):
            captured["message"] = message
            captured["context"] = context
            return {"status": "completed", "assistant_message": {"body": "已完成：改了复购页文案"}}

    monkeypatch.setattr(
        AiGroupChatService, "_super_service", staticmethod(lambda eid: FakeService())
    )

    result = await svc.post_message(user_id=1, group_id=gid, text="实现复购优化", execute=True)
    bodies = [m["body"] for m in result["messages"]]
    # 末条=执行结果，来自超级员工。
    assert any("已完成：改了复购页文案" in b for b in bodies)
    # 用的是任务模式（不是 mode=chat），且 brief 带上了讨论要点。
    assert captured["context"].get("mode") != "chat"
    assert "讨论要点" in captured["message"]
    assert "实现复购优化" in captured["message"]


@pytest.mark.asyncio
async def test_execute_noop_when_no_super_employee(tmp_path: Path):
    """群里没有超级员工时，execute=True 不产生执行消息（只有讨论）。"""
    svc = make_service(tmp_path)
    gid = svc.create_group(user_id=1, name="无超员组")["id"]
    svc.add_member(user_id=1, group_id=gid, member={"employee_id": "e1", "name": "小销"})
    result = await svc.post_message(user_id=1, group_id=gid, text="做个表", execute=True)
    # 仅 用户消息 + 1 条讨论回复，无执行结果。
    assert len(result["messages"]) == 2
