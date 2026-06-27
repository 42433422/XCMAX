"""真实行为测试，提升 ai_group_chat_service 覆盖率（聚焦此前未覆盖的逻辑）。

覆盖目标：
- 模块级默认加载器（_default_completion / _default_departments /
  _default_enterprise_departments / _dept_key_to_employee_ids /
  _default_duty_employee_loader / _append_super_employees /
  _default_enterprise_employee_loader）
- 群状态切换/标记方法（toggle_pinned/mark_unread/mark_read/
  toggle_followed/toggle_hidden/delete_group）的成功路径与"群不存在"错误分支
- _ai_reply 的 completion 异常 / 失败响应回退分支
- _super_employee_reply 的成功 / 空 body 回退 / 异常分支
- create_group 空名校验、add_member employee_id 校验
- _read_jsonl 坏行跳过、_latest_previews 预览构造
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

import app.application.ai_group_chat_service as svc_mod
from app.application.ai_group_chat_service import AiGroupChatService

# ── 工具 ──


def make_completion(seen: list[dict] | None = None):
    async def completion(messages):
        if seen is not None:
            seen.append({"system": messages[0]["content"], "user": messages[1]["content"]})
        system = messages[0]["content"]
        who = system.split("「", 2)[2].split("」", 1)[0] if system.count("「") >= 2 else "AI"
        return {"success": True, "content": f"{who} 收到", "error": ""}

    return completion


def fake_departments() -> dict[str, dict[str, str]]:
    return {
        "ops_acquisition": {"label": "O-A 获客部"},
        "prod_web": {"label": "P-W 网站部"},
    }


def make_service(tmp_path: Path, seen=None, employees=None) -> AiGroupChatService:
    return AiGroupChatService(
        storage_root=tmp_path,
        completion_fn=make_completion(seen),
        department_loader=fake_departments,
        employee_loader=(lambda: employees or []),
        mode="admin",
    )


# ── 状态切换方法：成功路径 ──


def test_toggle_pinned_flips_and_persists(tmp_path: Path):
    svc = make_service(tmp_path)
    gid = svc.list_groups(user_id=1)[0]["id"]
    g1 = svc.toggle_pinned(user_id=1, group_id=gid)
    assert g1["is_pinned"] is True
    g2 = svc.toggle_pinned(user_id=1, group_id=gid)
    assert g2["is_pinned"] is False
    # 持久化：新实例读取保持
    svc2 = make_service(tmp_path)
    svc.toggle_pinned(user_id=1, group_id=gid)
    reread = next(g for g in svc2.list_groups(user_id=1) if g["id"] == gid)
    assert reread["is_pinned"] is True


def test_mark_unread_then_mark_read(tmp_path: Path):
    svc = make_service(tmp_path)
    gid = svc.list_groups(user_id=1)[0]["id"]
    g1 = svc.mark_unread(user_id=1, group_id=gid)
    assert g1["unread_count"] == 1
    # 再次 mark_unread：current>0 走 current+1 分支
    g2 = svc.mark_unread(user_id=1, group_id=gid)
    assert g2["unread_count"] == 2
    g3 = svc.mark_read(user_id=1, group_id=gid)
    assert g3["unread_count"] == 0


def test_toggle_followed_default_true_then_flip(tmp_path: Path):
    svc = make_service(tmp_path)
    gid = svc.list_groups(user_id=1)[0]["id"]
    # 种子群 is_followed 默认 True → 切换后 False
    g1 = svc.toggle_followed(user_id=1, group_id=gid)
    assert g1["is_followed"] is False
    g2 = svc.toggle_followed(user_id=1, group_id=gid)
    assert g2["is_followed"] is True


def test_toggle_hidden_and_include_hidden_filter(tmp_path: Path):
    svc = make_service(tmp_path)
    groups = svc.list_groups(user_id=1)
    gid = groups[0]["id"]
    n_before = len(groups)
    g1 = svc.toggle_hidden(user_id=1, group_id=gid)
    assert g1["is_hidden"] is True
    # 默认 list 不含隐藏群
    visible = svc.list_groups(user_id=1)
    assert len(visible) == n_before - 1
    assert all(g["id"] != gid for g in visible)
    # include_hidden=True 时仍可见
    full = svc.list_groups(user_id=1, include_hidden=True)
    assert any(g["id"] == gid for g in full)


def test_delete_group_removes_and_returns_payload(tmp_path: Path):
    svc = make_service(tmp_path)
    groups = svc.list_groups(user_id=1)
    gid = groups[0]["id"]
    res = svc.delete_group(user_id=1, group_id=gid)
    assert res == {"deleted": True, "id": str(gid)}
    remaining = svc.list_groups(user_id=1, include_hidden=True)
    assert all(g["id"] != gid for g in remaining)


# ── 状态切换方法：群不存在错误分支 ──


@pytest.mark.parametrize(
    "method",
    [
        "toggle_pinned",
        "mark_unread",
        "mark_read",
        "toggle_followed",
        "toggle_hidden",
        "add_member_missing",
        "remove_member",
        "delete_group",
        "post_message",
    ],
)
async def test_group_not_found_raises(tmp_path: Path, method: str):
    svc = make_service(tmp_path)
    svc.list_groups(user_id=1)  # 种好群
    with pytest.raises(ValueError, match="群不存在"):
        if method == "add_member_missing":
            svc.add_member(user_id=1, group_id="nope", member={"employee_id": "e1", "name": "x"})
        elif method == "remove_member":
            svc.remove_member(user_id=1, group_id="nope", employee_id="e1")
        elif method == "delete_group":
            svc.delete_group(user_id=1, group_id="nope")
        elif method == "post_message":
            await svc.post_message(user_id=1, group_id="nope", text="hi")
        else:
            getattr(svc, method)(user_id=1, group_id="nope")


# ── 输入校验分支 ──


def test_create_group_blank_name_raises(tmp_path: Path):
    svc = make_service(tmp_path)
    with pytest.raises(ValueError, match="群名不能为空"):
        svc.create_group(user_id=1, name="   ")


def test_add_member_blank_employee_id_raises(tmp_path: Path):
    svc = make_service(tmp_path)
    gid = svc.list_groups(user_id=1)[0]["id"]
    with pytest.raises(ValueError, match="employee_id 不能为空"):
        svc.add_member(user_id=1, group_id=gid, member={"employee_id": "  "})


async def test_post_message_blank_text_raises(tmp_path: Path):
    svc = make_service(tmp_path)
    gid = svc.list_groups(user_id=1)[0]["id"]
    with pytest.raises(ValueError, match="message 不能为空"):
        await svc.post_message(user_id=1, group_id=gid, text="   ")


# ── _ai_reply 错误/失败分支 ──


async def test_ai_reply_completion_exception_returns_fallback(tmp_path: Path):
    async def boom(messages):
        raise RuntimeError("llm down")

    svc = AiGroupChatService(
        storage_root=tmp_path,
        completion_fn=boom,
        department_loader=fake_departments,
        employee_loader=lambda: [],
        mode="admin",
    )
    gid = svc.list_groups(user_id=1)[0]["id"]
    svc.add_member(user_id=1, group_id=gid, member={"employee_id": "e1", "name": "小销"})
    # main 现默认仅小C助理接话；显式 @点名小销 才让其成为唯一响应者并走 _ai_reply。
    result = await svc.post_message(user_id=1, group_id=gid, text="进展如何", mentions=["e1"])
    ai = [m for m in result["messages"] if m["role"] == "ai"]
    assert len(ai) == 1
    assert ai[0]["sender_name"] == "小销"
    assert "小销 暂时无法回应" in ai[0]["body"]
    assert "llm down" in ai[0]["body"]


async def test_ai_reply_failed_response_with_error_field(tmp_path: Path):
    async def failed(messages):
        return {"success": False, "content": "", "error": "配额不足"}

    svc = AiGroupChatService(
        storage_root=tmp_path,
        completion_fn=failed,
        department_loader=fake_departments,
        employee_loader=lambda: [],
        mode="admin",
    )
    gid = svc.list_groups(user_id=1)[0]["id"]
    svc.add_member(user_id=1, group_id=gid, member={"employee_id": "e1", "name": "小销"})
    result = await svc.post_message(user_id=1, group_id=gid, text="hi", mentions=["e1"])
    ai = [m for m in result["messages"] if m["role"] == "ai"][0]
    assert "小销 暂时无法回应：配额不足" in ai["body"]


async def test_ai_reply_non_dict_response_returns_fallback(tmp_path: Path):
    async def weird(messages):
        return "not a dict"

    svc = AiGroupChatService(
        storage_root=tmp_path,
        completion_fn=weird,
        department_loader=fake_departments,
        employee_loader=lambda: [],
        mode="admin",
    )
    gid = svc.list_groups(user_id=1)[0]["id"]
    svc.add_member(user_id=1, group_id=gid, member={"employee_id": "e1", "name": "小销"})
    result = await svc.post_message(user_id=1, group_id=gid, text="hi", mentions=["e1"])
    ai = [m for m in result["messages"] if m["role"] == "ai"][0]
    # 无 error 字段 → 仅"暂时无法回应"
    assert ai["body"] == "（小销 暂时无法回应）"


# ── _super_employee_reply：成功 / 空 body / 异常 ──


def _install_fake_super_modules(monkeypatch, invoke_impl):
    """注入假的 codex/claude super employee service 模块。"""

    class _FakeService:
        def __init__(self, *a, **k):
            pass

        def invoke(self, *, user_id, message, context):
            return invoke_impl(user_id=user_id, message=message, context=context)

    codex_mod = types.ModuleType("app.application.codex_super_employee_service")
    codex_mod.CodexSuperEmployeeService = _FakeService
    claude_mod = types.ModuleType("app.application.claude_super_employee_service")
    claude_mod.ClaudeSuperEmployeeService = _FakeService
    monkeypatch.setitem(sys.modules, "app.application.codex_super_employee_service", codex_mod)
    monkeypatch.setitem(sys.modules, "app.application.claude_super_employee_service", claude_mod)


async def test_super_employee_reply_success(tmp_path: Path, monkeypatch):
    captured = {}

    def invoke_impl(*, user_id, message, context):
        captured["user_id"] = user_id
        captured["message"] = message
        captured["context"] = context
        return {"assistant_message": {"body": "Codex 已答复"}}

    _install_fake_super_modules(monkeypatch, invoke_impl)
    svc = make_service(tmp_path)
    gid = svc.list_groups(user_id=7)[0]["id"]
    svc.add_member(
        user_id=7,
        group_id=gid,
        member={"employee_id": "codex-super-employee", "name": "超级员工-Codex"},
    )
    # main 默认仅小C助理接话；显式 @点名超级员工才走 _super_employee_reply invoke 通道。
    result = await svc.post_message(
        user_id=7, group_id=gid, text="帮我看看", mentions=["codex-super-employee"]
    )
    ai = [m for m in result["messages"] if m["role"] == "ai"][0]
    assert ai["body"] == "Codex 已答复"
    # 群聊场景强制 mode=chat
    assert captured["context"] == {"mode": "chat"}
    assert captured["user_id"] == 7


async def test_super_employee_reply_claude_branch(tmp_path: Path, monkeypatch):
    def invoke_impl(*, user_id, message, context):
        return {"assistant_message": {"body": "Claude 已答复"}}

    _install_fake_super_modules(monkeypatch, invoke_impl)
    svc = make_service(tmp_path)
    gid = svc.list_groups(user_id=1)[0]["id"]
    svc.add_member(
        user_id=1,
        group_id=gid,
        member={"employee_id": "claude-super-employee", "name": "超级员工-Claude"},
    )
    result = await svc.post_message(
        user_id=1, group_id=gid, text="hi", mentions=["claude-super-employee"]
    )
    ai = [m for m in result["messages"] if m["role"] == "ai"][0]
    assert ai["body"] == "Claude 已答复"


async def test_super_employee_reply_empty_body_fallback(tmp_path: Path, monkeypatch):
    def invoke_impl(*, user_id, message, context):
        return {"assistant_message": {"body": "   "}}

    _install_fake_super_modules(monkeypatch, invoke_impl)
    svc = make_service(tmp_path)
    gid = svc.list_groups(user_id=1)[0]["id"]
    svc.add_member(
        user_id=1,
        group_id=gid,
        member={"employee_id": "codex-super-employee", "name": "超级员工-Codex"},
    )
    result = await svc.post_message(
        user_id=1, group_id=gid, text="hi", mentions=["codex-super-employee"]
    )
    ai = [m for m in result["messages"] if m["role"] == "ai"][0]
    assert ai["body"] == "（超级员工-Codex 暂时无法回应）"


async def test_super_employee_reply_exception_fallback(tmp_path: Path, monkeypatch):
    def invoke_impl(*, user_id, message, context):
        raise RuntimeError("device offline")

    _install_fake_super_modules(monkeypatch, invoke_impl)
    svc = make_service(tmp_path)
    gid = svc.list_groups(user_id=1)[0]["id"]
    svc.add_member(
        user_id=1,
        group_id=gid,
        member={"employee_id": "codex-super-employee", "name": "超级员工-Codex"},
    )
    result = await svc.post_message(
        user_id=1, group_id=gid, text="hi", mentions=["codex-super-employee"]
    )
    ai = [m for m in result["messages"] if m["role"] == "ai"][0]
    assert "超级员工-Codex 暂时无法回应：device offline" in ai["body"]


# ── 模块级默认加载器 ──


async def test_default_completion_delegates(monkeypatch):
    calls = {}

    async def fake_complete(messages, *, max_tokens, temperature):
        calls["messages"] = messages
        calls["max_tokens"] = max_tokens
        calls["temperature"] = temperature
        return {"success": True, "content": "ok"}

    fake_llm = types.ModuleType("app.mod_sdk.mod_employee_llm")
    fake_llm.mod_employee_complete = fake_complete
    monkeypatch.setitem(sys.modules, "app.mod_sdk.mod_employee_llm", fake_llm)
    out = await svc_mod._default_completion([{"role": "user", "content": "hi"}])
    assert out == {"success": True, "content": "ok"}
    assert calls["max_tokens"] == 600
    assert calls["temperature"] == 0.4


def test_default_departments_success(monkeypatch):
    fake = types.ModuleType("app.mod_sdk.duty_roster")
    fake.load_departments = lambda: {"d1": {"label": "L1"}}
    monkeypatch.setitem(sys.modules, "app.mod_sdk.duty_roster", fake)
    assert svc_mod._default_departments() == {"d1": {"label": "L1"}}


def test_default_departments_non_dict_returns_empty(monkeypatch):
    fake = types.ModuleType("app.mod_sdk.duty_roster")
    fake.load_departments = lambda: ["not", "a", "dict"]
    monkeypatch.setitem(sys.modules, "app.mod_sdk.duty_roster", fake)
    assert svc_mod._default_departments() == {}


def test_default_departments_exception_returns_empty(monkeypatch):
    fake = types.ModuleType("app.mod_sdk.duty_roster")

    def _boom():
        raise RuntimeError("no config")

    fake.load_departments = _boom
    monkeypatch.setitem(sys.modules, "app.mod_sdk.duty_roster", fake)
    assert svc_mod._default_departments() == {}


def test_default_enterprise_departments_delegates(monkeypatch):
    fake = types.ModuleType("app.domain.enterprise_org_layers")
    fake.enterprise_departments = lambda: {"tools": {"label": "工具层"}}
    monkeypatch.setitem(sys.modules, "app.domain.enterprise_org_layers", fake)
    assert svc_mod._default_enterprise_departments() == {"tools": {"label": "工具层"}}


def test_dept_key_to_employee_ids_flattens_subzones():
    depts = {
        "ops": {
            "subzones": {
                "z1": {"ids": ["e1", " e2 ", ""]},
                "z2": {"ids": ["e3"]},
                "bad": "not-a-dict",
                "no_ids": {"ids": "not-a-list"},
            }
        },
        "empty": {"subzones": {}},  # 无 ids → 不进 mapping
        "not_dict": "skip",
    }
    out = svc_mod._dept_key_to_employee_ids(depts)
    assert out == {"ops": ["e1", "e2", "e3"]}
    assert "empty" not in out
    assert "not_dict" not in out


# ── _append_super_employees ──


def test_append_super_employees_adds_two(monkeypatch):
    # 用真实 CODEX/CLAUDE profile（模块可导入）
    employees: list[dict] = []
    svc_mod._append_super_employees(employees)
    ids = {e["employee_id"] for e in employees}
    assert "codex-super-employee" in ids
    assert "claude-super-employee" in ids
    # department_key 留空、mod_id=super-employee
    for e in employees:
        assert e["department_key"] == ""
        assert e["mod_id"] == "super-employee"


def test_append_super_employees_skips_existing():
    employees = [{"employee_id": "codex-super-employee", "name": "已有"}]
    svc_mod._append_super_employees(employees)
    codex = [e for e in employees if e["employee_id"] == "codex-super-employee"]
    assert len(codex) == 1  # 未重复追加
    # claude 仍被加入
    assert any(e["employee_id"] == "claude-super-employee" for e in employees)


def test_append_super_employees_import_failure_is_silent(monkeypatch):
    bad = types.ModuleType("app.application.super_employee_service")
    # 不提供 CODEX_PROFILE/CLAUDE_PROFILE → from-import 触发 ImportError
    monkeypatch.setitem(sys.modules, "app.application.super_employee_service", bad)
    employees: list[dict] = []
    svc_mod._append_super_employees(employees)
    assert employees == []  # 静默跳过


# ── _default_duty_employee_loader ──


def test_duty_loader_uses_registry_records(monkeypatch):
    """main 现为部门编制驱动：成员归属与 department_key 来自部门 subzone 的 ids，
    duty_employee_records 仅按 id 补充展示元数据（名称/摘要/头像）。"""
    fake = types.ModuleType("app.mod_sdk.duty_roster")
    # 部门编制是 SSOT：emp1∈ops_acquisition、emp2∈prod_web；ids 里的空串被过滤。
    fake.load_departments = lambda: {
        "ops_acquisition": {"subzones": {"z1": {"ids": ["emp1", ""]}}},
        "prod_web": {"subzones": {"z2": {"ids": ["emp2"]}}},
    }
    # registry 记录仅补名称/摘要/头像，按 id（或 pkg_id）匹配；自身 department_key 字段被忽略。
    fake.load_duty_employee_records = lambda: [
        {
            "id": "emp1",
            "name": "员工一",
            "department_key": "should_be_ignored",
            "mod_id": "m1",
            "panel_summary": "摘要一",
            "avatar": "a.png",
        },
        {"id": "", "name": "空ID跳过"},  # eid 为空 → 不进 records_by_id
        {"pkg_id": "emp2", "label": "员工二"},  # 用 pkg_id 匹配 + label 作名称
    ]
    fake.primary_department_for_pkg = lambda eid: ""
    monkeypatch.setitem(sys.modules, "app.mod_sdk.duty_roster", fake)
    out = svc_mod._default_duty_employee_loader()
    by_id = {e["employee_id"]: e for e in out}
    # department_key 来自部门编制，不再取记录自带字段
    assert by_id["emp1"]["department_key"] == "ops_acquisition"
    assert by_id["emp1"]["name"] == "员工一"
    assert by_id["emp1"]["summary"] == "摘要一"
    # emp2 经 pkg_id 匹配记录，department_key 来自 prod_web 编制
    assert by_id["emp2"]["department_key"] == "prod_web"
    assert by_id["emp2"]["name"] == "员工二"
    assert "" not in by_id  # 空 ID 不会成为部门成员
    # 超级员工被追加
    assert "codex-super-employee" in by_id


def test_duty_loader_fallback_to_mods(monkeypatch):
    """registry 为空 → 走 duty_roster 编制 × list_all_mods 回退路径。"""
    fake = types.ModuleType("app.mod_sdk.duty_roster")
    fake.load_duty_employee_records = lambda: []  # registry 空
    fake.load_departments = lambda: {"ops_acquisition": {"subzones": {"z": {"ids": ["e1"]}}}}
    fake.primary_department_for_pkg = lambda eid: ""
    monkeypatch.setitem(sys.modules, "app.mod_sdk.duty_roster", fake)

    class _MM:
        def list_all_mods(self):
            return [
                {
                    "id": "mod1",
                    "description": "mod 描述",
                    "workflow_employees": [
                        {"id": "e1", "name": "员工E1", "panel_summary": "s"},
                        {"id": "e_unknown", "name": "不在编制"},  # 不在 emp_to_dept
                        "not-a-dict",  # 跳过
                    ],
                },
                {"id": "mod2", "workflow_employees": "not-a-list"},  # 跳过
                "not-a-dict",  # 跳过
            ]

    fake_mm = types.ModuleType("app.infrastructure.mods.mod_manager")
    fake_mm.get_mod_manager = lambda: _MM()
    monkeypatch.setitem(sys.modules, "app.infrastructure.mods.mod_manager", fake_mm)

    out = svc_mod._default_duty_employee_loader()
    by_id = {e["employee_id"]: e for e in out}
    assert by_id["e1"]["department_key"] == "ops_acquisition"
    assert by_id["e1"]["mod_id"] == "mod1"
    assert "e_unknown" not in by_id  # 不在编制被过滤
    assert "codex-super-employee" in by_id  # 仍追加超级员工


def test_duty_loader_fallback_no_departments_returns_empty(monkeypatch):
    fake = types.ModuleType("app.mod_sdk.duty_roster")
    fake.load_duty_employee_records = lambda: []
    fake.load_departments = lambda: {}  # 无部门 → 直接返回 []
    fake.primary_department_for_pkg = lambda eid: ""
    monkeypatch.setitem(sys.modules, "app.mod_sdk.duty_roster", fake)
    assert svc_mod._default_duty_employee_loader() == []


# ── _default_enterprise_employee_loader ──


def test_enterprise_loader_resolves_layers(monkeypatch):
    fake_org = types.ModuleType("app.domain.enterprise_org_layers")
    fake_org.resolve_enterprise_org_layer = lambda eid, name, panel, manifest: (
        manifest or "execution"
    )
    monkeypatch.setitem(sys.modules, "app.domain.enterprise_org_layers", fake_org)

    class _MM:
        def list_all_mods(self):
            return [
                {
                    "id": "mod1",
                    "logo": "logo.png",
                    "workflow_employees": [
                        {
                            "id": "emp_exec",
                            "name": "执行员",
                            "panel_summary": "执行摘要",
                        },
                        {
                            "id": "emp_svc",
                            "name": "服务员",
                            "enterprise_layer": "service",
                        },
                        {"id": "", "name": "空ID跳过"},  # eid 空 → continue
                        "not-a-dict",
                    ],
                },
                {"id": "mod_bad", "workflow_employees": None},  # wf 非 list 跳过
            ]

    fake_mm = types.ModuleType("app.infrastructure.mods.mod_manager")
    fake_mm.get_mod_manager = lambda: _MM()
    monkeypatch.setitem(sys.modules, "app.infrastructure.mods.mod_manager", fake_mm)

    out = svc_mod._default_enterprise_employee_loader()
    by_id = {e["employee_id"]: e for e in out}
    assert by_id["emp_exec"]["department_key"] == "execution"
    assert by_id["emp_svc"]["department_key"] == "service"  # manifest 优先
    assert "" not in by_id
    assert "codex-super-employee" in by_id  # 追加超级员工


def test_enterprise_loader_mod_manager_import_failure(monkeypatch):
    fake_org = types.ModuleType("app.domain.enterprise_org_layers")
    fake_org.resolve_enterprise_org_layer = lambda *a, **k: "execution"
    monkeypatch.setitem(sys.modules, "app.domain.enterprise_org_layers", fake_org)

    # mod_manager 导入失败 → 返回 []
    class _Raising(types.ModuleType):
        def __getattr__(self, name):
            raise ImportError("no mod manager")

    monkeypatch.setitem(
        sys.modules,
        "app.infrastructure.mods.mod_manager",
        _Raising("app.infrastructure.mods.mod_manager"),
    )
    assert svc_mod._default_enterprise_employee_loader() == []


# ── _read_jsonl 坏行 / _latest_previews ──


def test_read_jsonl_skips_blank_and_malformed(tmp_path: Path):
    svc = make_service(tmp_path)
    p = tmp_path / "ai_group_chat" / "groups.jsonl"
    p.write_text(
        '{"id":"g1","user_id":1}\n'
        "\n"  # 空行跳过
        "   \n"  # 空白行跳过
        "{bad json}\n"  # 解析失败跳过
        "[1,2,3]\n"  # 非 dict 跳过
        '{"id":"g2","user_id":1}\n',
        encoding="utf-8",
    )
    rows = svc._all_groups()
    ids = [r["id"] for r in rows]
    assert ids == ["g1", "g2"]


def test_read_jsonl_missing_file_returns_empty(tmp_path: Path):
    svc = make_service(tmp_path)
    missing = tmp_path / "does_not_exist.jsonl"
    assert svc._read_jsonl(missing) == []


async def test_latest_previews_reflected_in_list_groups(tmp_path: Path):
    svc = make_service(tmp_path)
    gid = svc.list_groups(user_id=1)[0]["id"]
    svc.add_member(user_id=1, group_id=gid, member={"employee_id": "e1", "name": "小销"})
    await svc.post_message(user_id=1, group_id=gid, text="最新一句")
    groups = svc.list_groups(user_id=1)
    g = next(x for x in groups if x["id"] == gid)
    # 预览取最后一条消息（AI 回复），格式 "sender：body"
    assert g["last_message_preview"]
    assert "：" in g["last_message_preview"]
    assert g["last_message_at"]
