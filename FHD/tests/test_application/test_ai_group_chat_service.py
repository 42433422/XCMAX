from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import app.application.ai_group_chat_service as group_chat_module
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
    tmp_path: Path,
    seen: list[dict] | None = None,
    employees=None,
    mode: str = "admin",
    executor=None,
) -> AiGroupChatService:
    return AiGroupChatService(
        storage_root=tmp_path,
        completion_fn=make_completion(seen),
        employee_executor_fn=executor,
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
    assert all(g["member_count"] == 1 for g in groups)
    assert all(g["members"][0]["employee_id"] == "xcagi-assistant" for g in groups)
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
    assert g["member_count"] == 2
    # 幂等去重
    g = svc.add_member(user_id=1, group_id=gid, member={"employee_id": "e1", "name": "小销"})
    assert g["member_count"] == 2
    g = svc.remove_member(user_id=1, group_id=gid, employee_id="e1")
    assert g["member_count"] == 1
    g = svc.remove_member(user_id=1, group_id=gid, employee_id="xcagi-assistant")
    assert g["member_count"] == 1


@pytest.mark.asyncio
async def test_post_message_defaults_to_xiaoc_reception(tmp_path: Path):
    seen: list[dict] = []
    svc = make_service(tmp_path, seen)
    gid = svc.list_groups(user_id=1)[0]["id"]
    svc.add_member(user_id=1, group_id=gid, member={"employee_id": "e1", "name": "小销"})
    svc.add_member(user_id=1, group_id=gid, member={"employee_id": "e2", "name": "小服"})

    result = await svc.post_message(user_id=1, group_id=gid, text="今天有什么进展？")

    # 真实工作群默认先由小C接待，避免一条普通消息刷出全员回复。
    roles = [m["role"] for m in result["messages"]]
    assert roles == ["user", "ai"]
    senders = [m["sender_name"] for m in result["messages"] if m["role"] == "ai"]
    assert senders == ["小C助理"]
    # 历史落盘
    msgs = svc.get_messages(user_id=1, group_id=gid)
    assert len(msgs) == 2


@pytest.mark.asyncio
async def test_post_message_broadcast_mention_reaches_group_members(tmp_path: Path):
    svc = make_service(tmp_path)
    gid = svc.list_groups(user_id=1)[0]["id"]
    svc.add_member(user_id=1, group_id=gid, member={"employee_id": "e1", "name": "小销"})
    svc.add_member(user_id=1, group_id=gid, member={"employee_id": "e2", "name": "小服"})

    result = await svc.post_message(user_id=1, group_id=gid, text="@所有人 今天有什么进展？")

    roles = [m["role"] for m in result["messages"]]
    assert roles == ["user", "ai", "ai", "ai"]
    senders = [m["sender_name"] for m in result["messages"] if m["role"] == "ai"]
    assert set(senders) == {"小C助理", "小销", "小服"}


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
async def test_empty_group_has_xiaoc_reply(tmp_path: Path):
    svc = make_service(tmp_path)
    gid = svc.list_groups(user_id=1)[0]["id"]
    result = await svc.post_message(user_id=1, group_id=gid, text="有人吗")
    assert [m["role"] for m in result["messages"]] == ["user", "ai"]
    assert result["messages"][1]["sender_id"] == "xcagi-assistant"


@pytest.mark.asyncio
async def test_delete_own_group_message_only_removes_user_message(tmp_path: Path):
    svc = make_service(tmp_path)
    gid = svc.list_groups(user_id=1)[0]["id"]
    result = await svc.post_message(user_id=1, group_id=gid, text="这条等下删除")
    user_message = result["messages"][0]
    ai_message = result["messages"][1]

    deleted = svc.delete_message(user_id=1, group_id=gid, message_id=user_message["id"])

    assert deleted == {"deleted": True, "id": user_message["id"]}
    messages = svc.get_messages(user_id=1, group_id=gid)
    assert [m["id"] for m in messages] == [ai_message["id"]]


@pytest.mark.asyncio
async def test_delete_group_message_rejects_ai_message(tmp_path: Path):
    svc = make_service(tmp_path)
    gid = svc.list_groups(user_id=1)[0]["id"]
    result = await svc.post_message(user_id=1, group_id=gid, text="AI 回复不能删")
    ai_message = result["messages"][1]

    with pytest.raises(ValueError, match="只能删除自己发送的消息"):
        svc.delete_message(user_id=1, group_id=gid, message_id=ai_message["id"])


@pytest.mark.asyncio
async def test_dispatch_message_creates_work_order_and_reports(tmp_path: Path):
    calls: list[dict] = []

    def executor(employee_id: str, task: str, input_data: dict, user_id: int):
        calls.append(
            {
                "employee_id": employee_id,
                "task": task,
                "input_data": input_data,
                "user_id": user_id,
            }
        )
        return {"success": True, "summary": f"{employee_id} 已完成"}

    svc = make_service(tmp_path, executor=executor)
    gid = svc.list_groups(user_id=7)[0]["id"]
    svc.add_member(user_id=7, group_id=gid, member={"employee_id": "e1", "name": "小销"})
    svc.add_member(user_id=7, group_id=gid, member={"employee_id": "e2", "name": "小服"})

    result = await svc.post_message(
        user_id=7,
        group_id=gid,
        text="整理本周客户转化数据",
        dispatch=True,
        branch_context="mobile-group/clean-test",
    )

    assert [c["employee_id"] for c in calls] == ["e1", "e2"]
    assert all(c["task"] == "整理本周客户转化数据" for c in calls)
    assert all(c["user_id"] == 7 for c in calls)
    assert all(c["input_data"]["invoke_mode"] == "group_dispatch" for c in calls)
    assert all(c["input_data"]["branch"] == "mobile-group/clean-test" for c in calls)
    assert [m.get("kind") for m in result["messages"]] == [
        None,
        "work_order",
        "work_report",
        "work_report",
    ]
    work_order = next(m for m in result["messages"] if m.get("kind") == "work_order")
    assert work_order["payload"]["branch_context"] == "mobile-group/clean-test"
    assert "工作分支：mobile-group/clean-test" in work_order["body"]
    reports = [m for m in result["messages"] if m.get("kind") == "work_report"]
    assert {m["sender_id"] for m in reports} == {"e1", "e2"}
    assert all("执行汇报" in m["body"] for m in reports)
    assert all("分支：mobile-group/clean-test" in m["body"] for m in reports)
    assert all("风险：" in m["body"] for m in reports)
    assert len(result["work_orders"]) == 2
    assert len(svc.get_messages(user_id=7, group_id=gid)) == 4


@pytest.mark.asyncio
async def test_dispatch_mention_targets_one_employee_point_to_point(tmp_path: Path):
    calls: list[str] = []

    def executor(employee_id: str, task: str, input_data: dict, user_id: int):
        calls.append(employee_id)
        return {"success": True, "message": f"{employee_id} done"}

    svc = make_service(tmp_path, executor=executor)
    gid = svc.list_groups(user_id=1)[0]["id"]
    employees = [
        {"employee_id": "sales", "name": "销售"},
        {"employee_id": "service", "name": "客服"},
        {"employee_id": "ops", "name": "运营"},
    ]
    for member in employees:
        svc.add_member(user_id=1, group_id=gid, member=member)

    for member in employees:
        calls.clear()
        result = await svc.post_message(
            user_id=1,
            group_id=gid,
            text=f"@{member['name']} 点对点测试：回报你的执行结果",
            mentions=[member["employee_id"]],
            dispatch=True,
        )
        assert calls == [member["employee_id"]]
        reports = [m for m in result["messages"] if m.get("kind") == "work_report"]
        assert len(reports) == 1
        assert reports[0]["sender_id"] == member["employee_id"]


@pytest.mark.asyncio
async def test_dispatch_failure_reports_without_blocking_other_employees(tmp_path: Path):
    def executor(employee_id: str, task: str, input_data: dict, user_id: int):
        if employee_id == "bad":
            raise RuntimeError("工具不可用")
        return {"success": True, "summary": "已处理"}

    svc = make_service(tmp_path, executor=executor)
    gid = svc.list_groups(user_id=1)[0]["id"]
    svc.add_member(user_id=1, group_id=gid, member={"employee_id": "bad", "name": "失败员工"})
    svc.add_member(user_id=1, group_id=gid, member={"employee_id": "ok", "name": "正常员工"})

    result = await svc.post_message(user_id=1, group_id=gid, text="执行回归测试", dispatch=True)

    reports = [m for m in result["messages"] if m.get("kind") == "work_report"]
    by_sender = {m["sender_id"]: m for m in reports}
    assert by_sender["bad"]["status"] == "failed"
    assert "工具不可用" in by_sender["bad"]["body"]
    assert by_sender["ok"]["status"] == "done"
    assert "已处理" in by_sender["ok"]["body"]


@pytest.mark.asyncio
async def test_super_development_group_discusses_routes_then_dispatches(tmp_path: Path):
    completion_calls: list[dict[str, str]] = []

    async def completion(messages):
        system = messages[0]["content"]
        user = messages[1]["content"]
        completion_calls.append({"system": system, "user": user})
        if "群聊工作流调度器" in system:
            return {
                "success": True,
                "content": (
                    '{"target_employee_ids":["cursor-super-employee","codex-super-employee"],'
                    '"rationale":"顶部输入框是移动端 UI 改动，Cursor 主改，Codex 补测试。"}'
                ),
                "error": "",
            }
        name = system.split("「")[-1].split("」", 1)[0]
        return {
            "success": True,
            "content": f"{name}：先确认范围，再分流执行。",
            "error": "",
        }

    calls: list[dict] = []

    def executor(employee_id: str, task: str, input_data: dict, user_id: int):
        calls.append(
            {
                "employee_id": employee_id,
                "task": task,
                "input_data": input_data,
                "user_id": user_id,
            }
        )
        return {"success": True, "summary": f"{employee_id} 已接单"}

    svc = AiGroupChatService(
        storage_root=tmp_path,
        completion_fn=completion,
        employee_executor_fn=executor,
        department_loader=fake_departments,
        employee_loader=lambda: [],
    )
    group = svc.create_group(user_id=9, name="超级开发部")
    for member in [
        {"employee_id": "codex-super-employee", "mod_id": "super-employee", "name": "超级员工-Codex"},
        {"employee_id": "cursor-super-employee", "mod_id": "super-employee", "name": "超级员工-Cursor"},
        {"employee_id": "claude-super-employee", "mod_id": "super-employee", "name": "超级员工-Claude"},
    ]:
        svc.add_member(user_id=9, group_id=group["id"], member=member)

    result = await svc.post_message(
        user_id=9,
        group_id=group["id"],
        text="全链路优化发起群聊的顶部输入框、后端状态和验收反馈，多个模块需要分工",
        dispatch=True,
    )

    kinds = [m.get("kind") for m in result["messages"]]
    assert kinds == [
        None,
        "discussion",
        "discussion",
        "discussion",
        "discussion",
        "routing_decision",
        "work_order",
        "work_report",
        "work_report",
    ]
    discussion = [m for m in result["messages"] if m.get("kind") == "discussion"]
    assert discussion[0]["sender_id"] == "xcagi-assistant"
    assert discussion[0]["payload"]["phase"] == "pre_dispatch_assessment"
    assert "小C先评估，再选负责人" in discussion[0]["body"]
    assert {m["sender_id"] for m in discussion} == {
        "xcagi-assistant",
        "codex-super-employee",
        "cursor-super-employee",
        "claude-super-employee",
    }
    assert all(int(m["payload"]["round"]) <= 2 for m in discussion)
    assert any("我判断这是" in m["body"] and "建议" in m["body"] for m in discussion[1:])
    assert any("不要调用 CLI" in call["system"] for call in completion_calls)
    assert [c["employee_id"] for c in calls] == [
        "cursor-super-employee",
        "codex-super-employee",
    ]
    assert "移动端体验" in calls[0]["task"]
    assert "服务端链路" in calls[1]["task"]
    assert all("原始需求：全链路优化发起群聊的顶部输入框、后端状态和验收反馈，多个模块需要分工" in c["task"] for c in calls)
    assert calls[0]["input_data"]["assigned_task"] == calls[0]["task"]
    assert calls[1]["input_data"]["assigned_task"] == calls[1]["task"]
    assert calls[0]["input_data"]["assignment_focus"] != calls[1]["input_data"]["assignment_focus"]
    assert all(c["input_data"]["invoke_mode"] == "group_dispatch" for c in calls)
    routing = [m for m in result["messages"] if m.get("kind") == "routing_decision"][0]
    assert routing["payload"]["target_employee_ids"] == [
        "cursor-super-employee",
        "codex-super-employee",
    ]
    assert "Cursor 主改" in routing["body"]
    assert len(result["work_orders"]) == 2


@pytest.mark.asyncio
async def test_super_development_group_discussion_timeout_keeps_dispatch_moving(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(group_chat_module, "SUPER_DISCUSSION_COMPLETION_TIMEOUT_SEC", 0.01)

    async def slow_completion(messages):
        await asyncio.sleep(10)
        return {"success": True, "content": "too late", "error": ""}

    calls: list[str] = []

    def executor(employee_id: str, task: str, input_data: dict, user_id: int):
        calls.append(employee_id)
        return {"success": True, "summary": f"{employee_id} 已接单"}

    svc = AiGroupChatService(
        storage_root=tmp_path,
        completion_fn=slow_completion,
        employee_executor_fn=executor,
        department_loader=fake_departments,
        employee_loader=lambda: [],
    )
    group = svc.create_group(user_id=9, name="超级开发部")
    for member in [
        {"employee_id": "codex-super-employee", "mod_id": "super-employee", "name": "超级员工-Codex"},
        {"employee_id": "cursor-super-employee", "mod_id": "super-employee", "name": "超级员工-Cursor"},
        {"employee_id": "claude-super-employee", "mod_id": "super-employee", "name": "超级员工-Claude"},
    ]:
        svc.add_member(user_id=9, group_id=group["id"], member=member)

    result = await svc.post_message(
        user_id=9,
        group_id=group["id"],
        text="简单任务：移动端派工链路测试",
        dispatch=True,
    )

    bodies = [str(m.get("body") or "") for m in result["messages"]]
    assert any("小C先评估，再选负责人" in body for body in bodies)
    assert any("我判断这是" in body and "改动文件、命令和测试结果" in body for body in bodies)
    assert all("按职责待命" not in body for body in bodies)
    assert any("小C分工" in body for body in bodies)
    assert calls == ["codex-super-employee"]


@pytest.mark.asyncio
async def test_super_development_group_replaces_placeholder_discussion(tmp_path: Path):
    async def completion(messages):
        system = messages[0]["content"]
        if "群聊工作流调度器" in system:
            return {
                "success": True,
                "content": (
                    '{"target_employee_ids":["codex-super-employee"],'
                    '"rationale":"简单任务，只派 Codex 一个负责人。"}'
                ),
                "error": "",
            }
        return {
            "success": True,
            "content": "收到，我按职责待命，等派工后给出执行结果。",
            "error": "",
        }

    def executor(employee_id: str, task: str, input_data: dict, user_id: int):
        return {
            "success": True,
            "summary": "已修改 app/application/ai_group_chat_service.py；验证：pytest tests/test_application/test_ai_group_chat_service.py 通过。",
        }

    svc = AiGroupChatService(
        storage_root=tmp_path,
        completion_fn=completion,
        employee_executor_fn=executor,
        department_loader=fake_departments,
        employee_loader=lambda: [],
    )
    group = svc.create_group(user_id=9, name="超级开发部")
    for member in [
        {"employee_id": "codex-super-employee", "mod_id": "super-employee", "name": "超级员工-Codex"},
        {"employee_id": "cursor-super-employee", "mod_id": "super-employee", "name": "超级员工-Cursor"},
    ]:
        svc.add_member(user_id=9, group_id=group["id"], member=member)

    result = await svc.post_message(
        user_id=9,
        group_id=group["id"],
        text="修复超级开发部任务讨论假讨论",
        dispatch=True,
    )

    discussion = [m for m in result["messages"] if m.get("kind") == "discussion"]
    assert discussion
    assert all("收到，我按职责待命，等派工后给出执行结果" not in m["body"] for m in discussion)
    assert all("按职责待命" not in m["body"] for m in discussion)
    assert any("我判断这是" in m["body"] and "负责人" in m["body"] for m in discussion)


def test_preferred_single_dispatch_target_prioritizes_dev_work_over_review_word():
    candidates = [
        {"employee_id": "codex-super-employee", "name": "超级员工-Codex"},
        {"employee_id": "cursor-super-employee", "name": "超级员工-Cursor"},
        {"employee_id": "claude-super-employee", "name": "超级员工-Claude"},
    ]

    selected = AiGroupChatService._preferred_single_dispatch_target(
        candidates,
        "修复超级开发部先讨论再派工和假阳性验收；回报必须包含 changed files 和 tests passed。",
    )

    assert selected is not None
    assert selected["employee_id"] == "codex-super-employee"


@pytest.mark.asyncio
async def test_super_development_group_dispatches_super_employees_via_mobile_relay(
    tmp_path: Path,
):
    class FakeRelay:
        def __init__(self):
            self.created: list[dict] = []

        def list_desktops(self, *, user_id: int):
            return [
                {"relay_id": "old-relay", "status": "paired", "last_seen_at": "2026-01-01T00:00:00Z"},
                {"relay_id": "fresh-relay", "status": "paired", "last_seen_at": "2026-01-01T00:00:10Z"},
            ]

        def create_task(self, *, user_id: int, relay_id: str, kind: str, payload: dict):
            self.created.append(
                {"user_id": user_id, "relay_id": relay_id, "kind": kind, "payload": payload}
            )
            return {"task_id": f"relay-task-{len(self.created)}", "status": "queued"}

    async def completion(messages):
        system = messages[0]["content"]
        if "群聊工作流调度器" in system:
            return {
                "success": True,
                "content": (
                    '{"target_employee_ids":["codex-super-employee","cursor-super-employee",'
                    '"claude-super-employee"],"rationale":"全员验证移动端派工链路。"}'
                ),
                "error": "",
            }
        return {"success": True, "content": "收到，先判断再派工。", "error": ""}

    relay = FakeRelay()
    svc = AiGroupChatService(
        storage_root=tmp_path,
        completion_fn=completion,
        department_loader=fake_departments,
        employee_loader=lambda: [],
    )
    svc._mobile_relay_service = lambda: relay  # type: ignore[method-assign]
    group = svc.create_group(user_id=9, name="超级开发部")
    for member in [
        {"employee_id": "codex-super-employee", "mod_id": "super-employee", "name": "超级员工-Codex"},
        {"employee_id": "cursor-super-employee", "mod_id": "super-employee", "name": "超级员工-Cursor"},
        {"employee_id": "claude-super-employee", "mod_id": "super-employee", "name": "超级员工-Claude"},
    ]:
        svc.add_member(user_id=9, group_id=group["id"], member=member)

    result = await svc.post_message(
        user_id=9,
        group_id=group["id"],
        text="全链路移动端派工链路测试，多个模块一起验收",
        dispatch=True,
        branch_context="mobile-group/relay-clean",
    )

    assert [item["kind"] for item in relay.created] == [
        "codex.invoke",
        "cursor.invoke",
        "claude.invoke",
    ]
    assert {item["relay_id"] for item in relay.created} == {"fresh-relay"}
    reports = [m for m in result["messages"] if m.get("kind") == "work_report"]
    assert [m["status"] for m in reports] == ["queued", "queued", "queued"]
    assert [m["payload"]["raw"]["dispatcher"] for m in reports] == [
        "mobile_relay",
        "mobile_relay",
        "mobile_relay",
    ]
    assert [m["payload"]["raw"]["task_id"] for m in reports] == [
        "relay-task-1",
        "relay-task-2",
        "relay-task-3",
    ]
    messages = [item["payload"]["message"] for item in relay.created]
    assert len(set(messages)) == 3
    original_task = "全链路移动端派工链路测试，多个模块一起验收"
    assert all(f"原始需求：{original_task}" in message for message in messages)
    assert all(
        item["payload"]["context"]["original_task"] == original_task
        for item in relay.created
    )
    assert all(item["payload"]["branch"] == "mobile-group/relay-clean" for item in relay.created)
    assert all(
        item["payload"]["context"]["branch"] == "mobile-group/relay-clean"
        for item in relay.created
    )
    assert {item["payload"]["context"]["assignment_focus"] for item in relay.created} == {
        "服务端链路、数据状态、接口和自动化测试证据",
        "移动端体验、前端交互和可见 UI 验证",
        "方案拆解、风险评审、验收标准和最终收口",
    }


@pytest.mark.asyncio
async def test_super_development_group_relay_dispatch_returns_immediate_progress(
    tmp_path: Path,
):
    class FakeRelay:
        def list_desktops(self, *, user_id: int):
            return [{"relay_id": "relay-1", "status": "paired", "last_seen_at": "2026-01-01T00:00:00Z"}]

        def create_task(self, *, user_id: int, relay_id: str, kind: str, payload: dict):
            return {"task_id": "relay-task-progress", "status": "queued"}

    async def completion(messages):
        system = messages[0]["content"]
        if "群聊工作流调度器" in system:
            return {
                "success": True,
                "content": (
                    '{"target_employee_ids":["codex-super-employee"],'
                    '"rationale":"中等服务端任务，先派 Codex 一个负责人。"}'
                ),
                "error": "",
            }
        return {"success": True, "content": "先判断难度，再派一个负责人。", "error": ""}

    svc = AiGroupChatService(
        storage_root=tmp_path,
        completion_fn=completion,
        department_loader=fake_departments,
        employee_loader=lambda: [],
    )
    svc._mobile_relay_service = lambda: FakeRelay()  # type: ignore[method-assign]
    group = svc.create_group(user_id=9, name="超级开发部")
    for member in [
        {"employee_id": "codex-super-employee", "mod_id": "super-employee", "name": "超级员工-Codex"},
        {"employee_id": "cursor-super-employee", "mod_id": "super-employee", "name": "超级员工-Cursor"},
        {"employee_id": "claude-super-employee", "mod_id": "super-employee", "name": "超级员工-Claude"},
    ]:
        svc.add_member(user_id=9, group_id=group["id"], member=member)

    result = await svc.post_message(
        user_id=9,
        group_id=group["id"],
        text="中等难度：修复超级开发部派工进度回访体验",
        dispatch=True,
    )

    kinds = [m.get("kind") for m in result["messages"]]
    assert "discussion" in kinds
    assert "work_report" in kinds
    assert "work_progress" in kinds
    progress = next(m for m in result["messages"] if m.get("kind") == "work_progress")
    assert progress["status"] == "queued"
    assert "不需要你退出重进" in progress["body"]
    messages = svc.get_messages(user_id=9, group_id=group["id"])
    assert sum(1 for m in messages if m.get("kind") == "work_progress") == 1


def test_duplicate_super_development_groups_are_merged_and_alias_resolves(tmp_path: Path):
    svc = make_service(tmp_path)
    first = svc.create_group(user_id=1, name="小C助理、超级员工-Codex、超级员工-Cursor、超级员工-Claude")
    second = svc.create_group(user_id=1, name="超级开发部")
    members = [
        {"employee_id": "codex-super-employee", "mod_id": "super-employee", "name": "超级员工-Codex"},
        {"employee_id": "cursor-super-employee", "mod_id": "super-employee", "name": "超级员工-Cursor"},
        {"employee_id": "claude-super-employee", "mod_id": "super-employee", "name": "超级员工-Claude"},
    ]
    for group in [first, second]:
        for member in members:
            svc.add_member(user_id=1, group_id=group["id"], member=member)
    svc._append_messages(  # noqa: SLF001 - 覆盖重复群合并
        [
            svc._message_row(  # noqa: SLF001
                user_id=1,
                group_id=first["id"],
                role="ai",
                sender_id="xcagi-assistant",
                sender_name="小C助理",
                sender_avatar="",
                body="旧群消息",
            ),
            svc._message_row(  # noqa: SLF001
                user_id=1,
                group_id=second["id"],
                role="ai",
                sender_id="xcagi-assistant",
                sender_name="小C助理",
                sender_avatar="",
                body="新群消息",
            ),
        ]
    )

    visible = svc.list_groups(user_id=1)
    visible_super = [g for g in visible if g["name"] == "超级开发部"]
    assert len(visible_super) == 1
    all_groups = svc.list_groups(user_id=1, include_hidden=True)
    hidden_alias = next(g for g in svc._user_groups(1) if g.get("is_hidden"))  # noqa: SLF001
    assert hidden_alias.get("alias_group_id") == visible_super[0]["id"]
    alias_messages = svc.get_messages(user_id=1, group_id=str(hidden_alias["id"]))
    assert {m["body"] for m in alias_messages} == {"旧群消息", "新群消息"}
    assert any(g["id"] == visible_super[0]["id"] for g in all_groups)


def test_append_relay_work_report_adds_final_group_report_idempotently(tmp_path: Path):
    svc = make_service(tmp_path)
    group = svc.create_group(user_id=1, name="超级开发部")
    svc.add_member(
        user_id=1,
        group_id=group["id"],
        member={"employee_id": "codex-super-employee", "name": "超级员工-Codex"},
    )
    task = {
        "task_id": "relay-task-1",
        "relay_id": "relay-1",
        "kind": "codex.invoke",
        "status": "completed",
        "created_by_user_id": 1,
        "payload": {
            "message": "移动端派工终态回写测试",
            "context": {
                "source": "mobile_ai_group",
                "group_id": group["id"],
                "group_name": "超级开发部",
                "work_order_id": "work-order-1",
                "employee_id": "codex-super-employee",
            },
        },
        "result": {
            "ok": True,
            "codex": {
                "dispatch": {"dispatcher": "codex_cli", "status": "completed"},
                "assistant_message": {
                    "body": (
                        "真实桌面执行端已完成并回写。改动文件："
                        "mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/navigation/ChatScreen.kt；"
                        "验证：pytest tests/test_application/test_ai_group_chat_service.py 通过。"
                    )
                },
            },
        },
    }

    first = svc.append_relay_work_report(task=task)
    second = svc.append_relay_work_report(task=task)

    assert first is not None
    assert second is not None
    assert second["id"] == first["id"]
    messages = svc.get_messages(user_id=1, group_id=group["id"])
    assert len(messages) == 1
    assert messages[0]["kind"] == "relay_work_report"
    assert messages[0]["status"] == "completed"
    assert messages[0]["work_order_id"] == "work-order-1"
    assert "真实桌面执行端已完成并回写" in messages[0]["body"]
    assert messages[0]["payload"]["raw"]["task_id"] == "relay-task-1"
    assert messages[0]["payload"]["raw"]["dispatcher"] == "codex_cli"


def test_get_messages_caps_historical_long_work_report_body(tmp_path: Path):
    svc = make_service(tmp_path)
    group = svc.create_group(user_id=1, name="超级开发部")
    long_body = (
        "执行日志：[all_hands_app_service.py](/private/var/folders/tmp/demo/FHD/app/application/all_hands_app_service.py:2)"
        + ("这是很长的执行输出。" * 300)
    )
    svc._append_messages(  # noqa: SLF001 - 验证旧消息公开展示折叠
        [
            svc._message_row(  # noqa: SLF001
                user_id=1,
                group_id=group["id"],
                role="ai",
                sender_id="codex-super-employee",
                sender_name="超级员工-Codex",
                sender_avatar="",
                body=long_body,
                kind="relay_work_report",
                status="completed",
                payload={"raw": {"task_id": "relay-task-long"}, "full": long_body},
            )
        ]
    )

    messages = svc.get_messages(user_id=1, group_id=group["id"])

    assert len(messages[0]["body"]) < len(long_body)
    assert "聊天里已折叠长执行输出" in messages[0]["body"]
    assert "/private/var/folders" not in messages[0]["body"]
    assert "all_hands_app_service.py" in messages[0]["body"]
    assert messages[0]["payload"]["full"] == long_body


def test_chat_friendly_summary_removes_markdown_links_and_temp_paths():
    summary = AiGroupChatService._chat_friendly_summary(  # noqa: SLF001
        "**职责结论**：[all_hands_app_service.py](/private/var/folders/tmp/demo/FHD/app/application/all_hands_app_service.py:2) 已验证。",
        limit=140,
        include_detail_note=False,
    )

    assert "**" not in summary
    assert "/private/var/folders" not in summary
    assert "all_hands_app_service.py" in summary
    assert "职责结论" in summary


def test_public_chat_body_removes_broken_markdown_links():
    body = AiGroupChatService._clean_public_chat_body(  # noqa: SLF001
        "结果：职责结论：[all_hands_app_service.py](临时执行工作区\n"
        "风险：未发现阻塞；中继任务：53b992e79ea7453bb7183761fe7d6568。"
    )

    assert "[all_hands_app_service.py](" not in body
    assert "all_hands_app_service.py" in body
    assert "53b992e79ea7453bb7183761fe7d6568" not in body


def test_append_relay_work_report_adds_acceptance_when_work_order_done(tmp_path: Path):
    svc = make_service(tmp_path)
    group = svc.create_group(user_id=1, name="超级开发部")
    for member in [
        {"employee_id": "codex-super-employee", "name": "超级员工-Codex"},
        {"employee_id": "cursor-super-employee", "name": "超级员工-Cursor"},
    ]:
        svc.add_member(user_id=1, group_id=group["id"], member=member)
    work_order_id = "work-order-1"
    svc._append_messages(  # noqa: SLF001 - 覆盖真实消息流水收口
        [
            svc._message_row(  # noqa: SLF001
                user_id=1,
                group_id=group["id"],
                role="ai",
                sender_id="ai-group-dispatcher",
                sender_name="工作流调度",
                sender_avatar="",
                body=svc._format_work_order_message(  # noqa: SLF001
                    "移动端派工验收测试",
                    ["超级员工-Codex", "超级员工-Cursor"],
                ),
                kind="work_order",
                status="assigned",
                work_order_id=work_order_id,
                payload={"task": "移动端派工验收测试"},
            ),
            svc._message_row(  # noqa: SLF001
                user_id=1,
                group_id=group["id"],
                role="ai",
                sender_id="codex-super-employee",
                sender_name="超级员工-Codex",
                sender_avatar="",
                body="Codex 已接单",
                kind="work_report",
                status="queued",
                work_order_id=work_order_id,
                payload={"raw": {"task_id": "relay-task-1"}},
            ),
            svc._message_row(  # noqa: SLF001
                user_id=1,
                group_id=group["id"],
                role="ai",
                sender_id="cursor-super-employee",
                sender_name="超级员工-Cursor",
                sender_avatar="",
                body="Cursor 已接单",
                kind="work_report",
                status="queued",
                work_order_id=work_order_id,
                payload={"raw": {"task_id": "relay-task-2"}},
            ),
        ]
    )

    for task_id, employee_id in [
        ("relay-task-1", "codex-super-employee"),
        ("relay-task-2", "cursor-super-employee"),
    ]:
        svc.append_relay_work_report(
            task={
                "task_id": task_id,
                "relay_id": "relay-1",
                "kind": "codex.invoke",
                "status": "completed",
                "created_by_user_id": 1,
                "payload": {
                    "message": "移动端派工验收测试",
                    "context": {
                        "source": "mobile_ai_group",
                        "group_id": group["id"],
                        "work_order_id": work_order_id,
                        "employee_id": employee_id,
                    },
                },
                "result": {
                    "ok": True,
                    "codex": {
                        "dispatch": {"dispatcher": "codex_cli", "status": "completed"},
                        "assistant_message": {
                            "body": (
                                "已完成验收测试。改动文件：mobile-android/app/src/main/java/ChatScreen.kt；"
                                "验证：pytest tests/test_application/test_ai_group_chat_service.py 通过。"
                            )
                        },
                    },
                },
            }
        )

    messages = svc.get_messages(user_id=1, group_id=group["id"])
    acceptance = [m for m in messages if m.get("kind") == "work_acceptance"]
    assert len(acceptance) == 1
    assert acceptance[0]["sender_id"] == "xcagi-assistant"
    assert acceptance[0]["status"] == "completed"
    assert "可以验收" in acceptance[0]["body"]
    assert "2/2 个负责人已完成" in acceptance[0]["body"]
    assert "不满意就直接说要谁补什么" in acceptance[0]["body"]


def test_append_relay_work_report_marks_acceptance_needs_review_on_blocked_body(tmp_path: Path):
    svc = make_service(tmp_path)
    group = svc.create_group(user_id=1, name="超级开发部")
    svc.add_member(
        user_id=1,
        group_id=group["id"],
        member={"employee_id": "codex-super-employee", "name": "超级员工-Codex"},
    )
    work_order_id = "work-order-blocked"
    svc._append_messages(  # noqa: SLF001 - 覆盖真实消息流水收口
        [
            svc._message_row(  # noqa: SLF001
                user_id=1,
                group_id=group["id"],
                role="ai",
                sender_id="ai-group-dispatcher",
                sender_name="工作流调度",
                sender_avatar="",
                body=svc._format_work_order_message(  # noqa: SLF001
                    "修复手机端消息长按复制删除",
                    ["超级员工-Codex"],
                ),
                kind="work_order",
                status="assigned",
                work_order_id=work_order_id,
                payload={"task": "修复手机端消息长按复制删除"},
            ),
            svc._message_row(  # noqa: SLF001
                user_id=1,
                group_id=group["id"],
                role="ai",
                sender_id="codex-super-employee",
                sender_name="超级员工-Codex",
                sender_avatar="",
                body="Codex 已接单",
                kind="work_report",
                status="queued",
                work_order_id=work_order_id,
                payload={"raw": {"task_id": "relay-task-blocked"}},
            ),
        ]
    )

    svc.append_relay_work_report(
        task={
            "task_id": "relay-task-blocked",
            "relay_id": "relay-1",
            "kind": "codex.invoke",
            "status": "completed",
            "created_by_user_id": 1,
            "payload": {
                "message": "修复手机端消息长按复制删除",
                "context": {
                    "source": "mobile_ai_group",
                    "group_id": group["id"],
                    "work_order_id": work_order_id,
                    "employee_id": "codex-super-employee",
                },
            },
            "result": {
                "ok": True,
                "codex": {
                    "dispatch": {"dispatcher": "codex_cli", "status": "completed"},
                    "assistant_message": {
                        "body": "BLOCKED: 未完成；当前只给出执行方案，未修改文件。"
                    },
                },
            },
        }
    )

    messages = svc.get_messages(user_id=1, group_id=group["id"])
    relay_report = next(m for m in messages if m.get("kind") == "relay_work_report")
    acceptance = next(m for m in messages if m.get("kind") == "work_acceptance")
    assert relay_report["status"] == "blocked"
    assert acceptance["status"] == "needs_review"
    assert "需要复核" in acceptance["body"]
    assert "可以验收" not in acceptance["body"]


def test_acceptance_rejects_cannot_execute_without_evidence(tmp_path: Path):
    svc = make_service(tmp_path)
    group = svc.create_group(user_id=1, name="超级开发部")
    svc.add_member(
        user_id=1,
        group_id=group["id"],
        member={"employee_id": "codex-super-employee", "name": "超级员工-Codex"},
    )
    work_order_id = "work-order-no-evidence"
    svc._append_messages(  # noqa: SLF001
        [
            svc._message_row(  # noqa: SLF001
                user_id=1,
                group_id=group["id"],
                role="ai",
                sender_id="ai-group-dispatcher",
                sender_name="工作流调度",
                sender_avatar="",
                body=svc._format_work_order_message(  # noqa: SLF001
                    "提供改动文件、测试和 APK 安装证据",
                    ["超级员工-Codex"],
                ),
                kind="work_order",
                status="assigned",
                work_order_id=work_order_id,
                payload={"task": "提供改动文件、测试和 APK 安装证据"},
            ),
            svc._message_row(  # noqa: SLF001
                user_id=1,
                group_id=group["id"],
                role="ai",
                sender_id="codex-super-employee",
                sender_name="超级员工-Codex",
                sender_avatar="",
                body="Codex 已接单",
                kind="work_report",
                status="queued",
                work_order_id=work_order_id,
                payload={"raw": {"task_id": "relay-task-no-evidence"}},
            ),
        ]
    )

    svc.append_relay_work_report(
        task={
            "task_id": "relay-task-no-evidence",
            "relay_id": "relay-1",
            "kind": "codex.invoke",
            "status": "completed",
            "created_by_user_id": 1,
            "payload": {
                "message": "提供改动文件、测试和 APK 安装证据",
                "context": {
                    "source": "mobile_ai_group",
                    "group_id": group["id"],
                    "work_order_id": work_order_id,
                    "employee_id": "codex-super-employee",
                },
            },
            "result": {
                "ok": True,
                "codex": {
                    "dispatch": {"dispatcher": "codex_cli", "status": "completed"},
                    "assistant_message": {
                        "body": "当前这个普通对话通道里我不能执行命令、读工作区、跑测试、安装 APK，所以不能给你伪造 changed files / tests / install result。"
                    },
                },
            },
        }
    )

    messages = svc.get_messages(user_id=1, group_id=group["id"])
    relay_report = next(m for m in messages if m.get("kind") == "relay_work_report")
    acceptance = next(m for m in messages if m.get("kind") == "work_acceptance")
    assert relay_report["status"] == "blocked"
    assert acceptance["status"] == "needs_review"
    assert "需要复核" in acceptance["body"]
    assert "可以验收" not in acceptance["body"]


def test_acceptance_rejects_research_only_completion_for_dev_task(tmp_path: Path):
    svc = make_service(tmp_path)
    group = svc.create_group(user_id=1, name="超级开发部")
    svc.add_member(
        user_id=1,
        group_id=group["id"],
        member={"employee_id": "claude-super-employee", "name": "超级员工-Claude"},
    )
    work_order_id = "work-order-research-only"
    svc._append_messages(  # noqa: SLF001
        [
            svc._message_row(  # noqa: SLF001
                user_id=1,
                group_id=group["id"],
                role="ai",
                sender_id="ai-group-dispatcher",
                sender_name="工作流调度",
                sender_avatar="",
                body=svc._format_work_order_message(  # noqa: SLF001
                    "修复超级开发部先讨论再派工，并完成手机端验收测试",
                    ["超级员工-Claude"],
                ),
                kind="work_order",
                status="assigned",
                work_order_id=work_order_id,
                payload={"task": "修复超级开发部先讨论再派工，并完成手机端验收测试"},
            ),
            svc._message_row(  # noqa: SLF001
                user_id=1,
                group_id=group["id"],
                role="ai",
                sender_id="claude-super-employee",
                sender_name="超级员工-Claude",
                sender_avatar="",
                body="Claude 已接单",
                kind="work_report",
                status="queued",
                work_order_id=work_order_id,
                payload={"raw": {"task_id": "relay-task-research-only"}},
            ),
        ]
    )

    svc.append_relay_work_report(
        task={
            "task_id": "relay-task-research-only",
            "relay_id": "relay-1",
            "kind": "claude.invoke",
            "status": "completed",
            "created_by_user_id": 1,
            "payload": {
                "message": "修复超级开发部先讨论再派工，并完成手机端验收测试",
                "context": {
                    "source": "mobile_ai_group",
                    "group_id": group["id"],
                    "work_order_id": work_order_id,
                    "employee_id": "claude-super-employee",
                },
            },
            "result": {
                "ok": True,
                "claude": {
                    "dispatch": {"dispatcher": "claude_cli", "status": "completed"},
                    "assistant_message": {
                        "body": "已调研问题原因：讨论阶段内容偏空，建议后续增加证据校验和负责人选择规则。"
                    },
                },
            },
        }
    )

    messages = svc.get_messages(user_id=1, group_id=group["id"])
    relay_report = next(m for m in messages if m.get("kind") == "relay_work_report")
    acceptance = next(m for m in messages if m.get("kind") == "work_acceptance")
    assert relay_report["status"] == "blocked"
    assert "缺少改动文件" in relay_report["body"]
    assert acceptance["status"] == "needs_review"
    assert "需要复核" in acceptance["body"]
    assert "可以验收" not in acceptance["body"]


def test_acceptance_rejects_phone_observed_progress_and_review_only_reports(tmp_path: Path):
    svc = make_service(tmp_path)
    group = svc.create_group(user_id=1, name="超级开发部")
    for member in [
        {"employee_id": "cursor-super-employee", "name": "超级员工-Cursor"},
        {"employee_id": "claude-super-employee", "name": "超级员工-Claude"},
    ]:
        svc.add_member(user_id=1, group_id=group["id"], member=member)
    work_order_id = "work-order-phone-observed"
    task_text = "修复超级开发部任务讨论假讨论、执行假完成、小C验收假阳性"
    svc._append_messages(  # noqa: SLF001
        [
            svc._message_row(  # noqa: SLF001
                user_id=1,
                group_id=group["id"],
                role="ai",
                sender_id="ai-group-dispatcher",
                sender_name="工作流调度",
                sender_avatar="",
                body=svc._format_work_order_message(  # noqa: SLF001
                    task_text,
                    ["超级员工-Cursor", "超级员工-Claude"],
                ),
                kind="work_order",
                status="assigned",
                work_order_id=work_order_id,
                payload={"task": task_text},
            ),
            svc._message_row(  # noqa: SLF001
                user_id=1,
                group_id=group["id"],
                role="ai",
                sender_id="cursor-super-employee",
                sender_name="超级员工-Cursor",
                sender_avatar="",
                body="Cursor 已接单",
                kind="work_report",
                status="queued",
                work_order_id=work_order_id,
                payload={"raw": {"task_id": "relay-task-cursor-progress"}},
            ),
            svc._message_row(  # noqa: SLF001
                user_id=1,
                group_id=group["id"],
                role="ai",
                sender_id="claude-super-employee",
                sender_name="超级员工-Claude",
                sender_avatar="",
                body="Claude 已接单",
                kind="work_report",
                status="queued",
                work_order_id=work_order_id,
                payload={"raw": {"task_id": "relay-task-claude-review"}},
            ),
        ]
    )

    for task_id, employee_id, body in [
        (
            "relay-task-cursor-progress",
            "cursor-super-employee",
            "正在搜索代码库中与群组任务讨论、负责人优先相关的移动端/前端实现；正在实现移动端与 Web 前端的群消息类型展示。",
        ),
        (
            "relay-task-claude-review",
            "claude-super-employee",
            "【SuperDevelopment 群 · 角色:验收/风险/收口 owner】我只出验收口径、风险、收口。实现/测试运行/构建/E2E 分给其他负责人。",
        ),
    ]:
        svc.append_relay_work_report(
            task={
                "task_id": task_id,
                "relay_id": "relay-1",
                "kind": "cursor.invoke" if "cursor" in employee_id else "claude.invoke",
                "status": "completed",
                "created_by_user_id": 1,
                "payload": {
                    "message": task_text,
                    "context": {
                        "source": "mobile_ai_group",
                        "group_id": group["id"],
                        "work_order_id": work_order_id,
                        "employee_id": employee_id,
                    },
                },
                "result": {
                    "ok": True,
                    "agent": {
                        "dispatch": {"dispatcher": "cli", "status": "completed"},
                        "assistant_message": {"body": body},
                    },
                },
            }
        )

    messages = svc.get_messages(user_id=1, group_id=group["id"])
    reports = [m for m in messages if m.get("kind") == "relay_work_report"]
    acceptance = next(m for m in messages if m.get("kind") == "work_acceptance")
    assert {m["sender_id"]: m["status"] for m in reports} == {
        "cursor-super-employee": "blocked",
        "claude-super-employee": "blocked",
    }
    assert acceptance["status"] == "needs_review"
    assert "需要复核" in acceptance["body"]
    assert "可以验收" not in acceptance["body"]


def test_get_messages_syncs_super_employee_result_without_false_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class FakeRelay:
        def get_task(self, *, user_id: int, task_id: str):
            return None

    class FakeSuperEmployee:
        def list_messages(self, *, user_id: int, limit: int = 80):
            return [
                {
                    "role": "assistant",
                    "kind": "codex_result",
                    "task_id": "devfleet-task-progress",
                    "status": "completed",
                    "task_status": "completed",
                    "body": "正在搜索代码库中与群组任务讨论相关的实现；正在实现移动端展示。",
                }
            ]

    monkeypatch.setattr(
        AiGroupChatService,
        "_mobile_relay_service",
        staticmethod(lambda: FakeRelay()),
    )
    monkeypatch.setattr(
        AiGroupChatService,
        "_super_employee_service",
        staticmethod(lambda employee_id: FakeSuperEmployee()),
    )

    svc = make_service(tmp_path)
    group = svc.create_group(user_id=1, name="超级开发部")
    svc.add_member(
        user_id=1,
        group_id=group["id"],
        member={"employee_id": "codex-super-employee", "name": "超级员工-Codex"},
    )
    work_order_id = "work-order-devfleet-sync"
    task_text = "修复超级开发部先讨论再派工和假阳性验收"
    svc._append_messages(  # noqa: SLF001
        [
            svc._message_row(  # noqa: SLF001
                user_id=1,
                group_id=group["id"],
                role="ai",
                sender_id="ai-group-dispatcher",
                sender_name="工作流调度",
                sender_avatar="",
                body=svc._format_work_order_message(  # noqa: SLF001
                    task_text,
                    ["超级员工-Codex"],
                ),
                kind="work_order",
                status="assigned",
                work_order_id=work_order_id,
                payload={"task": task_text},
            ),
            svc._message_row(  # noqa: SLF001
                user_id=1,
                group_id=group["id"],
                role="ai",
                sender_id="codex-super-employee",
                sender_name="超级员工-Codex",
                sender_avatar="",
                body="Codex 已接单",
                kind="work_report",
                status="accepted",
                work_order_id=work_order_id,
                payload={
                    "work_order_id": work_order_id,
                    "employee_id": "codex-super-employee",
                    "employee_name": "超级员工-Codex",
                    "task": task_text,
                    "original_task": task_text,
                    "assignment_focus": "主负责人",
                    "status": "accepted",
                    "success": True,
                    "summary": "思考中...",
                    "raw": {
                        "task_id": "devfleet-task-progress",
                        "dispatcher": "codex_super_employee",
                        "kind": "codex.invoke",
                    },
                },
            ),
        ]
    )

    messages = svc.get_messages(user_id=1, group_id=group["id"])
    report = next(m for m in messages if m.get("kind") == "relay_work_report")
    acceptance = next(m for m in messages if m.get("kind") == "work_acceptance")

    assert report["status"] == "blocked"
    assert "缺少改动文件" in report["body"]
    assert acceptance["status"] == "needs_review"
    assert "需要复核" in acceptance["body"]
    assert "可以验收" not in acceptance["body"]


def test_create_custom_group(tmp_path: Path):
    svc = make_service(tmp_path)
    svc.list_groups(user_id=1)
    g = svc.create_group(user_id=1, name="我的专属小队")
    assert g["name"] == "我的专属小队"
    assert g["member_count"] == 1
    assert g["members"][0]["employee_id"] == "xcagi-assistant"
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
    assert by_key["ops_acquisition"]["member_count"] == 2
    assert by_key["ops_acquisition"]["members"][1]["name"] == "小销"
    assert by_key["ops_partner"]["member_count"] == 2
    assert by_key["prod_web"]["member_count"] == 2
    assert by_key["prod_mod"]["member_count"] == 1  # 仅固定小C
    # 游离员工不进任何部门群
    all_ids = {m["employee_id"] for g in groups for m in g["members"]}
    assert "e_no_dept" not in all_ids


def test_backfill_existing_empty_groups(tmp_path: Path):
    """已存在的空部门群首次访问时回填成员（仅一次，用户移人后不覆盖）。"""
    # 先用空员工建群
    svc = make_service(tmp_path, employees=[])
    groups = svc.list_groups(user_id=1)
    assert all(g["member_count"] == 1 for g in groups)

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
    assert by_key["ops_acquisition"]["member_count"] == 2

    # 用户手动移人后，再次 list 不会自动加回（members_seeded 已置 True）
    svc2.remove_member(user_id=1, group_id="dept:ops_acquisition", employee_id="e1")
    groups3 = svc2.list_groups(user_id=1)
    by_key3 = {g["department_key"]: g for g in groups3}
    assert by_key3["ops_acquisition"]["member_count"] == 1


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
    assert all(g["member_count"] == 1 for g in groups)


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
    assert by_key["execution"]["member_count"] == 2
    assert by_key["execution"]["members"][1]["name"] == "标签打印"
    assert by_key["service"]["member_count"] == 2
    assert by_key["tools"]["member_count"] == 2
    assert by_key["management"]["member_count"] == 2


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
