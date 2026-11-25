"""Regression contracts: one authorized AI employee may be dispatched at most once."""

from __future__ import annotations

import pytest

from app.application.group_chat.dispatch_targeting import DispatchTargeting
from app.application.group_chat.discussion_router import GroupDiscussion
from app.application.group_chat.work_dispatch import WorkDispatch


def _members():
    return [
        {"employee_id": "lead", "name": "负责人"},
        {"employee_id": "audit", "name": "验收"},
        {"employee_id": "build", "name": "开发"},
    ]


def test_model_routing_never_admits_duplicates_or_non_object_payload():
    candidates = _members()
    parsed, _ = DispatchTargeting.parse_routing_json(
        '{"target_employee_ids":["audit","audit","lead","foreign",7,null,"build"]}',
        candidates,
    )
    assert parsed == ["audit", "lead", "build"]
    for malformed in ('[]', '"lead"', "42", "true", "null"):
        assert DispatchTargeting.parse_routing_json(malformed, candidates) == ([], "")
    assert DispatchTargeting.parse_routing_json(
        '{"target_employee_ids":["foreign","foreign"]}', candidates
    )[0] == []


def test_duplicate_roster_entries_do_not_generate_duplicate_work_assignments():
    duplicated = [_members()[0], _members()[0], {"employee_id": ""}, _members()[1]]
    dispatch = DispatchTargeting()
    targets = dispatch.pick_dispatch_targets(duplicated, "@所有人 执行", None)
    assert [m["employee_id"] for m in targets] == ["lead", "audit"]
    assignments = DispatchTargeting.build_dispatch_assignments("执行", duplicated)
    assert [a["employee_id"] for a in assignments] == ["lead", "audit"]
    assert [m["employee_id"] for m in DispatchTargeting.pick_responders(
        duplicated, "@所有人", None
    )] == ["lead", "audit"]


@pytest.mark.asyncio
async def test_explicit_multi_employee_mentions_select_only_named_members():
    async def should_not_call_model(*_args, **_kwargs):
        raise AssertionError("An explicit assignment must not be changed by a model")

    router = GroupDiscussion(
        None,
        lambda **kwargs: kwargs,
        complete=should_not_call_model,
        timeout=lambda: 1.0,
        reply=should_not_call_model,
        route=should_not_call_model,
    )
    selected, rationale = await router.route_after_discussion(
        group={"name": "团队"},
        task="请完成这单",
        candidates=_members(),
        discussion_turns=[],
        mentions=["audit", "build"],
    )
    assert [member["employee_id"] for member in selected] == ["audit", "build"]
    assert "点名" in rationale

    selected, rationale = await router.route_after_discussion(
        group={"name": "团队"},
        task="请完成这单",
        candidates=_members(),
        discussion_turns=[],
        mentions=["revoked-employee"],
    )
    assert selected == []
    assert "未执行" in rationale


@pytest.mark.asyncio
async def test_duplicate_members_never_repeat_work_dispatch_side_effect():
    dispatched = []

    async def execute(**kwargs):
        dispatched.append(kwargs["member"]["employee_id"])
        return {"status": "queued", "success": True, "summary": "已接单"}

    component = WorkDispatch(None, execute, lambda **kwargs: kwargs)
    messages, reports = await component.dispatch_work(
        group={"id": "g1"},
        members=[_members()[0], _members()[0], _members()[1]],
        task="执行原任务",
        user_id=1,
        sender_name="用户",
        persist=False,
    )
    assert dispatched == ["lead", "audit"]
    assert len(reports) == 2
    assert [row["employee_id"] for row in messages[0]["payload"]["assignments"]] == [
        "lead", "audit"
    ]
