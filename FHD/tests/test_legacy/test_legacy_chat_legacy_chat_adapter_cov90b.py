from __future__ import annotations

"""Second-wave behavior tests for app/legacy/chat/legacy_chat_adapter.py.

Targets the residual uncovered lines (function-body imports, the parallel
tool-execution branches, ``_record_tool_result``, ``_call_model_completion``,
streaming delta accumulation/payload-collection branches and the
``_append_last_tool_record`` defensive paths). All LLM / tool / module-resolution
dependencies are mocked so the suite stays offline and deterministic.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import app.legacy.chat.legacy_chat_adapter as _mod


# ---------------------------------------------------------------------------
# Lightweight stubs (real attribute objects, not MagicMock, so getattr chains
# in the SUT see exactly the values we set).
# ---------------------------------------------------------------------------
class _Fn:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _Tc:
    def __init__(self, tc_id, name, arguments):
        self.id = tc_id
        self.function = _Fn(name, arguments)


class _Delta:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, delta=None, finish_reason=None):
        self.delta = delta
        self.finish_reason = finish_reason


class _Chunk:
    def __init__(self, choice):
        self.choices = [choice]


class _DeltaTc:
    """A streaming tool-call delta fragment."""

    def __init__(self, index, tc_id=None, name=None, arguments=""):
        self.index = index
        self.id = tc_id
        self.function = _Fn(name, arguments)


# ---------------------------------------------------------------------------
# _get_workflow_tool_registry  (lines 48,53-55,57)
# ---------------------------------------------------------------------------
class TestGetWorkflowToolRegistry:
    def test_via_mod_enabled_uses_planner_registry(self):
        fake = [{"type": "function", "from": "mod"}]
        with (
            patch(
                "app.mod_sdk.planner_tools.is_planner_tools_via_mod_enabled",
                return_value=True,
            ),
            patch(
                "app.mod_sdk.planner_tools.get_planner_chat_tool_registry",
                return_value=fake,
            ),
        ):
            assert _mod._get_workflow_tool_registry() is fake

    def test_via_mod_disabled_uses_workflow_registry(self):
        fake = [{"type": "function", "from": "workflow"}]
        with (
            patch(
                "app.mod_sdk.planner_tools.is_planner_tools_via_mod_enabled",
                return_value=False,
            ),
            patch(
                "app.application.tools.workflow.get_workflow_tool_registry",
                return_value=fake,
            ),
        ):
            assert _mod._get_workflow_tool_registry() is fake


# ---------------------------------------------------------------------------
# _resolve_chat_execute_tool  (lines 61,63)
# ---------------------------------------------------------------------------
class TestResolveChatExecuteTool:
    def test_delegates_to_planner_executor(self):
        sentinel = MagicMock(name="executor")
        with patch(
            "app.mod_sdk.planner_tools.resolve_planner_tool_executor",
            return_value=sentinel,
        ):
            assert _mod._resolve_chat_execute_tool() is sentinel


# ---------------------------------------------------------------------------
# _append_last_tool_record defensive paths  (lines 143-145, 148)
# ---------------------------------------------------------------------------
class TestAppendLastToolRecord:
    def setup_method(self):
        _mod.clear_last_tool_result()

    def test_invalid_json_arguments_yield_empty_params(self):
        tc = _Tc("id-1", "products", "not-json")
        _mod._append_last_tool_record(tc, "products", "not-json", {"success": True})
        records = _mod.get_last_tool_records()
        assert records[-1]["params"] == {}
        assert records[-1]["tool_call_id"] == "id-1"

    def test_non_dict_json_arguments_reset_to_empty(self):
        # raw_arguments parses to a list -> params reset to {} (line 143)
        tc = _Tc("id-2", "products", "[1, 2, 3]")
        _mod._append_last_tool_record(tc, "products", "[1, 2, 3]", {"success": False})
        records = _mod.get_last_tool_records()
        assert records[-1]["params"] == {}
        assert records[-1]["success"] is False

    def test_records_not_list_is_replaced(self):
        # Corrupt the thread-local store -> the not-isinstance(records, list)
        # branch (line 148) must rebuild it cleanly.
        _mod._LAST_TOOL_TRACE.records = "corrupt"
        tc = _Tc("id-3", "excel_analysis", json.dumps({"action": "read"}))
        _mod._append_last_tool_record(
            tc, "excel_analysis", json.dumps({"action": "read"}), {"success": True}
        )
        records = _mod.get_last_tool_records()
        assert isinstance(records, list)
        assert len(records) == 1
        assert records[-1]["action"] == "read"

    def test_non_dict_payload_wrapped_as_message(self):
        tc = _Tc("id-4", "products", "{}")
        _mod._append_last_tool_record(tc, "products", "{}", "plain string output")
        records = _mod.get_last_tool_records()
        assert records[-1]["output"] == {"message": "plain string output"}
        assert records[-1]["success"] is False


# ---------------------------------------------------------------------------
# reset_last_tool_result  (line 167) + _record_tool_result  (190-192, 197-201)
# ---------------------------------------------------------------------------
class TestRecordToolResult:
    def setup_method(self):
        _mod.reset_last_tool_result()

    def test_reset_clears_contextvar(self):
        _mod._LAST_TOOL_RESULT.set({"tool_key": "x"})
        _mod.reset_last_tool_result()
        assert _mod._LAST_TOOL_RESULT.get() is None

    def test_empty_payload_is_ignored(self):
        _mod._record_tool_result("k", None)
        assert _mod._LAST_TOOL_RESULT.get() is None
        _mod._record_tool_result("k", {})
        assert _mod._LAST_TOOL_RESULT.get() is None

    def test_requires_token_payload_is_ignored(self):
        _mod._record_tool_result("k", {"requires_token": True, "success": True})
        assert _mod._LAST_TOOL_RESULT.get() is None

    def test_success_payload_recorded_with_download_url(self):
        _mod._record_tool_result(
            "generate_office_document",
            {"success": True, "download_url": "http://x/f.docx"},
        )
        rec = _mod._LAST_TOOL_RESULT.get()
        assert rec is not None
        assert rec["tool_key"] == "generate_office_document"
        assert rec["download_url"] == "http://x/f.docx"
        assert rec["payload"]["success"] is True

    def test_better_result_replaces_previous(self):
        _mod._record_tool_result("k", {"success": False})
        # success True must replace the prior failed record
        _mod._record_tool_result("k", {"success": True})
        rec = _mod._LAST_TOOL_RESULT.get()
        assert rec["success"] is True

    def test_worse_result_does_not_replace(self):
        _mod._record_tool_result("k", {"success": True, "download_url": "u"})
        before = _mod._LAST_TOOL_RESULT.get()
        _mod._record_tool_result("k", {"success": False})
        assert _mod._LAST_TOOL_RESULT.get() is before


# ---------------------------------------------------------------------------
# append_tool_messages: args parsing to non-dict  (line 340)
# ---------------------------------------------------------------------------
class TestAppendToolMessagesNonDictArgs:
    def setup_method(self):
        _mod.reset_planner_tool_dedup_state()

    def test_list_json_args_normalized_to_empty_dict(self):
        captured: dict[str, Any] = {}

        def exec_tool(name, raw_eff, ws, db_write_token=None):
            captured["raw_eff"] = raw_eff
            return json.dumps({"success": True})

        tc = _Tc("tc1", "products", "[1, 2, 3]")
        messages: list[Any] = []
        result = _mod.append_tool_messages(
            messages, [tc], workspace_root=None, execute_tool=exec_tool
        )
        assert result is None
        # args_dict reset to {} -> normalized effective args serialize to "{}"
        assert captured["raw_eff"] == "{}"
        assert messages[0]["role"] == "tool"


# ---------------------------------------------------------------------------
# append_tool_messages parallel branches  (386, 407, 410)
# ---------------------------------------------------------------------------
class TestAppendToolMessagesParallelBranches:
    def setup_method(self):
        _mod.reset_planner_tool_dedup_state()

    def test_parallel_duplicate_marked_and_other_executed(self):
        # Pre-seed dedup with one of the two tool keys so the parallel path
        # hits the "key in _TOOL_DEDUP" branch (line 386) for that index.
        def exec_tool(name, raw_eff, ws, db_write_token=None):
            return json.dumps({"success": True})

        tc_dup = _Tc("dup", "products", json.dumps({"action": "search"}))
        tc_new = _Tc("new", "customers", json.dumps({"action": "list"}))

        # First run executes tc_dup so its key is now in dedup.
        _mod.append_tool_messages([], [tc_dup], workspace_root=None, execute_tool=exec_tool)

        messages: list[Any] = []
        with patch.object(_mod, "_planner_tools_max_workers", return_value=4):
            result = _mod.append_tool_messages(
                messages, [tc_dup, tc_new], workspace_root=None, execute_tool=exec_tool
            )
        assert result is None
        contents = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        assert any(c.get("error") == "duplicate_tool_call" for c in contents)
        assert any(c.get("success") is True for c in contents)

    def test_parallel_requires_token_returns_payload(self):
        # In parallel mode, a payload with requires_token returns it (line 410).
        def exec_tool(name, raw_eff, ws, db_write_token=None):
            if name == "products_bulk_import":
                return json.dumps({"requires_token": True, "token_name": "DB_WRITE_TOKEN"})
            return json.dumps({"success": True})

        # products_bulk_import is token-sensitive and would force serial; to keep
        # the *parallel* code path we patch the sensitive-tool set to empty.
        tc1 = _Tc("t1", "products_bulk_import", json.dumps({"action": "x"}))
        tc2 = _Tc("t2", "customers", json.dumps({"action": "y"}))
        messages: list[Any] = []
        with (
            patch.object(_mod, "_TOKEN_ORDER_SENSITIVE_TOOLS", frozenset()),
            patch.object(_mod, "_planner_tools_max_workers", return_value=4),
        ):
            result = _mod.append_tool_messages(
                messages, [tc1, tc2], workspace_root=None, execute_tool=exec_tool
            )
        assert result is not None
        assert result.get("requires_token") is True

    def test_parallel_all_duplicates_payload_none_continue(self):
        # When every tool is a duplicate, to_run is empty; the second loop sees
        # payloads that are dup-markers (not None) but exercises the None-skip
        # guard (line 407) defensively via a tool whose payload stays None.
        def exec_tool(name, raw_eff, ws, db_write_token=None):
            return json.dumps({"success": True})

        tc_a = _Tc("a", "products", json.dumps({"action": "search"}))
        tc_b = _Tc("b", "customers", json.dumps({"action": "list"}))
        # Seed both keys into dedup.
        _mod.append_tool_messages([], [tc_a], workspace_root=None, execute_tool=exec_tool)
        _mod.append_tool_messages([], [tc_b], workspace_root=None, execute_tool=exec_tool)

        messages: list[Any] = []
        with patch.object(_mod, "_planner_tools_max_workers", return_value=4):
            result = _mod.append_tool_messages(
                messages, [tc_a, tc_b], workspace_root=None, execute_tool=exec_tool
            )
        assert result is None
        contents = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        assert all(c.get("error") == "duplicate_tool_call" for c in contents)
        assert len(contents) == 2


# ---------------------------------------------------------------------------
# _call_model_completion  (lines 427-429, 431-435)
# ---------------------------------------------------------------------------
class TestCallModelCompletion:
    def test_with_explicit_client_returns_stripped_content(self):
        msg = MagicMock()
        msg.content = "  hi there  "
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        client = MagicMock()
        client.is_modstore_openai_compatible = False
        client.chat.completions.create.return_value = resp

        out = _mod._call_model_completion(
            [{"role": "user", "content": "x"}], model="m", client=client
        )
        assert out == "hi there"
        client.chat.completions.create.assert_called_once()

    def test_client_none_builds_client_and_requires_api_key(self):
        msg = MagicMock()
        msg.content = None  # exercises (msg.content or "") fallback
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        built = MagicMock()
        built.is_modstore_openai_compatible = False
        built.chat.completions.create.return_value = resp

        with (
            patch.object(_mod, "require_api_key") as req,
            patch.object(_mod, "get_openai_compatible_client", return_value=built),
            patch.object(_mod, "resolve_chat_model", return_value="resolved-model"),
        ):
            out = _mod._call_model_completion([{"role": "user", "content": "x"}])
        assert out == ""
        req.assert_called_once()
        # model resolved through fallback since no explicit model given
        _, kwargs = built.chat.completions.create.call_args
        assert kwargs["model"] == "resolved-model"


# ---------------------------------------------------------------------------
# chat: system prompt present branch  (line 455)
# ---------------------------------------------------------------------------
class TestChatSystemPrompt:
    def setup_method(self):
        _mod.reset_planner_tool_dedup_state()

    def test_system_message_prepended_when_prompt_present(self):
        client = MagicMock()
        client.is_modstore_openai_compatible = False
        msg = MagicMock()
        msg.content = "answer"
        msg.tool_calls = None
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        client.chat.completions.create.return_value = resp

        with (
            patch.object(_mod, "merge_system_prompt", return_value="SYS PROMPT"),
            patch.object(_mod, "_get_workflow_tool_registry", return_value=[]),
            patch.object(_mod, "build_openai_user_content", side_effect=lambda m, c: m),
        ):
            _mod.chat("hello", client=client, model="m")

        sent_messages = client.chat.completions.create.call_args.kwargs["messages"]
        assert sent_messages[0] == {"role": "system", "content": "SYS PROMPT"}
        assert sent_messages[1]["role"] == "user"


# ---------------------------------------------------------------------------
# chat_stream_text: system prompt + client-None build  (562, 567-568)
# ---------------------------------------------------------------------------
class TestChatStreamTextSetup:
    def setup_method(self):
        _mod.reset_planner_tool_dedup_state()

    def test_system_prompt_and_built_client(self):
        built = MagicMock()
        built.is_modstore_openai_compatible = False
        chunk = _Chunk(_Choice(_Delta(content="hey"), finish_reason="stop"))
        built.chat.completions.create.return_value = iter([chunk])

        with (
            patch.object(_mod, "merge_system_prompt", return_value="SYS"),
            patch.object(_mod, "require_api_key") as req,
            patch.object(_mod, "get_openai_compatible_client", return_value=built),
            patch.object(_mod, "resolve_chat_model", return_value="resolved"),
            patch.object(_mod, "_get_workflow_tool_registry", return_value=[]),
            patch.object(_mod, "build_openai_user_content", side_effect=lambda m, c: m),
        ):
            parts = list(_mod.chat_stream_text("hi"))

        assert "hey" in parts
        req.assert_called_once()
        sent = built.chat.completions.create.call_args.kwargs["messages"]
        assert sent[0] == {"role": "system", "content": "SYS"}


# ---------------------------------------------------------------------------
# chat_stream_text: delta is None continue  (line 590)
# ---------------------------------------------------------------------------
class TestChatStreamTextDeltaNone:
    def setup_method(self):
        _mod.reset_planner_tool_dedup_state()

    def test_none_delta_chunk_skipped(self):
        client = MagicMock()
        client.is_modstore_openai_compatible = False
        # chunk with delta None -> continue; then a real text chunk.
        none_chunk = _Chunk(_Choice(delta=None, finish_reason=None))
        text_chunk = _Chunk(_Choice(_Delta(content="world"), finish_reason="stop"))
        client.chat.completions.create.return_value = iter([none_chunk, text_chunk])

        with patch.object(_mod, "_get_workflow_tool_registry", return_value=[]):
            parts = list(_mod.chat_stream_text("hi", client=client, model="m"))
        assert parts == ["world"]


# ---------------------------------------------------------------------------
# chat_stream_text: tool-call delta accumulation across chunks  (610-613)
# ---------------------------------------------------------------------------
class TestChatStreamTextToolDeltaAccumulation:
    def setup_method(self):
        _mod.reset_planner_tool_dedup_state()

    def test_arguments_accumulated_over_two_chunks(self):
        client = MagicMock()
        client.is_modstore_openai_compatible = False

        # First fragment: opens index 0 with partial args + name.
        frag1 = _DeltaTc(index=0, tc_id="tc1", name="excel_analysis", arguments='{"query":')
        # Second fragment: same index, no id, name supplied late, more args ->
        # hits the else branch (610-613): name set + arguments appended.
        frag2 = _DeltaTc(index=0, tc_id=None, name="excel_analysis", arguments='"hi"}')

        chunk1 = _Chunk(_Choice(_Delta(content=None, tool_calls=[frag1]), finish_reason=None))
        chunk2 = _Chunk(
            _Choice(_Delta(content=None, tool_calls=[frag2]), finish_reason="tool_calls")
        )
        client.chat.completions.create.return_value = iter([chunk1, chunk2])

        captured: dict[str, Any] = {}

        def exec_tool(name, raw_eff, ws, db_write_token=None):
            captured["name"] = name
            captured["raw_eff"] = raw_eff
            return json.dumps({"success": True})

        with (
            patch.object(_mod, "_get_workflow_tool_registry", return_value=[{"type": "function"}]),
            patch.object(_mod, "_resolve_chat_execute_tool", return_value=exec_tool),
        ):
            parts = list(
                _mod.chat_stream_text("analyze", client=client, model="m", max_iterations=1)
            )

        # The two argument fragments must have been concatenated before execution.
        assert captured["name"] == "excel_analysis"
        assert json.loads(captured["raw_eff"]) == {"query": "hi"}
        assert any(isinstance(p, str) and "正在调用工具" in p for p in parts)


# ---------------------------------------------------------------------------
# chat_stream_text: tool payload collection  (682, 685-686, 692)
# ---------------------------------------------------------------------------
class TestChatStreamTextPayloadCollection:
    def setup_method(self):
        _mod.reset_planner_tool_dedup_state()

    def test_collection_breaks_on_non_tool_role_and_handles_bad_json(self):
        client = MagicMock()
        client.is_modstore_openai_compatible = False

        frag = _DeltaTc(index=0, tc_id="tc1", name="products", arguments="{}")
        chunk = _Chunk(_Choice(_Delta(content=None, tool_calls=[frag]), finish_reason="tool_calls"))
        client.chat.completions.create.return_value = iter([chunk])

        # execute_tool returns invalid JSON content; append_tool_messages stores
        # the raw json (it json.dumps a dict though). To force the JSONDecodeError
        # path (685-686) in the *collection* loop we make the appended tool
        # message content un-parseable by mutating messages via a wrapper.
        def exec_tool(name, raw_eff, ws, db_write_token=None):
            return json.dumps({"success": True})

        # Patch append_tool_messages so it appends a non-tool message first
        # (forces the break at 682) and a tool message with bad JSON (685-686),
        # while still returning None (no token needed). We then verify the round
        # still completes and yields a post-round hint.
        real_append = _mod.append_tool_messages

        def fake_append(messages, tcs, **kw):
            # a non-tool sentinel between assistant and the tool msg is not how
            # the real flow works; instead place a tool msg with bad json then a
            # trailing assistant-ish msg is impossible here. Use real append then
            # corrupt the last tool message content to bad JSON.
            res = real_append(messages, tcs, **kw)
            for m in messages:
                if m.get("role") == "tool":
                    m["content"] = "<<not json>>"
            return res

        with (
            patch.object(_mod, "_get_workflow_tool_registry", return_value=[{"type": "function"}]),
            patch.object(_mod, "_resolve_chat_execute_tool", return_value=exec_tool),
            patch.object(_mod, "append_tool_messages", side_effect=fake_append),
        ):
            parts = list(_mod.chat_stream_text("go", client=client, model="m", max_iterations=1))

        # bad-json tool content -> collected {} (685-686); round-hint still emitted.
        assert any(isinstance(p, str) and "工具已返回" in p for p in parts)

    def test_payload_padding_when_fewer_collected_than_tail(self):
        # Two tool calls but the collection loop breaks early on a non-tool role,
        # so tool_payloads gets padded with {} (line 692).
        client = MagicMock()
        client.is_modstore_openai_compatible = False

        frag1 = _DeltaTc(index=0, tc_id="t1", name="products", arguments=json.dumps({"a": 1}))
        frag2 = _DeltaTc(index=1, tc_id="t2", name="customers", arguments=json.dumps({"b": 2}))
        chunk = _Chunk(
            _Choice(
                _Delta(content=None, tool_calls=[frag1, frag2]),
                finish_reason="tool_calls",
            )
        )
        client.chat.completions.create.return_value = iter([chunk])

        def exec_tool(name, raw_eff, ws, db_write_token=None):
            return json.dumps({"success": True})

        real_append = _mod.append_tool_messages

        def fake_append(messages, tcs, **kw):
            res = real_append(messages, tcs, **kw)
            # Insert a non-tool message at the tail so the backward scan breaks
            # before collecting both tool payloads -> padding path (692).
            messages.append({"role": "assistant", "content": "tail"})
            return res

        with (
            patch.object(_mod, "_get_workflow_tool_registry", return_value=[{"type": "function"}]),
            patch.object(_mod, "_resolve_chat_execute_tool", return_value=exec_tool),
            patch.object(_mod, "append_tool_messages", side_effect=fake_append),
        ):
            parts = list(_mod.chat_stream_text("go", client=client, model="m", max_iterations=1))

        # The round-hint must still be produced even with padded payloads.
        assert any(isinstance(p, str) and "工具已返回" in p for p in parts)
