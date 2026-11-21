"""Excel 自然语言查询链路的回归测试：表头探测、日期归一化、失败重试。"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.application.tools.workflow_tools.contracts import ExcelIO
from app.application.tools.workflow_tools.excel_analysis import (
    ExcelAnalysis,
    natural_language_query,
    read_excel_dataframe,
)
from app.infrastructure.excel.date_norm import cn_date, first_date
from app.infrastructure.excel.header_detection import detect_header_row_1based

pytestmark = pytest.mark.usefixtures("mock_external_service")


def _write_workbook(path: Path) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = "澜宇二厂 2026 年购货明细"
    sheet["A2"] = "制表日期：2026-11-01"
    sheet.append([])
    sheet.append(["日期", "产品名称", "购货金额"])
    sheet.append(["12月27-26年1月23", "电视柜", 100])
    sheet.append(["2026/9/30", "电视柜", 200])
    sheet.append(["合计", None, 300])
    workbook.save(path)


@pytest.fixture
def unconfigured_header_registry(monkeypatch):
    from app.infrastructure.llm import client
    from app.infrastructure.llm.providers import registry

    for name in (
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "XCAUTO_API_KEY",
        "XCAUTO_PAT",
        "XIUCI_API_KEY",
        "XIAOMI_API_KEY",
        "MIMO_API_KEY",
        "XIAOMI_MIMO_API_KEY",
        "LLM_ROUTING_ORDER",
        "LLM_PROVIDER",
        "XCAGI_LLM_PROVIDER",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(client, "_mode", "online")
    monkeypatch.setattr(registry, "_registry", registry.LLMProviderRegistry())
    return registry


def test_detect_header_row_skips_title_rows_when_model_unavailable(
    tmp_path: Path, unconfigured_header_registry
) -> None:
    path = tmp_path / "ledger.xlsx"
    _write_workbook(path)
    assert unconfigured_header_registry.get_active_provider(profile="excel_header") is None
    assert detect_header_row_1based(path) == 4


@pytest.mark.parametrize("decision", ["failure", "unknown"])
@pytest.mark.parametrize("scoped", [True, False])
def test_real_sdk_header_failure_does_not_become_no_model_fallback(
    tmp_path, monkeypatch, unconfigured_header_registry, decision, scoped
):
    from app.application.tools.workflow import handle_excel_analysis
    from app.infrastructure.llm import client

    path = tmp_path / "ledger.xlsx"
    _write_workbook(path)
    create = MagicMock(
        side_effect=RuntimeError("provider authorization denied")
        if decision == "failure"
        else None,
        return_value={"choices": [{"message": {"content": '{"header_row": 0}'}}]},
    )
    sdk_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setenv("LLM_ROUTING_ORDER", "openai_sdk")
    if not scoped:
        monkeypatch.setenv("OPENAI_API_KEY", "header-test-credential")
        monkeypatch.setattr(client, "_openai_client", sdk_client)
    with (
        client.llm_client_scope(sdk_client, "header-test-model") if scoped else nullcontext(),
        patch(
            "app.infrastructure.excel.header_detection._row_score",
            side_effect=AssertionError("configured provider cannot fall back to rules"),
        ),
    ):
        provider = unconfigured_header_registry.get_active_provider(profile="excel_header")
        assert provider is not None and provider.provider_id == "openai_sdk"
        assert provider.is_configured is True
        result = handle_excel_analysis(
            {"file_path": str(path), "action": "structure"}, workspace_root=str(tmp_path)
        )
    assert result["success"] is False and result["error"] == "read_excel_failed"
    assert "columns" not in result
    assert create.call_count == (2 if decision == "failure" else 1)


def test_read_dataframe_fills_merged_header_columns(tmp_path: Path) -> None:
    path = tmp_path / "merged.xlsx"
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = "日期"
    sheet["B1"] = "金额"
    sheet["C1"] = None
    sheet.append(["2026/9/30", 1, 2])
    workbook.save(path)
    frame = read_excel_dataframe(path, sheet_name=None, header_row_1based=1)
    assert list(frame.columns) == ["日期", "金额", "金额_2"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12月27-26年1月23", pd.Timestamp("2025-12-27")),
        ("9月1-2026年9月30", pd.Timestamp("2026-09-01")),
        ("7月1-2026年12月31", pd.Timestamp("2026-07-01")),
        ("2月", pd.Timestamp("2026-02-01")),
        ("2026/9/30", pd.Timestamp("2026-09-30")),
        (46292, pd.Timestamp("2026-09-27")),
        (None, pd.NaT),
    ],
)
def test_first_date_handles_chinese_ranges_and_serial(raw, expected) -> None:
    parsed = first_date(raw, allow_serial=True)
    if pd.isna(expected):
        assert parsed is None
    else:
        assert pd.Timestamp(parsed) == expected


def test_cn_date_series_mixes_text_and_serial() -> None:
    series = pd.Series(["12月27-26年1月23", 46292, None])
    parsed = cn_date(series)
    assert parsed.tolist()[:2] == [pd.Timestamp("2025-12-27"), pd.Timestamp("2026-09-27")]
    assert pd.isna(parsed.tolist()[2])


def test_natural_language_query_retries_with_error_feedback() -> None:
    frame = pd.DataFrame({"amount": [1, 2, 3]})
    calls: list[str | None] = []

    def translate(_question: str, _df: pd.DataFrame, *, error_feedback=None):
        calls.append(error_feedback)
        if error_feedback:
            return '{"query_expression": "c0 > 1"}'
        return '{"query_expression": "missing > 0"}'

    result = natural_language_query(frame, "大于 1 的金额", translate, _execute)
    assert result["success"] is True
    assert result["row_count"] == 2
    assert len(calls) == 2 and calls[1]


def _execute(code: str, df: pd.DataFrame) -> pd.DataFrame:
    from app.infrastructure.excel.text_to_pandas import _safe_exec_pandas

    return _safe_exec_pandas(code, df)


def test_natural_language_query_reports_translation_failure() -> None:
    frame = pd.DataFrame({"a": [1]})
    with patch("app.application.tools.workflow.adapters.translate_pandas", return_value=None):
        result = natural_language_query(
            frame,
            "看不懂的问题",
            lambda *_args, **_kwargs: None,
            _execute,
        )
    assert result["success"] is False
    assert result["error"] == "query_translation_failed"
    assert result["message"]


def test_generated_file_and_network_operations_cannot_escape_supplied_frame(tmp_path):
    external = tmp_path / "not-in-supplied-frame.csv"
    external.write_text("external_secret\nfixture-only\n")
    output = tmp_path / "must-not-be-written.csv"
    payloads = [
        f"result = pd.read_csv({str(external)!r})",
        f"df.to_csv({str(output)!r})\nresult = df",
        "result = pd.read_csv('https://example.invalid/private')",
        json.dumps({"query_expression": f"pd.read_csv({str(external)!r})"}),
        json.dumps({"query_expression": "__import__('os').getenv('TOKEN')"}),
        json.dumps({"query_expression": "c0.__class__"}),
        json.dumps({"code": "result = df"}),
        json.dumps({"columns": ["allowed", "allowed"]}),
    ]
    with patch.object(pd, "read_csv", side_effect=AssertionError("model attempted I/O")) as read:
        for payload in payloads:
            result = natural_language_query(
                pd.DataFrame({"allowed": [1]}), "只查询传入的表格", lambda *_args: payload, _execute
            )
            assert result["success"] is False
            assert result["error"] == "invalid_pandas_query"
            assert result["records"] == [{"allowed": 1}]
        read.assert_not_called()
    assert not output.exists()


def test_plain_read_preserves_identifier_values_and_source_file(tmp_path):
    path = tmp_path / "ids.csv"
    pd.DataFrame({"candidate_id": [46292], "update_time_code": [46293]}).to_csv(path, index=False)
    original = path.read_bytes()
    analysis = ExcelAnalysis(
        ExcelIO(lambda _root, _path: path, read_excel_dataframe, lambda _args: None),
        lambda *_args, **_kwargs: {},
        lambda frame, _expression: frame,
        lambda *_args: "",
        logging.getLogger(__name__),
    )
    result = analysis.analyze({"file_path": str(path), "action": "read"}, str(tmp_path))
    assert result["success"] is True
    assert result["records"] == [{"candidate_id": 46292, "update_time_code": 46293}]
    assert path.read_bytes() == original


def test_model_header_decision_precedes_the_conflicting_rule(tmp_path):
    from openpyxl import Workbook

    path = tmp_path / "merged.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["产品", None, "供应商", None, "备注"])
    sheet.merge_cells("A1:B1")
    sheet.merge_cells("C1:D1")
    sheet.append(["床垫", "M-01", "甲公司", "广东", "现货"])
    sheet.append(["床垫", "M-02", "乙公司", "上海", "现货"])
    workbook.save(path)
    with (
        patch(
            "app.infrastructure.excel.header_detection.get_active_provider", return_value=object()
        ),
        patch(
            "app.infrastructure.excel.header_detection.complete_structured_sync",
            return_value=SimpleNamespace(data={"header_row": 1}),
        ) as infer,
    ):
        header = detect_header_row_1based(path)
    assert header == 1 and infer.call_count == 1
    frame = read_excel_dataframe(path, sheet_name=None, header_row_1based=header)
    assert len(frame) == 2 and frame.iloc[0, 0] == "床垫"


def test_explicit_header_is_not_overridden_by_ai(tmp_path):
    path = tmp_path / "ledger.xlsx"
    _write_workbook(path)
    analysis = ExcelAnalysis(
        ExcelIO(lambda _root, _path: path, read_excel_dataframe, lambda _args: 4),
        lambda *_args, **_kwargs: {},
        lambda frame, _expression: frame,
        lambda *_args: "",
        logging.getLogger(__name__),
    )
    with patch(
        "app.infrastructure.excel.header_detection.get_active_provider",
        side_effect=AssertionError("explicit header must not invoke a model"),
    ):
        result = analysis.analyze({"file_path": str(path), "action": "statistics"}, str(tmp_path))
    assert result["header_row"] == 4 and result["row_count"] == 3


@pytest.mark.parametrize("tool", ["excel_analysis", "excel_schema_understand"])
@pytest.mark.parametrize("decision", ["failure", "unknown"])
@pytest.mark.parametrize("native_enabled", [True, False])
def test_configured_model_failure_does_not_succeed_with_first_row(
    tmp_path, monkeypatch, tool, decision, native_enabled
):
    from app.application.tools.workflow import execute_workflow_tool
    from app.infrastructure.llm.structured_output import StructuredOutputError

    path = tmp_path / "ledger.xlsx"
    _write_workbook(path)
    monkeypatch.setenv("XCAGI_DISABLE_PLANNER_NATIVE_TOOLS", "0" if native_enabled else "1")
    with (
        patch(
            "app.infrastructure.excel.header_detection.get_active_provider", return_value=object()
        ),
        patch(
            "app.infrastructure.excel.header_detection.complete_structured_sync",
            side_effect=StructuredOutputError(1, ["unavailable"], "")
            if decision == "failure"
            else None,
            return_value=SimpleNamespace(data={"header_row": 0}),
        ),
        patch(
            "app.infrastructure.excel.header_detection._row_score",
            side_effect=AssertionError("configured model must not fall back to rules"),
        ),
    ):
        result = json.loads(
            execute_workflow_tool(
                tool, {"file_path": str(path), "action": "structure"}, workspace_root=str(tmp_path)
            )
        )
    assert result["success"] is False
    assert result["error"] == "read_excel_failed"
    assert "columns" not in result


@pytest.mark.parametrize("native_enabled", [True, False])
def test_schema_tool_preserves_snapshot_contract_with_model_header(
    tmp_path, monkeypatch, native_enabled
):
    from app.application.tools.workflow import execute_workflow_tool

    path = tmp_path / "ledger.xlsx"
    _write_workbook(path)
    monkeypatch.setenv("XCAGI_DISABLE_PLANNER_NATIVE_TOOLS", "0" if native_enabled else "1")
    with (
        patch(
            "app.infrastructure.excel.header_detection.get_active_provider", return_value=object()
        ),
        patch(
            "app.infrastructure.excel.header_detection.complete_structured_sync",
            return_value=SimpleNamespace(data={"header_row": 4}),
        ) as infer,
    ):
        result = json.loads(
            execute_workflow_tool(
                "excel_schema_understand", {"file_path": str(path)}, workspace_root=str(tmp_path)
            )
        )
    assert result["success"] is True and result["header_row"] == 4
    assert result["snapshot"]["columns"] == ["日期", "产品名称", "购货金额"]
    assert result["structure"]["row_count"] == 3
    assert infer.call_count == 1
    if native_enabled:
        assert result["source"] == "mod:xcagi-planner-excel-tools"


def test_real_translator_keeps_owner_scope_and_runs_date_aggregation_in_both_bridges(monkeypatch):
    from app.infrastructure.excel.pandas_translator import LLMPandasTranslator
    from app.infrastructure.llm import model_admission
    from app.infrastructure.llm.client import _scoped_client
    from app.infrastructure.llm.providers import registry

    calls = []
    plan = {
        "conversions": [
            {"column": "日期", "kind": "date"},
            {"column": "金额（元）", "kind": "number"},
        ],
        "query_expression": 'c0 >= "2026-01-01" and c0 < "2026-10-01"',
        "metrics": [{"column": "金额（元）", "op": "sum"}],
    }

    class Provider:
        is_configured = True

        def __init__(self, provider_id):
            self.provider_id = provider_id

        async def chat_completion(self, messages, **kwargs):
            calls.append(
                (
                    self.provider_id,
                    model_admission._MODEL_IDENTITY.get(),
                    model_admission._MODEL_TENANT.get(),
                    _scoped_client.get() is not None,
                )
            )
            assert "9月1-2026年9月30" in messages[-1]["content"]
            return {"choices": [{"message": {"content": json.dumps(plan)}}]}

    owner = Provider("scoped-owner")
    fallback = Provider("process-fallback")
    isolated = object.__new__(registry.LLMProviderRegistry)
    isolated._providers = {"fallback": fallback}
    monkeypatch.setattr(registry, "_registry", isolated)
    monkeypatch.setattr(registry, "OpenAISdkProvider", lambda: owner)
    monkeypatch.setattr(registry, "_routing_order", lambda: ("fallback",))
    monkeypatch.setattr(registry, "_maybe_instrument", lambda provider: provider)
    monkeypatch.setattr(model_admission, "rate_limit_provider", lambda provider: provider)
    frame = pd.DataFrame(
        {"日期": ["9月1-2026年9月30", "2026/10/01"], "金额（元）": ["￥1,200元", "50"]}
    )
    original = frame.copy()

    def query():
        token = _scoped_client.set((object(), "owner-model"))
        try:
            with model_admission.model_rate_limit_scope({"local_user_id": 7, "tenant_id": 9}):
                return natural_language_query(
                    frame, "2026 年 10 月之前金额合计", LLMPandasTranslator().translate, _execute
                )
        finally:
            _scoped_client.reset(token)

    async def inside_loop():
        return query()

    for result in (query(), asyncio.run(inside_loop())):
        assert result["success"] is True
        assert result["records"] == [{"金额（元）_sum": 1200}]
    assert calls == [("scoped-owner", "tenant:9:actor:7", "tenant:9", True)] * 2
    pd.testing.assert_frame_equal(frame, original)


def test_missing_model_keeps_failure_receipt_without_python_fallback(monkeypatch):
    from app.infrastructure.excel.pandas_translator import LLMPandasTranslator
    from app.infrastructure.llm import invoke

    monkeypatch.setattr(invoke, "get_active_provider", lambda **_kwargs: None)
    result = natural_language_query(
        pd.DataFrame({"a": [1]}), "汇总", LLMPandasTranslator().translate, _execute
    )
    assert result["success"] is False
    assert result["error"] == "query_translation_failed"
    assert result["generated_code"] == ""
    assert result["records"] == [{"a": 1}]
