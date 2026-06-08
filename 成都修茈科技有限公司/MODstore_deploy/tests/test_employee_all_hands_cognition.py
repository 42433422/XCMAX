"""员工大会：_cognition_real 须把 task_text 注入 LLM user 消息（非仅 RAG query）。"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import modstore_server.employee_executor as ee


def test_is_all_hands_cognition_context_flags() -> None:
    assert ee._is_all_hands_cognition_context({"all_hands_standby": True})
    assert ee._is_all_hands_cognition_context({"role_context": {"mode": "all_hands_meeting"}})
    assert ee._is_all_hands_cognition_context({"role_context": {"mode": "all_hands_standby"}})
    assert not ee._is_all_hands_cognition_context({"role_context": {"mode": "daily_brief"}})
    assert not ee._is_all_hands_cognition_context({})


def test_build_all_hands_cognition_user_message_includes_task() -> None:
    task = "## 一、文件与工作逻辑\n- 示例"
    inp = {"all_hands_standby": True, "employee_id": "dbops-engineer"}
    msg = ee._build_all_hands_cognition_user_message(task, inp)
    assert task in msg
    assert "以下为结构化输入（JSON）" in msg
    assert "dbops-engineer" in msg


def test_cognition_real_all_hands_injects_task_into_user_message() -> None:
    captured_messages: List[Dict[str, Any]] = []

    async def _fake_dispatch(_session, _uid, _provider, _model, messages, **kwargs):
        captured_messages.extend(messages)
        return {"ok": True, "content": "## 一、文件与工作逻辑\n- ok"}

    config = {
        "agent": {
            "system_prompt": "日常任务请输出 JSON。",
            "model": {"provider": "openai", "model_name": "gpt-4o-mini", "max_tokens": 512},
        },
        "knowledge": {"enabled": False},
    }
    perceived = {
        "normalized_input": {
            "all_hands_standby": True,
            "role_context": {"mode": "all_hands_meeting"},
            "employee_id": "log-monitor-incident",
        }
    }
    task = "你是 MODstore 在岗 AI 员工。请按四段 Markdown 汇报。"

    with patch(
        "modstore_server.employee_executor.chat_dispatch_via_session",
        new_callable=AsyncMock,
        side_effect=_fake_dispatch,
    ):
        out = ee._run_coro_sync(
            ee._cognition_real(
                config,
                perceived,
                {},
                object(),
                1,
                employee_id="log-monitor-incident",
                task=task,
            )
        )

    assert not out.get("error")
    user_msgs = [m for m in captured_messages if m.get("role") == "user"]
    assert len(user_msgs) == 1
    content = user_msgs[0]["content"]
    assert isinstance(content, str)
    assert task in content
    assert "log-monitor-incident" in content
    sys_content = next(m["content"] for m in captured_messages if m.get("role") == "system")
    assert "员工大会模式" in sys_content
    assert "禁止" in sys_content and "JSON" in sys_content
