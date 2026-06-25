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


# ── 群成员候选（普通员工 + 超级员工）──


def test_list_member_candidates_marks_super(tmp_path: Path):
    """候选列表带 is_super 标志，超级员工被标记，便于手机端打徽标。"""
    emps = [
        {
            "employee_id": "e1",
            "mod_id": "m1",
            "name": "小销",
            "summary": "获客",
            "department_key": "ops_acquisition",
        },
        {
            "employee_id": "codex-super-employee",
            "mod_id": "super-employee",
            "name": "超级员工-Codex",
            "summary": "CLI 直答",
            "department_key": "",
        },
    ]
    svc = make_service(tmp_path, employees=emps)
    cands = svc.list_member_candidates()
    by_id = {c["employee_id"]: c for c in cands}
    assert by_id["e1"]["is_super"] is False
    assert by_id["codex-super-employee"]["is_super"] is True
    assert by_id["codex-super-employee"]["mod_id"] == "super-employee"


def test_list_member_candidates_dedups(tmp_path: Path):
    """同一 employee_id 去重，避免前端列表 key 冲突。"""
    emps = [
        {"employee_id": "e1", "name": "A"},
        {"employee_id": "e1", "name": "B"},
        {"employee_id": "", "name": "空 id 跳过"},
    ]
    svc = make_service(tmp_path, employees=emps)
    cands = svc.list_member_candidates()
    assert [c["employee_id"] for c in cands] == ["e1"]


def test_append_super_employees_adds_codex_claude():
    """_append_super_employees 把 Codex/Claude 追加进候选，保证手机端能把超级员工拉进群。"""
    from app.application.ai_group_chat_service import _append_super_employees

    emps: list[dict] = []
    _append_super_employees(emps)
    ids = {e["employee_id"] for e in emps}
    assert "codex-super-employee" in ids
    assert "claude-super-employee" in ids
    # 统一标 mod_id=super-employee，后端据此路由到 _super_employee_reply。
    assert all(e["mod_id"] == "super-employee" for e in emps)
