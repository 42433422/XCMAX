"""ERP Agent document-worker integration: real function calls, never text protocol."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.application.tools.workflow import (
    get_workflow_tool_registry,
    invalidate_workflow_tool_registry,
)
from app.mod_sdk.employee_pack_compat import list_office_pack_catalog
from app.mod_sdk.employee_tool_registry import (
    build_employee_tools_status,
    invalidate_employee_tool_cache,
)


def test_all_ten_built_in_document_workers_are_registered_and_runnable() -> None:
    expected = set(list_office_pack_catalog()["pack_ids"])
    assert len(expected) == 10
    invalidate_employee_tool_cache()
    invalidate_workflow_tool_registry()
    status = build_employee_tools_status()
    names = {row["function"]["name"] for row in get_workflow_tool_registry() if row.get("function")}

    assert status["office_ready"] is True
    assert status["missing_office_pack_ids"] == []
    # Some non-document host packs may intentionally be unavailable in a
    # lightweight test environment.  The release contract here is that each
    # bundled office employee is executable, not that every optional pack is.
    assert not (expected & set(status["runtime_missing_pack_ids"]))
    assert expected <= set(status["registered_tool_names"])
    assert expected <= names


def test_word_generator_writes_an_actual_document_from_a_chat_request(
    tmp_path, monkeypatch
) -> None:
    """A forced chat call must yield a file, even when no JSON was uploaded."""
    from app.mod_sdk.employee_tool_registry import execute_employee_tool

    def unexpected_cognition(*_args, **_kwargs):
        raise AssertionError("bundled Office conversion must not need an LLM")

    monkeypatch.setattr(
        "app.application.employee_runtime.agent._ex._cognition_fhd",
        unexpected_cognition,
    )

    result = json.loads(
        execute_employee_tool(
            "word-generate-employee",
            {"user_request": "起草一份验收用销售合同，包含交付与付款条款。"},
            str(tmp_path),
        )
    )

    assert result["success"] is True
    assert result["artifact_postcondition"]["verified"] is True
    assert Path(result["artifact_postcondition"]["paths"][0]).suffix == ".docx"
    generated = list((tmp_path / "outputs").glob("*.docx"))
    assert generated and generated[0].stat().st_size > 0
    read_result = json.loads(
        execute_employee_tool(
            "word-full-read-employee", {"file_path": str(generated[0])}, str(tmp_path)
        )
    )
    assert read_result["success"] is True, read_result


@pytest.mark.parametrize(
    ("tool_name", "reader_name", "suffix"),
    [
        ("excel-generate-employee", "excel-full-read-employee", ".xlsx"),
        ("csv-generate-employee", "csv-full-read-employee", ".csv"),
        ("pdf-generate-employee", "pdf-full-read-employee", ".pdf"),
        ("ppt-generate-employee", "ppt-full-read-employee", ".pptx"),
    ],
)
def test_other_document_generators_write_files_without_modstore_source(
    tmp_path, tool_name: str, reader_name: str, suffix: str
) -> None:
    from app.mod_sdk.employee_tool_registry import execute_employee_tool

    result = json.loads(
        execute_employee_tool(
            tool_name,
            {"user_request": "生成一份验收用业务摘要，包含客户、金额和交付状态。"},
            str(tmp_path),
        )
    )

    assert result["success"] is True
    assert result["artifact_postcondition"]["verified"] is True
    assert Path(result["artifact_postcondition"]["paths"][0]).suffix == suffix
    generated = list((tmp_path / "outputs").glob(f"*{suffix}"))
    assert generated and generated[0].stat().st_size > 0
    read_result = json.loads(
        execute_employee_tool(reader_name, {"file_path": str(generated[0])}, str(tmp_path))
    )
    assert read_result["success"] is True, read_result


def test_explicit_document_request_forces_real_function_call_then_returns_to_auto(
    monkeypatch,
) -> None:
    from app.legacy.chat import legacy_chat_adapter as adapter

    calls: list[dict] = []
    executed: list[tuple[str, dict]] = []

    class _Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                tool_call = SimpleNamespace(
                    id="call_word_1",
                    function=SimpleNamespace(
                        name="word-generate-employee",
                        arguments=json.dumps({"user_request": "起草销售合同"}, ensure_ascii=False),
                    ),
                )
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[tool_call]))
                    ]
                )
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content="合同已生成", tool_calls=[]))
                ]
            )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=_Completions()),
        is_modstore_openai_compatible=False,
    )
    monkeypatch.setattr(
        adapter,
        "_get_workflow_tool_registry",
        lambda: [{"type": "function", "function": {"name": "word-generate-employee"}}],
    )

    def _execute(name: str, raw_args: str, _workspace: str | None, **_kwargs: object) -> str:
        executed.append((name, json.loads(raw_args)))
        return json.dumps({"success": True, "output_path": "/tmp/sales-contract.docx"})

    monkeypatch.setattr(adapter, "_resolve_chat_execute_tool", lambda: _execute)
    result = adapter.chat("起草一份 Word 销售合同", client=client)

    assert calls[0]["tool_choice"] == {
        "type": "function",
        "function": {"name": "word-generate-employee"},
    }
    assert calls[1]["tool_choice"] == "auto"
    assert executed == [("word-generate-employee", {"user_request": "起草销售合同"})]
    assert result["text"] == "合同已生成"


def test_explicit_document_stream_uses_the_same_real_function_call(monkeypatch) -> None:
    """The desktop path streams, so it must not fall back to an XML-looking reply."""
    from app.legacy.chat import legacy_chat_adapter as adapter

    calls: list[dict] = []
    executed: list[tuple[str, dict]] = []

    def _chunk(
        *,
        content: str | None = None,
        tool_calls: list[object] | None = None,
        finish_reason: str | None = None,
    ):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=content, tool_calls=tool_calls or []),
                    finish_reason=finish_reason,
                )
            ]
        )

    class _Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                tool_call = SimpleNamespace(
                    index=0,
                    id="call_word_stream_1",
                    function=SimpleNamespace(
                        name="word-generate-employee",
                        arguments=json.dumps({"user_request": "起草销售合同"}, ensure_ascii=False),
                    ),
                )
                return iter([_chunk(tool_calls=[tool_call], finish_reason="tool_calls")])
            return iter([_chunk(content="合同已生成", finish_reason="stop")])

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=_Completions()),
        is_modstore_openai_compatible=False,
    )
    monkeypatch.setattr(
        adapter,
        "_get_workflow_tool_registry",
        lambda: [{"type": "function", "function": {"name": "word-generate-employee"}}],
    )

    def _execute(name: str, raw_args: str, _workspace: str | None, **_kwargs: object) -> str:
        executed.append((name, json.loads(raw_args)))
        return json.dumps({"success": True, "output_path": "/tmp/sales-contract.docx"})

    monkeypatch.setattr(adapter, "_resolve_chat_execute_tool", lambda: _execute)
    events = list(adapter.chat_stream_text("起草一份 Word 销售合同", client=client))

    assert calls[0]["tool_choice"] == {
        "type": "function",
        "function": {"name": "word-generate-employee"},
    }
    assert calls[1]["tool_choice"] == "auto"
    assert executed == [("word-generate-employee", {"user_request": "起草销售合同"})], (
        calls,
        events,
    )
    assert "合同已生成" in events
