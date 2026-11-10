"""Real legacy runtime/adapter with synthetic completions and zero business writes."""

import json
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from app.fastapi_routes.domains.conversation.reply_helpers import _xcagi_compat_reply_payload
from app.legacy.chat import legacy_chat_adapter as adapter


def tool(index=0):
    return NS(
        index=index,
        id=f"synthetic-{index}",
        function=NS(name="fixture_read", arguments=json.dumps({"index": index})),
    )


def response(text="", calls=None):
    return NS(choices=[NS(message=NS(content=text, tool_calls=calls or []))])


def chunk(text="", calls=None, finish="stop"):
    return NS(choices=[NS(delta=NS(content=text, tool_calls=calls or []), finish_reason=finish)])


@pytest.fixture
def fixture_tools(monkeypatch):
    execute = Mock(return_value=json.dumps({"success": True, "data": {"count": 0}}))
    monkeypatch.setattr(
        adapter,
        "_get_workflow_tool_registry",
        lambda: [{"type": "function", "function": {"name": "fixture_read"}}],
    )
    monkeypatch.setattr(adapter, "_resolve_chat_execute_tool", lambda: execute)
    return execute


def client(factory):
    create = Mock(side_effect=factory)
    return NS(is_modstore_openai_compatible=False, chat=NS(completions=NS(create=create)))


def run(cli, stream, budget=8):
    if stream:
        events = list(
            adapter.chat_stream_sse_events(
                "synthetic request", client=cli, model="synthetic", max_iterations=budget
            )
        )
        assert events[-1]["type"] == "error"
        assert not any(event["type"] == "done" for event in events)
        return events[-1]["result"]
    return adapter.chat("synthetic request", client=cli, model="synthetic", max_iterations=budget)


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("text", ["", "  \n"])
def test_empty_answer_fails_once_not_eight_paid_retries(fixture_tools, stream, text):
    cli = client(lambda **_: iter([chunk(text)]) if stream else response(text))
    result = run(cli, stream)
    assert result["success"] is False
    assert result["error"] == "planner_empty_response"
    assert "最大迭代" not in result["message"]
    assert cli.chat.completions.create.call_count == 1
    fixture_tools.assert_not_called()


@pytest.mark.parametrize("stream", [False, True])
def test_duplicate_tool_stops_without_reexecuting_or_hiding_partial_success(fixture_tools, stream):
    cli = client(
        lambda **_: (
            iter([chunk(calls=[tool()], finish="tool_calls")])
            if stream
            else response(calls=[tool()])
        )
    )
    result = run(cli, stream)
    assert result["success"] is False
    assert result["error"] == "planner_no_progress"
    assert cli.chat.completions.create.call_count == 2
    fixture_tools.assert_called_once()
    records = result["legacy_tool_records"]
    assert len(records) == 2
    assert records[0]["output"]["success"] is True
    assert records[1]["output"]["error"] == "duplicate_tool_call"
    projected = _xcagi_compat_reply_payload(result)
    assert projected["success"] is False
    assert projected["error"] == "planner_no_progress"
    assert projected["data"]["legacy_tool_records"] == records


def test_usage_only_frames_are_ignored_without_index_error(fixture_tools):
    cli = client(lambda **_: iter([NS(choices=[]), chunk("synthetic answer"), NS(choices=[])]))
    events = list(adapter.chat_stream_sse_events("synthetic", client=cli, model="synthetic"))
    assert [event["type"] for event in events] == ["model_activity", "token", "done"]
    assert events[1]["text"] == "synthetic answer"
    fixture_tools.assert_not_called()


def test_buffered_model_activity_is_emitted_before_the_model_finishes(fixture_tools):
    def chunks():
        yield chunk("初稿。", finish=None)
        raise ValueError("upstream interrupted")

    events = adapter.chat_stream_sse_events(
        "synthetic", client=client(lambda **_: chunks()), model="synthetic"
    )
    assert next(events) == {"type": "model_activity"}
    with pytest.raises(ValueError, match="upstream interrupted"):
        next(events)


def test_explicit_explanation_streams_before_completion_without_tools(fixture_tools):
    def chunks():
        yield chunk("第一段", finish=None)
        raise ValueError("upstream interrupted")

    cli = client(lambda **_: chunks())
    events = adapter.chat_stream_sse_events(
        "请简要解释 HTTPS 是什么，不要调用工具。", client=cli, model="synthetic"
    )
    assert next(events) == {"type": "token", "text": "第一段"}
    assert cli.chat.completions.create.call_args.kwargs["tools"] is None
    assert next(events) == {"type": "model_activity"}
    with pytest.raises(ValueError, match="upstream interrupted"):
        next(events)
    fixture_tools.assert_not_called()


def test_explicit_explanation_rejects_unexpected_tool_calls(fixture_tools):
    cli = client(lambda **_: iter([chunk(calls=[tool()], finish="tool_calls")]))
    events = list(adapter.chat_stream_sse_events("解释 DNS 是什么", client=cli, model="synthetic"))
    assert any(event["type"] == "error" for event in events)
    fixture_tools.assert_not_called()


def test_failed_tool_return_does_not_claim_completed(fixture_tools):
    fixture_tools.return_value = json.dumps({"success": False, "message": "拒绝"})
    rounds = iter([iter([chunk(calls=[tool()], finish="tool_calls")]), iter([chunk("未成功。")])])
    events = list(
        adapter.chat_stream_sse_events(
            "synthetic", client=client(lambda **_: next(rounds)), model="synthetic"
        )
    )
    progress = [event for event in events if event["type"] == "tool_progress"]
    assert progress[-1]["phase"] != "completed"


def test_tool_messages_are_progress_events_not_answer_tokens(fixture_tools, monkeypatch):
    monkeypatch.setattr(adapter, "_slow_tool_wait_message", lambda *_: "等待工具完成。")
    rounds = iter([iter([chunk(calls=[tool()], finish="tool_calls")]), iter([chunk("最终答案。")])])
    events = list(
        adapter.chat_stream_sse_events(
            "synthetic", client=client(lambda **_: next(rounds)), model="synthetic"
        )
    )
    progress = [event for event in events if event["type"] == "tool_progress"]
    assert len(progress) == 3
    assert "正在调用工具" in progress[0]["text"]
    assert "等待工具完成" in progress[1]["text"]
    assert "工具已返回" in progress[2]["text"]
    assert [event["text"] for event in events if event["type"] == "token"] == ["最终答案。"]


def test_model_text_before_tool_call_is_not_emitted_as_answer(fixture_tools):
    rounds = iter(
        [
            iter([chunk("先检查数据。"), chunk(calls=[tool()], finish="tool_calls")]),
            iter([chunk("最终答案。")]),
        ]
    )
    events = list(
        adapter.chat_stream_sse_events(
            "synthetic", client=client(lambda **_: next(rounds)), model="synthetic"
        )
    )
    assert [event["text"] for event in events if event["type"] == "token"] == ["最终答案。"]
    assert any(event["type"] == "tool_progress" for event in events)


@pytest.mark.parametrize(
    "marker",
    ["[正在调用工具: 搜索]", "【工具已返回结果】", "（正在生成 Word 文档（.docx），请稍候。）"],
)
def test_legacy_progress_markers_are_not_answer_tokens(monkeypatch, marker):
    monkeypatch.setattr(adapter, "chat_stream_text", lambda *a, **k: iter([marker, "最终答案。 "]))
    events = list(adapter.chat_stream_sse_events("synthetic"))
    assert events[0]["type"] == "tool_progress"
    assert events[0]["text"] == marker
    assert events[1] == {"type": "token", "text": "最终答案。 "}


@pytest.mark.parametrize(
    "marker",
    ["[正在调用工具：搜索]", "【工具已返回结果】", "（正在生成 Word 文档（.docx），请稍候。）"],
)
def test_split_legacy_progress_marker_is_not_an_answer_token(monkeypatch, marker):
    monkeypatch.setattr(adapter, "chat_stream_text", lambda *a, **k: iter([*marker, "最终答案。 "]))
    events = list(adapter.chat_stream_sse_events("synthetic"))
    assert [event["text"] for event in events if event["type"] == "token"] == ["最终答案。 "]
    assert any(event["type"] == "tool_progress" and event["text"] == marker for event in events)


def test_partial_marker_at_interruption_is_not_emitted_as_answer(monkeypatch):
    monkeypatch.setattr(
        adapter,
        "chat_stream_text",
        lambda *a, **k: iter(
            [
                "正文。 [正在调用工",
                {"_planner_sse": "error", "message": "连接失败"},
            ]
        ),
    )
    events = list(adapter.chat_stream_sse_events("synthetic"))
    assert "".join(event["text"] for event in events if event["type"] == "token") == "正文。 "
    assert events[-1]["type"] == "error"


@pytest.mark.parametrize(
    "prompt,answer",
    [
        ("UX体验测试：只回复‘测试成功’，不要执行任何业务操作。", "测试成功"),
        ("UX复测：你好，请用一句话介绍你能做什么。仅回答，不执行操作。", "我可以帮你查询资料。"),
    ],
)
def test_report_prompts_receive_visible_market_stream_answers(
    fixture_tools, monkeypatch, prompt, answer
):
    from app.domain.shared_services.conversation import modstore_adapter as market

    platform = market.ModstorePlatformAdapter(
        platform_url="https://market.invalid", auth_token="synthetic"
    )
    wire = NS(
        iter_lines=lambda: iter(
            [
                "event: delta",
                f"data: {json.dumps({'delta': answer})}",
                "",
                "event: done",
                f"data: {json.dumps({'ok': True, 'content': answer})}",
                "",
            ]
        )
    )
    upstream = Mock(side_effect=lambda **kwargs: market._iter_market_sse_data_payloads(wire))
    monkeypatch.setattr(platform, "stream_chat_completion_sync", upstream)
    cli = market.ModstoreOpenAICompatibleClient(platform)
    events = list(adapter.chat_stream_sse_events(prompt, client=cli, model="synthetic"))
    assert events[-1]["type"] == "done"
    assert "".join(event["text"] for event in events if event["type"] == "token") == answer
    upstream.assert_called_once()
    fixture_tools.assert_not_called()


@pytest.mark.parametrize("stream", [False, True])
def test_missing_choices_is_explicit_empty_failure(fixture_tools, stream):
    cli = client(lambda **_: iter([NS(choices=[])]) if stream else NS(choices=[]))
    assert run(cli, stream)["error"] == "planner_empty_response"
    assert cli.chat.completions.create.call_count == 1


def test_tool_finish_without_a_call_is_not_retried(fixture_tools):
    cli = client(lambda **_: iter([chunk(finish="tool_calls")]))
    assert run(cli, True)["error"] == "planner_invalid_tool_call"
    fixture_tools.assert_not_called()
    assert cli.chat.completions.create.call_count == 1


@pytest.mark.parametrize("stream", [False, True])
def test_real_progress_still_obeys_original_iteration_budget(fixture_tools, stream):
    index = 0

    def create(**kwargs):
        nonlocal index
        index += 1
        calls = [tool(index)]
        return iter([chunk(calls=calls, finish="tool_calls")]) if stream else response(calls=calls)

    cli = client(create)
    result = run(cli, stream, budget=3)
    assert result["error"] == "planner_iteration_limit"
    assert result["success"] is False
    assert cli.chat.completions.create.call_count == fixture_tools.call_count == 3
    assert all(record["output"]["success"] for record in result["legacy_tool_records"])
    assert _xcagi_compat_reply_payload(result)["success"] is False


@pytest.mark.parametrize("stream", [False, True])
def test_new_turn_resets_budget_and_dedup_but_preserves_tool_receipt(fixture_tools, stream):
    turn = 0

    def create(**kwargs):
        nonlocal turn
        turn += 1
        if turn % 2:
            return (
                iter([chunk(calls=[tool()], finish="tool_calls")])
                if stream
                else response(calls=[tool()])
            )
        return iter([chunk("synthetic answer")]) if stream else response("synthetic answer")

    cli = client(create)
    for _ in range(2):
        if stream:
            events = list(
                adapter.chat_stream_sse_events(
                    "synthetic", client=cli, model="synthetic", max_iterations=2
                )
            )
            assert events[-1]["type"] == "done"
            result = events[-1]["result"]
        else:
            result = adapter.chat("synthetic", client=cli, model="synthetic", max_iterations=2)
            assert result["text"] == "synthetic answer"
        assert len(result["legacy_tool_records"]) == 1
    assert fixture_tools.call_count == 2
    assert cli.chat.completions.create.call_count == 4


@pytest.mark.parametrize("stream", [False, True])
def test_mixed_duplicate_and_new_tool_is_still_progress(fixture_tools, stream):
    index = 0

    def create(**kwargs):
        nonlocal index
        index += 1
        calls = [tool()] if index == 1 else [tool(), tool(1)] if index == 2 else []
        text = "synthetic answer" if index == 3 else ""
        return (
            iter([chunk(text, calls, "tool_calls" if calls else "stop")])
            if stream
            else response(text, calls)
        )

    cli = client(create)
    if stream:
        events = list(adapter.chat_stream_sse_events("synthetic", client=cli, model="synthetic"))
        assert events[-1]["type"] == "done"
        result = events[-1]["result"]
    else:
        result = adapter.chat("synthetic", client=cli, model="synthetic")
        assert result["text"] == "synthetic answer"
    assert len(result["legacy_tool_records"]) == 3
    assert fixture_tools.call_count == 2
    assert cli.chat.completions.create.call_count == 3
