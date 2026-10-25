"""Group component contracts and tenant isolation at the service boundary."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from app.application.ai_group_chat_service import AiGroupChatService
from app.application.group_chat.progress import ProgressSync
from app.application.group_chat.projections import ChatProjection
from app.application.group_chat.protocols import (
    EmployeeProviders,
    MessageStore,
    MobileRelay,
    Row,
    Rows,
)
from app.application.group_chat.work_dispatch import WorkDispatch


@pytest.fixture
def service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AiGroupChatService:
    monkeypatch.setenv("SECRET_KEY", "group-chat-component-test-secret")
    return AiGroupChatService(
        storage_root=tmp_path,
        department_loader=lambda: {"development": {"label": "开发部"}},
        employee_loader=lambda: [],
    )


def test_delete_group_rejects_a_different_owner(service: AiGroupChatService) -> None:
    foreign = service.create_group(user_id=2, name="私有群")
    original = service._all_groups()

    with pytest.raises(ValueError, match="群不存在"):
        service.delete_group(user_id=1, group_id=foreign["id"])

    assert service._all_groups() == original


def test_delete_seeded_group_preserves_same_id_for_other_owner(
    service: AiGroupChatService,
) -> None:
    group = service._seed_department_groups(1)[0]
    foreign = service._seed_department_groups(2)[0]
    assert group["id"] == foreign["id"]

    service.delete_group(user_id=1, group_id=group["id"])

    assert service._all_groups() == [foreign]


@pytest.mark.parametrize(
    "operation",
    ["toggle_pinned", "toggle_followed", "toggle_hidden", "mark_unread", "mark_read"],
)
def test_group_flags_preserve_same_id_for_other_owner(
    service: AiGroupChatService, operation: str
) -> None:
    group = service._seed_department_groups(1)[0]
    foreign = service._seed_department_groups(2)[0]

    getattr(service, operation)(user_id=1, group_id=group["id"])

    assert service._user_groups(2) == [foreign]
    assert len(service._user_groups(1)) == 1


def test_membership_updates_preserve_same_id_for_other_owner(
    service: AiGroupChatService,
) -> None:
    group = service._seed_department_groups(1)[0]
    foreign = service._seed_department_groups(2)[0]

    service.add_member(user_id=1, group_id=group["id"], member={"employee_id": "worker"})
    assert service._user_groups(2) == [foreign]

    service.remove_member(user_id=1, group_id=group["id"], employee_id="worker")
    assert service._user_groups(2) == [foreign]
    assert not any(m["employee_id"] == "worker" for m in service._user_groups(1)[0]["members"])


def test_department_backfill_only_updates_requested_owner(
    service: AiGroupChatService,
) -> None:
    own = service._seed_department_groups(1)[0]
    foreign = service._seed_department_groups(2)[0]
    service._employee_loader = lambda: [
        {"employee_id": "new-worker", "name": "新增员工", "department_key": "development"}
    ]

    service._backfill_department_members([own])

    assert service._user_groups(2) == [foreign]
    assert any(m["employee_id"] == "new-worker" for m in service._user_groups(1)[0]["members"])


def test_duplicate_group_merge_preserves_other_owner_with_same_keeper_id(
    service: AiGroupChatService,
) -> None:
    keeper = {"id": "dept:development", "user_id": 1, "name": "超级开发部", "members": []}
    duplicate = {"id": "old", "user_id": 1, "name": "超级开发部", "members": []}
    foreign = {"id": keeper["id"], "user_id": 2, "name": "我的群", "members": []}
    service._rewrite_groups([keeper, duplicate, deepcopy(foreign)])

    service._merge_duplicate_super_development_groups(1)

    assert service._user_groups(2) == [foreign]


def test_delete_message_preserves_same_id_in_other_tenant_and_group(
    service: AiGroupChatService,
) -> None:
    own: Row = {
        "id": "same-message",
        "user_id": 1,
        "group_id": "g1",
        "role": "user",
        "sender_id": "user",
    }
    other_group = {**own, "group_id": "g2"}
    other_owner = {**own, "user_id": 2}
    service._append_messages([own, other_group, other_owner])

    service.delete_message(user_id=1, group_id="g1", message_id=own["id"])

    assert service._read_messages() == [other_group, other_owner]


def test_followup_excludes_other_tenant_reports_with_same_work_order_id(
    service: AiGroupChatService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "_sync_relay_progress_for_group", lambda **kw: None)
    monkeypatch.setattr(service, "_sync_super_employee_progress_for_group", lambda **kw: None)
    service._append_messages(
        [
            {
                "id": "order",
                "user_id": 1,
                "group_id": "g1",
                "kind": "work_order",
                "work_order_id": "shared-order",
                "payload": {"task": "我的任务"},
            },
            {
                "id": "foreign",
                "user_id": 2,
                "group_id": "g1",
                "kind": "work_progress",
                "work_order_id": "shared-order",
                "sender_name": "其他客户负责人",
                "body": "不能出现在其他客户群里的进度",
                "status": "running",
            },
        ]
    )

    followup = service._append_acceptance_followup(user_id=1, group_id="g1")

    assert followup is not None
    assert "正在等待负责人接单或回报" in followup["body"]
    assert "其他客户" not in followup["body"]


def _memory_messages(rows: Rows) -> MessageStore:
    def rewrite(batch: Rows) -> None:
        rows[:] = deepcopy(batch)

    return MessageStore(
        read=lambda: deepcopy(rows),
        append=lambda batch: rows.extend(deepcopy(batch)),
        rewrite=rewrite,
        previews=lambda uid: ChatProjection.latest_previews(rows, uid),
    )


@pytest.mark.asyncio
async def test_dispatch_component_persists_order_before_executing() -> None:
    persisted: Rows = []
    execution_inputs: Rows = []

    async def execute(**kwargs) -> Row:
        assert [row["kind"] for row in persisted] == ["work_order"]
        execution_inputs.append(kwargs)
        return {
            "status": "queued",
            "success": True,
            "summary": "执行端已接单",
            "raw": {"task_id": "relay-task"},
        }

    component = WorkDispatch(_memory_messages(persisted), execute, ChatProjection.message_row)
    messages, reports = await component.dispatch_work(
        group={"id": "g1"},
        members=[{"employee_id": "worker", "name": "负责人"}],
        task="处理任务",
        user_id=7,
        sender_name="我",
        branch_context="feature/task",
        persist=True,
    )

    assert [row["kind"] for row in persisted] == ["work_order", "work_report", "work_progress"]
    assert persisted == messages
    assert len(reports) == 1
    assert execution_inputs[0]["branch_context"] == "feature/task"
    assert execution_inputs[0]["work_order_id"] == persisted[0]["work_order_id"]
    assert persisted[0]["payload"]["assignments"][0]["task"] == "处理任务"
    assert all(row["user_id"] == 7 and row["group_id"] == "g1" for row in persisted)


def test_progress_component_caches_sources_and_limits_tenant_scope() -> None:
    rows = [
        {
            "user_id": 7,
            "group_id": "g1",
            "kind": "work_report",
            "sender_id": employee,
            "payload": {"raw": {"task_id": task}},
        }
        for employee, task in [
            ("codex-super-employee", "t1"),
            ("codex-super-employee", "t2"),
            ("cursor-super-employee", "unavailable"),
        ]
    ]
    rows.append({**rows[0], "user_id": 9, "sender_id": "claude-super-employee"})
    queried: list[tuple[str, int]] = []
    reports: Rows = []

    class Source:
        def __init__(self, employee_id: str) -> None:
            self.employee_id = employee_id

        def invoke(self, *, user_id: int, message: str, context: Row | None = None) -> Row:
            raise AssertionError("Progress reads must not invoke employees")

        def list_messages(self, *, user_id: int, limit: int = 200) -> Rows:
            queried.append((self.employee_id, user_id))
            if self.employee_id == "cursor-super-employee":
                raise RuntimeError("unavailable source")
            return [
                {"task_id": task, "kind": "codex_result", "body": "测试通过", "status": "done"}
                for task in ("t1", "t2")
            ]

    def no_relay() -> MobileRelay:
        raise AssertionError("Super-employee progress does not need the relay")

    def append_report(*, task: Row) -> None:
        reports.append(task)

    component = ProgressSync(
        _memory_messages(rows),
        EmployeeProviders(no_relay, Source),
        append_report,
        ChatProjection.message_row,
    )
    component.sync_super_employee_progress_for_group(user_id=7, group_id="g1")

    assert queried == [("codex-super-employee", 7), ("cursor-super-employee", 7)]
    assert [report["task_id"] for report in reports] == ["t1", "t2"]
    assert all(report["created_by_user_id"] == 7 for report in reports)
    assert all(report["payload"]["context"]["group_id"] == "g1" for report in reports)


@pytest.mark.asyncio
async def test_completion_and_persistence_ports_resolve_patches_after_construction(
    service: AiGroupChatService, monkeypatch: pytest.MonkeyPatch
) -> None:
    group = service.create_group(user_id=1, name="测试群")
    messages: Rows = []
    completions: list[list[dict[str, str]]] = []

    async def complete(history: list[dict[str, str]]) -> Row:
        completions.append(history)
        return {"success": True, "content": "构造后替换的回复"}

    monkeypatch.setattr(service, "_completion_fn", complete)
    monkeypatch.setattr(service, "_append_messages", lambda batch: messages.extend(deepcopy(batch)))
    monkeypatch.setattr(service, "_read_messages", lambda: deepcopy(messages))

    response = await service.post_message(user_id=1, group_id=group["id"], text="请回复")

    assert len(completions) == 1
    assert "请回复" in completions[0][1]["content"]
    assert response["messages"][-1]["body"] == "构造后替换的回复"
    assert response["group"]["last_message_preview"].endswith("构造后替换的回复")
    assert [row["role"] for row in messages] == ["user", "ai"]


@pytest.mark.asyncio
async def test_super_chat_uses_late_bound_provider_in_chat_mode(
    service: AiGroupChatService, monkeypatch: pytest.MonkeyPatch
) -> None:
    invocations: Rows = []

    class Source:
        def invoke(self, **kwargs) -> Row:
            invocations.append(kwargs)
            return {"assistant_message": {"body": "专用通道回复"}}

    selected: list[str] = []

    def provider(employee_id: str) -> Source:
        selected.append(employee_id)
        return Source()

    monkeypatch.setattr(service, "_super_employee_service", provider)
    reply = await service._super_employee_reply(
        {"name": "工作群"},
        {"employee_id": "trae-super-employee", "name": "Trae"},
        [{"sender_name": "我", "body": "讨论修改代码"}],
        user_id=8,
    )

    assert reply == "专用通道回复"
    assert selected == ["trae-super-employee"]
    assert invocations[0]["context"] == {"mode": "chat"}
    assert invocations[0]["user_id"] == 8
