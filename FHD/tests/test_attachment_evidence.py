"""附件证据采集：空输入、兜底、工具失败、截断与开关的回归用例。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.application import attachment_evidence as module
from app.application.attachment_artifacts.models import (
    ArtifactRecord,
    ArtifactScope,
    SheetInfo,
)
from app.application.attachment_artifacts.store import ArtifactStore
from app.application.attachment_artifacts.tools import execute_tool as real_execute_tool

ARTIFACT_ID = "a1b2c3d4e5f6a7b8"
SCOPE = ArtifactScope(owner_user_id="101", tenant_id="7")


@pytest.fixture()
def store(tmp_path: Path) -> ArtifactStore:
    artifact_store = ArtifactStore(tmp_path, scope=SCOPE)
    artifact_store.save(
        ArtifactRecord(
            id=ARTIFACT_ID,
            name="订单.xlsx",
            suffix=".xlsx",
            size=128,
            sha1=ARTIFACT_ID,
            created_at="2026-11-15T10:00:00",
            sheets=[
                SheetInfo(
                    name="订单",
                    columns=["单号", "客户", "金额"],
                    row_count=2,
                    rows=[["A001", "张三", "120"], ["A002", "李四", "80"]],
                )
            ],
        )
    )
    return artifact_store


@pytest.fixture(autouse=True)
def isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认开启证据并关闭记忆召回，避免读到本机真实记忆数据。"""
    from app.application.user_memory import retrieve

    monkeypatch.setenv("XCAGI_ATTACHMENT_EVIDENCE", "1")
    monkeypatch.setattr(retrieve, "build_memory_context", lambda *args, **kwargs: "")


def _fake_llm(content: str):
    async def _call(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"choices": [{"message": {"content": content}}]}

    return _call


async def test_no_artifact_ids_returns_empty(
    monkeypatch: pytest.MonkeyPatch, store: ArtifactStore
) -> None:
    called: list[Any] = []
    monkeypatch.setattr(module, "execute_tool", lambda *args, **kwargs: called.append(args))
    monkeypatch.setattr(module, "chat_completion_openai_format", _fake_llm('{"calls": []}'))

    result = await module.collect_evidence("帮我看下这个表", [], store=store)
    assert result == {"evidence": "", "trace": [], "artifacts": []}
    assert called == []

    assert await module.collect_evidence("帮我看下这个表", [ARTIFACT_ID], store=None) == {
        "evidence": "",
        "trace": [],
        "artifacts": [],
    }


async def test_invalid_json_falls_back_to_heuristic(
    monkeypatch: pytest.MonkeyPatch, store: ArtifactStore
) -> None:
    monkeypatch.setattr(module, "chat_completion_openai_format", _fake_llm("抱歉，我无法输出 JSON"))

    result = await module.collect_evidence("这个表里有什么", [ARTIFACT_ID], store=store)
    assert len(result["trace"]) >= 1
    assert result["trace"][0]["tool"] == "describe_attachment"
    assert result["trace"][0]["ok"] is True
    assert result["evidence"]
    assert "【工件 订单.xlsx / 概览】" in result["evidence"]
    assert result["artifacts"] == [ARTIFACT_ID]


async def test_heuristic_reads_rows_for_quoted_column(
    monkeypatch: pytest.MonkeyPatch, store: ArtifactStore
) -> None:
    monkeypatch.setattr(module, "chat_completion_openai_format", _fake_llm("not json"))

    result = await module.collect_evidence('统计"金额"的合计', [ARTIFACT_ID], store=store)
    tools = [item["tool"] for item in result["trace"]]
    assert tools == ["describe_attachment", "read_slice"]
    assert "A001 | 张三 | 120" in result["evidence"]


async def test_tool_error_keeps_other_calls(
    monkeypatch: pytest.MonkeyPatch, store: ArtifactStore
) -> None:
    calls = {
        "calls": [
            {"tool": "describe_attachment", "args": {"artifact_id": ARTIFACT_ID}},
            {
                "tool": "read_slice",
                "args": {"artifact_id": ARTIFACT_ID, "sheet": "订单", "start": 0, "limit": 50},
            },
        ]
    }
    monkeypatch.setattr(
        module, "chat_completion_openai_format", _fake_llm(json.dumps(calls, ensure_ascii=False))
    )

    def flaky(name: str, args: dict[str, Any], artifact_store: ArtifactStore) -> dict[str, Any]:
        if name == "describe_attachment":
            raise RuntimeError("工具炸了")
        return real_execute_tool(name, args, artifact_store)

    monkeypatch.setattr(module, "execute_tool", flaky)

    result = await module.collect_evidence("看看数据", [ARTIFACT_ID], store=store)
    assert [item["ok"] for item in result["trace"]] == [False, True]
    assert "工具炸了" in result["trace"][0]["summary"]
    assert result["trace"][1]["tool"] == "read_slice"
    assert "A001 | 张三 | 120" in result["evidence"]


async def test_evidence_truncated_to_max_chars(
    monkeypatch: pytest.MonkeyPatch, store: ArtifactStore
) -> None:
    monkeypatch.setattr(module, "chat_completion_openai_format", _fake_llm("[]"))

    result = await module.collect_evidence("看看数据", [ARTIFACT_ID], store=store, max_chars=30)
    assert result["evidence"]
    assert len(result["evidence"]) <= 30


async def test_switch_off_keeps_only_owned_attachment_manifest(
    monkeypatch: pytest.MonkeyPatch, store: ArtifactStore
) -> None:
    monkeypatch.setenv("XCAGI_ATTACHMENT_EVIDENCE", "off")

    async def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("关闭时不应调用模型")

    monkeypatch.setattr(module, "chat_completion_openai_format", _boom)

    result = await module.collect_evidence("看看数据", [ARTIFACT_ID], store=store)
    assert result == {
        "evidence": "",
        "trace": [],
        "artifacts": [],
        "manifest": [{"id": ARTIFACT_ID, "name": "订单.xlsx", "suffix": ".xlsx"}],
    }
    assert module.evidence_enabled() is False


async def test_memory_hits_prepended(monkeypatch: pytest.MonkeyPatch, store: ArtifactStore) -> None:
    from app.application.user_memory import retrieve

    monkeypatch.setattr(module, "chat_completion_openai_format", _fake_llm("不是 JSON"))
    monkeypatch.setattr(
        retrieve,
        "build_memory_context",
        lambda *args, **kwargs: "【相关记忆】\n1. 对账使用 2025 版模板",
    )
    monkeypatch.setattr(
        "app.application.ai_chat.conversation_history.authorized_memory_context",
        lambda *_: ("personal-memory:v1:authorized", None),
    )

    result = await module.collect_evidence("帮我核对金额", [ARTIFACT_ID], store=store, user_id="u1")
    assert result["evidence"].startswith("【历史记忆】")
    assert "2025 版模板" in result["evidence"]
    assert "【工件 订单.xlsx / 概览】" in result["evidence"]


async def test_foreign_artifact_id_is_never_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    foreign = ArtifactStore(tmp_path, scope=ArtifactScope(owner_user_id="202", tenant_id="7"))
    foreign.save(
        ArtifactRecord(
            id=ARTIFACT_ID,
            name="别人的订单.xlsx",
            suffix=".xlsx",
            size=128,
            sha1=ARTIFACT_ID,
            created_at="2026-11-15T10:00:00",
        )
    )

    async def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("越权工件不应触发模型规划")

    called: list[Any] = []
    monkeypatch.setattr(module, "chat_completion_openai_format", _boom)
    monkeypatch.setattr(module, "execute_tool", lambda *args, **kwargs: called.append(args))

    current = ArtifactStore(tmp_path, scope=SCOPE)
    result = await module.collect_evidence("看看这个表", [ARTIFACT_ID], store=current)
    assert result == {"evidence": "", "trace": [], "artifacts": []}
    assert called == []


def test_evidence_system_block_text() -> None:
    assert module.evidence_system_block("") == ""
    block = module.evidence_system_block("【工件 订单.xlsx / 概览】金额 120")
    assert "不要编造" in block
    assert "只依据该证据中的数字作答" in block
    assert "【工件 订单.xlsx / 概览】金额 120" in block


async def test_list_evidence_only_includes_this_turns_artifacts(monkeypatch, store):
    old_id = "a" * 40
    store.save(
        ArtifactRecord(
            id=old_id,
            name="上一轮.xlsx",
            suffix=".xlsx",
            size=1,
            sha1=old_id,
            created_at="2026-11-15T10:00:00",
        )
    )
    monkeypatch.setattr(
        module,
        "chat_completion_openai_format",
        _fake_llm('{"calls":[{"tool":"list_attachments","args":{}}]}'),
    )
    result = await module.collect_evidence("导入", [ARTIFACT_ID], store=store)
    assert [item["id"] for item in result["manifest"]] == [ARTIFACT_ID]
    assert "订单.xlsx" in result["evidence"]
    assert "上一轮.xlsx" not in result["evidence"]


def test_list_attachments_render_keeps_every_name() -> None:
    names = [f"文件{i}.xlsx" for i in range(22)]
    rendered = module._render_result(
        "list_attachments",
        {"ok": True, "attachments": [{"name": name} for name in names]},
    )
    assert rendered.startswith("共 22 个：")
    for name in names:
        assert name in rendered
