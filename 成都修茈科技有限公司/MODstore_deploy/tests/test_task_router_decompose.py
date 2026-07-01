"""task_router.decompose_task 正常拆解路径 + 回落路径。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

from modstore_server import task_router


class _DummyCtx:
    """get_session_factory()() 的占位上下文管理器，避免测试触碰真实 DB。"""

    def __enter__(self):
        return MagicMock(name="session")

    def __exit__(self, *_args):
        return False


def _fake_employees():
    return [
        {
            "id": "writer",
            "name": "文案",
            "description": "写作",
            "domain": "marketing",
            "skills": [],
        },
        {"id": "designer", "name": "设计", "description": "配图", "domain": "design", "skills": []},
    ]


def test_decompose_task_produces_multiple_subtasks():
    llm_json = json.dumps(
        [
            {
                "employee_id": "writer",
                "task_brief": "撰写上线文案",
                "input_data": {},
                "depends_on": [],
                "priority": 1,
            },
            {
                "employee_id": "designer",
                "task_brief": "制作配图",
                "input_data": {},
                "depends_on": ["writer"],
                "priority": 2,
            },
        ],
        ensure_ascii=False,
    )
    dispatch_mock = AsyncMock(return_value={"ok": True, "content": llm_json})

    with (
        patch.object(task_router, "_load_all_employee_profiles", return_value=_fake_employees()),
        patch("modstore_server.models.get_session_factory", return_value=lambda: _DummyCtx()),
        patch("modstore_server.services.llm.chat_dispatch_via_session", new=dispatch_mock),
    ):
        subtasks = task_router.decompose_task(
            "做一份产品上线方案",
            llm_provider="deepseek",
            llm_model="deepseek-chat",
        )

    assert [s.employee_id for s in subtasks] == ["writer", "designer"]
    assert subtasks[1].depends_on == ["writer"]
    assert all(s.employee_id != "daily-orchestrator" for s in subtasks)

    dispatch_mock.assert_awaited_once()
    args, kwargs = dispatch_mock.call_args
    assert args[1] == 0
    assert args[2] == "deepseek"
    assert args[3] == "deepseek-chat"
    messages = args[4]
    assert isinstance(messages, list)
    assert messages[0]["role"] == "user"
    assert "stream" not in kwargs


def test_decompose_task_falls_back_when_llm_not_ok():
    dispatch_mock = AsyncMock(return_value={"ok": False, "error": "missing api key"})

    with (
        patch.object(task_router, "_load_all_employee_profiles", return_value=_fake_employees()),
        patch("modstore_server.models.get_session_factory", return_value=lambda: _DummyCtx()),
        patch("modstore_server.services.llm.chat_dispatch_via_session", new=dispatch_mock),
    ):
        subtasks = task_router.decompose_task(
            "做一份产品上线方案",
            llm_provider="deepseek",
            llm_model="deepseek-chat",
        )

    assert len(subtasks) == 1
    assert subtasks[0].employee_id == "daily-orchestrator"
