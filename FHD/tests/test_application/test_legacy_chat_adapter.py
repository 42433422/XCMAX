"""Tests for app.legacy.chat.legacy_chat_adapter."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.legacy.chat import legacy_chat_adapter as adapter
from app.legacy.chat.legacy_chat_adapter import (
    _parse_generate_office_format,
    _planner_tools_max_workers,
    _post_tool_round_hint,
    _resolve_chat_model_for_client,
    _slow_tool_wait_message,
    _tool_key,
    _tool_stream_call_label,
    append_tool_messages,
    chat,
    chat_stream_sse_events,
    chat_stream_text,
    get_last_tool_records,
    get_last_tool_result,
    reset_planner_tool_dedup_state,
)


class _Tc:
    def __init__(self, tc_id: str, name: str, arguments: str) -> None:
        self.id = tc_id
        self.function = SimpleNamespace(name=name, arguments=arguments)


def _chat_response(content="", tool_calls=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))]
    )


def _tool_chunk(name, arguments):
    call = _Tc("tc1", name, arguments)
    call.index = 0
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=None, tool_calls=[call]), finish_reason="tool_calls"
            )
        ]
    )


def _client(response, *, side_effect=False):
    client = MagicMock(is_modstore_openai_compatible=False)
    setattr(
        client.chat.completions.create, "side_effect" if side_effect else "return_value", response
    )
    return client


@contextmanager
def _planner_registry(registry):
    with patch.object(adapter, "_get_workflow_tool_registry", return_value=registry):
        yield


@contextmanager
def _planner_tools(execute_tool):
    with (
        _planner_registry([{"type": "function"}]),
        patch.object(adapter, "_resolve_chat_execute_tool", return_value=execute_tool),
    ):
        yield


class TestParseGenerateOfficeFormat:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ('{"output_format":"docx"}', "docx"),
            ('{"output_format":"xlsx"}', "xlsx"),
            ('{"output_format":"DOCX"}', "docx"),
            ('{"output_format":"pdf"}', ""),
            ("", ""),
            (None, ""),
            ("not json", ""),
            ("[1,2]", ""),
            ('{"other":"val"}', ""),
            ('{"output_format":"  "}', ""),
        ],
    )
    def test_formats(self, raw, expected):
        assert _parse_generate_office_format(raw) == expected


class TestToolKey:
    def test_combines_name_and_args(self):
        result = _tool_key("mytool", '{"a":1}')
        assert result.startswith("mytool::")
        assert "a" in result


class TestResolveChatModelForClient:
    @pytest.mark.parametrize(
        "compatible,default_model,provider,explicit,expected",
        [
            (None, "", "", "gpt-4", "gpt-4"),
            (True, "my-model", "prov", None, "prov/my-model"),
            (True, "my-model", "", None, "my-model"),
            (True, "", "prov", None, "fallback-model"),
            (False, "", "", None, "fallback-model"),
            (None, "", "", None, "fallback-model"),
        ],
    )
    def test_model_resolution(self, compatible, default_model, provider, explicit, expected):
        client = (
            None
            if compatible is None
            else MagicMock(
                is_modstore_openai_compatible=compatible,
                default_model=default_model,
                default_provider=provider,
            )
        )
        with patch.object(adapter, "resolve_chat_model", return_value="fallback-model"):
            assert _resolve_chat_model_for_client(client, explicit) == expected


class TestToolStreamCallLabel:
    @pytest.mark.parametrize(
        "name,args,expected",
        [
            ("generate_office_document", '{"output_format":"docx"}', "生成 Word 文档（.docx）"),
            ("generate_office_document", '{"output_format":"xlsx"}', "生成 Excel 工作簿（.xlsx）"),
            (
                "generate_office_document",
                '{"output_format":"pdf"}',
                "生成可下载文档（Word 或 Excel）",
            ),
            ("excel_analysis", "{}", "读取或分析 Excel"),
            ("custom_tool", "{}", "custom_tool"),
        ],
    )
    def test_tool_labels(self, name, args, expected):
        assert _tool_stream_call_label(name, args) == expected


class TestSlowToolWaitMessage:
    @pytest.mark.parametrize(
        "name,args,marker",
        [
            ("import_excel_to_database", "{}", "导入数据库"),
            ("generate_office_document", '{"output_format":"docx"}', "Word"),
            ("generate_office_document", '{"output_format":"xlsx"}', "Excel"),
            ("generate_office_document", "{}", "可下载文件"),
            ("excel_analysis", "{}", None),
        ],
    )
    def test_wait_messages(self, name, args, marker):
        message = _slow_tool_wait_message(name, args)
        if marker is None:
            assert message is None
        else:
            assert message is not None and marker in message


class TestPostToolRoundHint:
    doc = "generate_office_document"
    docx, xlsx = '{"output_format":"docx"}', '{"output_format":"xlsx"}'
    ok = {"success": True, "download_url": "http://x"}

    @pytest.mark.parametrize(
        "tools,payloads,markers",
        [
            ([(doc, docx)], [ok], ("Word",)),
            ([(doc, xlsx)], [ok], ("Excel",)),
            ([("import_excel_to_database", "{}")], [{"success": True}], ("导入",)),
            (
                [(doc, docx), (doc, xlsx)],
                [ok, {"success": True, "download_url": "http://y"}],
                ("Word", "Excel"),
            ),
            ([(doc, docx)], [{"success": False, "message": "some error"}], ("未成功",)),
            ([(doc, docx)], [{"error": "duplicate_tool_call", "hint": "dup"}], ("未成功",)),
            ([(doc, docx)], [{"success": True}], ("未成功",)),
            ([("import_excel_to_database", "{}")], [{"requires_token": True}], ("工具已返回结果",)),
            ([], [], ("工具已返回结果",)),
            ([("unknown_tool", "{}")], [{}], ("工具已返回结果",)),
        ],
    )
    def test_round_hints(self, tools, payloads, markers):
        tcs = [_Tc(str(index + 1), name, args) for index, (name, args) in enumerate(tools)]
        payloads = json.loads(json.dumps(payloads))
        hint = _post_tool_round_hint(tcs, payloads) if tcs else _post_tool_round_hint([])
        assert all(marker in hint for marker in markers)


class TestPlannerToolsMaxWorkers:
    @pytest.mark.parametrize(
        "value,expected", [(None, 8), ("4", 4), ("abc", 8), ("0", 1), ("100", 32)]
    )
    def test_worker_limits(self, monkeypatch, value, expected):
        if value is None:
            monkeypatch.delenv("FHD_PLANNER_TOOLS_MAX_PARALLEL", raising=False)
        else:
            monkeypatch.setenv("FHD_PLANNER_TOOLS_MAX_PARALLEL", value)
        assert _planner_tools_max_workers() == expected


class TestResetPlannerToolDedupState:
    def test_clears_dedup_set(self):
        from app.legacy.chat.legacy_chat_adapter import _tool_dedup_state

        _tool_dedup_state().add("test_key")
        reset_planner_tool_dedup_state()
        assert len(_tool_dedup_state()) == 0


class TestAppendToolMessages:
    def setup_method(self):
        reset_planner_tool_dedup_state()

    def test_empty_tool_calls_returns_none(self):
        result = append_tool_messages([], [], workspace_root=None, execute_tool=MagicMock())
        assert result is None

    def test_single_tool_serial_execution(self):
        execute_tool = MagicMock(return_value='{"success": true}')
        tcs = [_Tc("tc1", "excel_analysis", '{"query":"test"}')]
        messages: list = []
        result = append_tool_messages(
            messages, tcs, workspace_root="/tmp", execute_tool=execute_tool
        )
        assert result is None
        assert len(messages) == 1
        assert messages[0]["role"] == "tool"
        payload = json.loads(messages[0]["content"])
        assert payload["success"] is True
        last = get_last_tool_result()
        assert last["tool_key"] == "excel_analysis"
        assert last["tool_call_id"] == "tc1"
        assert last["tool_params"] == {"query": "test"}
        assert len(last["_tool_records"]) == 1

    def test_requires_token_returns_early(self):
        execute_tool = MagicMock(
            return_value='{"requires_token": true, "token_name": "DB_WRITE_TOKEN"}'
        )
        tcs = [_Tc("tc1", "import_excel_to_database", "{}")]
        messages: list = []
        result = append_tool_messages(
            messages, tcs, workspace_root="/tmp", execute_tool=execute_tool
        )
        assert result is not None
        assert result.get("requires_token") is True

    def test_duplicate_tool_call(self):
        execute_tool = MagicMock(return_value='{"success": true}')
        tcs = [_Tc("tc1", "excel_analysis", '{"query":"test"}')]
        messages1: list = []
        append_tool_messages(messages1, tcs, workspace_root="/tmp", execute_tool=execute_tool)
        messages2: list = []
        append_tool_messages(messages2, tcs, workspace_root="/tmp", execute_tool=execute_tool)
        payload = json.loads(messages2[0]["content"])
        assert payload.get("error") == "duplicate_tool_call"
        assert payload.get("success") is False

    @pytest.mark.parametrize("tenant_id", [1, 2])
    def test_parallel_execution(self, tenant_id):
        from app.infrastructure.llm.client import (
            get_openai_compatible_client,
            llm_client_scope,
            resolve_chat_model,
        )
        from app.infrastructure.tenant_scope import current_tenant_id, tenant_scope

        client = object()

        def execute_tool(*args, **kwargs):
            assert current_tenant_id() == tenant_id
            assert get_openai_compatible_client() is client
            assert resolve_chat_model() == f"account-{tenant_id}/model"
            return '{"success": true}'

        tcs = [
            _Tc("tc1", "excel_analysis", '{"q":"a"}'),
            _Tc("tc2", "excel_chart_recommend", '{"q":"b"}'),
        ]
        messages: list = []
        with tenant_scope(tenant_id), llm_client_scope(client, f"account-{tenant_id}/model"):
            result = append_tool_messages(
                messages, tcs, workspace_root="/tmp", execute_tool=execute_tool
            )
        assert result is None
        assert len(messages) == 2

    def test_token_sensitive_tools_force_serial(self):
        execute_tool = MagicMock(return_value='{"success": true}')
        tcs = [
            _Tc("tc1", "import_excel_to_database", '{"q":"a"}'),
            _Tc("tc2", "excel_analysis", '{"q":"b"}'),
        ]
        messages: list = []
        result = append_tool_messages(
            messages, tcs, workspace_root="/tmp", execute_tool=execute_tool
        )
        assert result is None
        assert len(messages) == 2

    def test_invalid_json_args_handled(self):
        execute_tool = MagicMock(return_value='{"success": true}')
        tcs = [_Tc("tc1", "excel_analysis", "not json")]
        messages: list = []
        result = append_tool_messages(
            messages, tcs, workspace_root="/tmp", execute_tool=execute_tool
        )
        assert result is None
        assert len(messages) == 1

    def test_enrich_excel_tool_arguments_called(self):
        execute_tool = MagicMock(return_value='{"success": true}')
        tcs = [_Tc("tc1", "excel_analysis", '{"query":"test"}')]
        messages: list = []
        with patch(
            "app.legacy.chat.legacy_chat_adapter.enrich_excel_tool_arguments",
            return_value={"query": "enriched"},
        ) as mock_enrich:
            append_tool_messages(messages, tcs, workspace_root="/tmp", execute_tool=execute_tool)
            mock_enrich.assert_called_once()

    def test_reset_clears_last_tool_records(self):
        execute_tool = MagicMock(return_value='{"success": true}')
        tcs = [_Tc("tc1", "excel_analysis", '{"query":"test"}')]
        append_tool_messages([], tcs, workspace_root="/tmp", execute_tool=execute_tool)

        assert get_last_tool_records()
        reset_planner_tool_dedup_state()

        assert get_last_tool_records() == []
        assert get_last_tool_result() == {}


class TestChat:
    def setup_method(self):
        reset_planner_tool_dedup_state()

    def test_chat_returns_dict_on_text_response(self):
        mock_resp = _chat_response("Hello!", None)
        mock_client = _client(mock_resp)

        with _planner_registry([]):
            result = chat("hi", client=mock_client, model="test-model")
        assert isinstance(result, dict)
        assert result["text"] == "Hello!"

    def test_chat_with_tool_calls(self):
        tc = _Tc("tc1", "excel_analysis", '{"query":"test"}')
        mock_resp1 = _chat_response("", [tc])

        mock_resp2 = _chat_response("Done!", None)

        mock_client = _client([mock_resp1, mock_resp2], side_effect=True)

        execute_tool = MagicMock(return_value='{"success": true}')

        with _planner_tools(execute_tool):
            result = chat("analyze", client=mock_client, model="test-model")
        assert isinstance(result, dict)
        assert "调用工具" in result["thinking_steps"]
        assert result["legacy_tool_records"][0]["tool_id"] == "excel_analysis"
        assert result["legacy_tool_records"][0]["tool_call_id"] == "tc1"
        assert result["legacy_tool_records"][0]["output"]["success"] is True

    @pytest.mark.parametrize("pending", [False, True])
    @pytest.mark.parametrize("iterations", [1, 2])
    def test_chat_max_iterations_reached(self, pending, iterations):
        tc = _Tc("tc1", "excel_analysis", '{"query":"test"}')
        mock_resp = _chat_response("", [tc])
        mock_client = _client(mock_resp)

        execute_tool = MagicMock(
            return_value=json.dumps({"success": not pending, "pending_approval": pending})
        )

        with _planner_tools(execute_tool):
            result = chat(
                "analyze", client=mock_client, model="test-model", max_iterations=iterations
            )
        assert isinstance(result, dict)
        assert ("最大迭代" in result["text"]) is not pending
        assert bool(result.get("pending_approval")) is pending
        assert mock_client.chat.completions.create.call_count == (1 if pending else iterations)

    def test_chat_requires_token_returns_json_string(self):
        tc = _Tc("tc1", "import_excel_to_database", "{}")
        mock_resp = _chat_response("", [tc])
        mock_client = _client(mock_resp)

        execute_tool = MagicMock(
            return_value='{"requires_token": true, "token_name": "DB_WRITE_TOKEN"}'
        )

        with _planner_tools(execute_tool):
            result = chat("import", client=mock_client, model="test-model")
        assert isinstance(result, str)
        data = json.loads(result)
        assert data["requires_token"] is True


class TestChatStreamText:
    def setup_method(self):
        reset_planner_tool_dedup_state()

    def test_yields_text_content(self):
        chunk1 = MagicMock()
        chunk1.choices = [MagicMock()]
        chunk1.choices[0].delta = MagicMock(content="Hello")
        chunk1.choices[0].finish_reason = None

        chunk2 = MagicMock()
        chunk2.choices = [MagicMock()]
        chunk2.choices[0].delta = MagicMock(content=" World")
        chunk2.choices[0].finish_reason = "stop"

        mock_client = _client(iter([chunk1, chunk2]))

        with _planner_registry([]):
            parts = list(chat_stream_text("hi", client=mock_client, model="test-model"))
        assert "Hello" in parts
        assert " World" in parts

    def test_yields_tool_call_label(self):
        chunk = _tool_chunk("excel_analysis", '{"query":"test"}')

        mock_client = _client(iter([chunk]))

        execute_tool = MagicMock(return_value='{"success": true}')

        with _planner_tools(execute_tool):
            parts = list(
                chat_stream_text(
                    "analyze", client=mock_client, model="test-model", max_iterations=1
                )
            )
        text_parts = [p for p in parts if isinstance(p, str)]
        assert any("调用工具" in p for p in text_parts)

    def test_yields_requires_token_dict(self):
        chunk = _tool_chunk("import_excel_to_database", "{}")

        mock_client = _client(iter([chunk]))

        execute_tool = MagicMock(
            return_value='{"requires_token": true, "token_name": "DB_WRITE_TOKEN"}'
        )

        with _planner_tools(execute_tool):
            parts = list(chat_stream_text("import", client=mock_client, model="test-model"))
        dict_parts = [p for p in parts if isinstance(p, dict)]
        assert any(p.get("_planner_sse") == "requires_token" for p in dict_parts)


class TestChatStreamSseEvents:
    def setup_method(self):
        reset_planner_tool_dedup_state()

    def test_terminal_events_carry_worker_tool_records(self, monkeypatch):
        from app.legacy.chat import legacy_chat_adapter as adapter

        record = {
            "tool_name": "execute_erp_capability",
            "success": False,
            "output": {"success": False, "error": "customer not found"},
        }

        def stream(*args, **kwargs):
            adapter._LAST_TOOL_TRACE.records = [record]
            yield "needs customer"

        monkeypatch.setattr(adapter, "chat_stream_text", stream)
        events = list(chat_stream_sse_events("sell"))
        assert events[-1] == {"type": "done", "result": {"legacy_tool_records": [record]}}

    def test_iteration_limit_is_error_instead_of_completed(self):
        events = list(
            chat_stream_sse_events("sell", max_iterations=0, client=MagicMock(), model="test-model")
        )
        assert events[-1]["type"] == "error"
        assert "未完成" in events[-1]["message"]
        assert not any(event["type"] == "done" for event in events)

    def test_yields_token_and_done_events(self):
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta = MagicMock(content="Hi")
        chunk.choices[0].finish_reason = "stop"

        mock_client = _client(iter([chunk]))

        with _planner_registry([]):
            events = list(chat_stream_sse_events("hi", client=mock_client, model="test-model"))
        types = [e["type"] for e in events]
        assert "token" in types
        assert "done" in types

    def test_requires_token_event(self):
        chunk = _tool_chunk("import_excel_to_database", "{}")

        mock_client = _client(iter([chunk]))

        execute_tool = MagicMock(
            return_value='{"requires_token": true, "token_name": "DB_WRITE_TOKEN"}'
        )

        with _planner_tools(execute_tool):
            events = list(chat_stream_sse_events("import", client=mock_client, model="test-model"))
        types = [e["type"] for e in events]
        assert "requires_token" in types


@pytest.mark.parametrize(
    "native, mode",
    [(True, "missing"), (False, "missing"), (True, "explicit"), (True, "fragmented")],
)
def test_market_complete_tool_calls_without_indices_preserve_arguments(monkeypatch, native, mode):
    from app.domain.conversation.legacy_services.modstore_adapter import ModstoreOpenAICompatibleClient

    expected = {
        "business_db_read": {"entity": "customers", "name": "Mac393验收客户"},
        "execute_erp_capability": {"capability": "sales.create_order", "params": {"quantity": 2}},
    }
    calls = [
        {
            "id": name,
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps(args),
            },
        }
        for name, args in expected.items()
    ]
    if mode != "missing":
        for index, call in enumerate(calls):
            call["index"] = index
    chunk = {"choices": [{"delta": {"tool_calls": calls}, "finish_reason": "tool_calls"}]}
    chunks = [chunk]
    if mode == "fragmented":
        partials = [[], []]
        for call in calls:
            function = call["function"]
            arguments = function["arguments"]
            middle = len(arguments) // 2
            for i, part in enumerate([arguments[:middle], arguments[middle:]]):
                partials[i].append(
                    {
                        "index": call["index"],
                        "id": call["id"],
                        "function": {"name": function["name"], "arguments": part},
                    }
                )
        chunks = [
            {
                "choices": [
                    {"delta": {"tool_calls": part}, "finish_reason": "tool_calls" if i else None}
                ]
            }
            for i, part in enumerate(partials)
        ]
    response = {"choices": [{"message": {"tool_calls": calls}, "finish_reason": "tool_calls"}]}
    adapter = SimpleNamespace(
        default_model="test-model",
        default_provider="test",
        model_name="test-model",
        stream_chat_completion_sync=lambda **_: iter(map(json.dumps, chunks)),
        chat_completion_sync=lambda **_: response,
    )
    monkeypatch.setenv("XCAGI_MODSTORE_USE_NATIVE_STREAM", "1" if native else "0")
    observed = {}

    def execute(name, arguments, *_args, **_kwargs):
        observed[name] = json.loads(arguments)
        return json.dumps(
            {
                "success": name == "business_db_read",
                "pending_approval": name == "execute_erp_capability",
                "message": "await approval",
            }
        )

    with (
        patch("app.legacy.chat.legacy_chat_adapter._get_workflow_tool_registry", return_value=[]),
        patch(
            "app.legacy.chat.legacy_chat_adapter._resolve_chat_execute_tool", return_value=execute
        ),
    ):
        parts = list(
            chat_stream_text("创建销售订单，先审批", client=ModstoreOpenAICompatibleClient(adapter))
        )
    assert observed == expected
    assert "await approval" in parts
    assert [r["params"] for r in get_last_tool_records()] == list(expected.values())


_BACKUP_MESSAGE = (
    "请手动备份当前隔离验收数据库，使用正常数据库备份功能，包含刚刚的客户、商品以及销售订单SO20261009083703。"
    "只生成数据库备份，不恢复、不修改业务数据。需要审批时先提交手动审批。"
)


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "case", ["missing", "read", "read_pending", "wrong_action", "failed", "pending", "success"]
)
def test_backup_requires_matching_executor_receipt(stream, case):
    name = "business_db_read" if case.startswith("read") else "execute_erp_capability"
    if case == "missing":
        name = None
    action = "restore_database" if case == "wrong_action" else "backup_database"
    output = {
        "success": case in ("read", "success"),
        "pending_approval": case in ("read_pending", "wrong_action", "pending"),
    }
    ready = case in ("pending", "success")
    fake = "备份操作已成功提交，审批单号79b74e314847452fbb07b49c8c7b291f"
    output = {**output, "message": "executor-fixture实际回执"}
    args = {"tool_id": "system_maintenance", "action": action, "params": {}}
    tc = _Tc("backup-call", name, json.dumps(args)) if name else None
    if tc:
        tc.index = 0
    delta = SimpleNamespace(content=fake, tool_calls=[tc] if tc else [])
    client = MagicMock(is_modstore_openai_compatible=False)
    response = _chat_response(fake, [tc] if tc else [])
    client.chat.completions.create.return_value = (
        iter([SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason="stop")])])
        if stream
        else response
    )
    execute = MagicMock(return_value=json.dumps(output))
    context = {"actor_id": 2, "tenant_id": 1, "task_id": "isolated-backup-fixture"}
    kwargs = {"client": client, "model": "test", "runtime_context": context}
    tools = [{"type": "function", "function": {"name": "execute_erp_capability"}}]
    with (
        _planner_registry(tools),
        patch.object(adapter, "_resolve_chat_execute_tool", return_value=execute),
    ):
        if stream:
            result = list(chat_stream_sse_events(_BACKUP_MESSAGE, **kwargs))
            assert result[-1]["type"] == ("done" if ready else "error")
        elif ready:
            result = chat(_BACKUP_MESSAGE, **kwargs)
        else:
            with pytest.raises(RuntimeError, match="未执行"):
                chat(_BACKUP_MESSAGE, **kwargs)
            result = []
    assert fake not in str(result)
    assert client.chat.completions.create.call_count == 1
    assert client.chat.completions.create.call_args.kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": "execute_erp_capability"},
    }
    assert execute.call_count == bool(name)
    if name:
        assert json.loads(execute.call_args.args[1]) == args
        assert execute.call_args.kwargs["runtime_context"] == context
    if ready:
        assert "executor-fixture实际回执" in str(result)
        assert get_last_tool_records()[0]["output"] == output


@pytest.mark.parametrize(
    "message",
    [
        "请不要备份数据库",
        "请解释如何备份数据库",
        "请查看数据库备份列表",
        "请恢复数据库备份",
        "请把数据库备份删除",
    ],
)
def test_backup_read_explanation_negative_restore_and_delete_stay_normal(message):
    client = MagicMock(is_modstore_openai_compatible=False)
    client.chat.completions.create.return_value = _chat_response("说明")
    with _planner_registry([{"type": "function", "function": {"name": "execute_erp_capability"}}]):
        assert chat(message, client=client, model="test")["text"] == "说明"
    assert client.chat.completions.create.call_args.kwargs["tool_choice"] == "auto"
