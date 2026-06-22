from __future__ import annotations

from pathlib import Path

import pytest

from app.application.ai_group_chat_service import AiGroupChatService


def fake_departments() -> dict[str, dict[str, str]]:
    return {
        "ops_acquisition": {"label": "O-A 获客部"},
        "ops_partner": {"label": "O-B 伙伴部"},
        "prod_web": {"label": "P-W 网站部"},
        "prod_mod": {"label": "P-M Mod 部"},
        "prod_software": {"label": "P-S 软件部"},
        "shared_retention": {"label": "S-R 归档部"},
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


def make_service(tmp_path: Path, seen: list[dict] | None = None) -> AiGroupChatService:
    return AiGroupChatService(
        storage_root=tmp_path,
        completion_fn=make_completion(seen),
        department_loader=fake_departments,
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
    result = await svc.post_message(
        user_id=1, group_id=gid, text="帮忙看下", mentions=["e2"]
    )
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
