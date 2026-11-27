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
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor

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


@pytest.mark.parametrize("missing_dependency", [False, True])
def test_header_detection_rejects_unreadable_workbook(tmp_path, monkeypatch, missing_dependency):
    import builtins
    import runpy
    import zipfile

    from app.infrastructure.excel import header_detection

    path = tmp_path / "unreadable.xlsx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("unrelated.txt", "not an Excel workbook")
    detect = detect_header_row_1based
    if missing_dependency:
        original_import = builtins.__import__

        def unavailable(name, *args, **kwargs):
            if name.startswith("openpyxl"):
                raise ImportError("optional reader unavailable")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", unavailable)
        detect = runpy.run_path(header_detection.__file__)["detect_header_row_1based"]
    assert detect(path) is None


def test_unreadable_workbook_returns_no_header_without_model_call(tmp_path, monkeypatch):
    from zipfile import ZipFile

    path = tmp_path / "damaged.xlsx"
    with ZipFile(path, "w") as archive:
        archive.writestr("unrelated.txt", "not a workbook")
    provider = MagicMock(side_effect=AssertionError("unreadable bytes cannot reach a model"))
    monkeypatch.setattr("app.infrastructure.excel.header_detection.get_active_provider", provider)
    assert detect_header_row_1based(path) is None
    provider.assert_not_called()


@pytest.mark.parametrize("layout", ["blank-column", "titled-blank-column", "metadata"])
def test_ambiguous_header_requires_confirmation_before_reading_or_querying(
    tmp_path, monkeypatch, unconfigured_header_registry, layout, registered_excel
):
    from openpyxl import Workbook

    from app.application.tools.workflow_excel_paths import _parse_excel_header_row_1based

    path = tmp_path / "blank-header.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    header = 1
    if layout == "titled-blank-column":
        sheet.append(["月度业务明细"])
        sheet.append([])
        header = 3
    if layout == "metadata":
        sheet.append(["客户", "甲公司"])
        sheet.append(["日期", "产品", "数量", "金额"])
        sheet.append(["2026/11/21", "床垫", 1, 100])
        sheet.append(["2026/11/22", "沙发", 2, 200])
        header = 2
    else:
        sheet.append(["客户", "地区", "备注", "金额", None])
        sheet.append(["客户甲", "华东", "新增订单", "100", "额外业务说明"])
        sheet.append(["客户乙", "华南", "续订订单", "200", "其他业务说明"])
    workbook.save(path)
    assert unconfigured_header_registry.get_active_provider(profile="excel_header") is None
    read = MagicMock(wraps=read_excel_dataframe)
    query = MagicMock(
        side_effect=lambda frame, *_args, **_kwargs: {
            "success": True,
            "row_count": len(frame),
            "total": int(pd.to_numeric(frame["金额"]).sum()),
        }
    )
    analysis = ExcelAnalysis(
        ExcelIO(lambda _root, _path: path, read, _parse_excel_header_row_1based),
        lambda frame, _expression: frame,
        lambda *_args: "",
        logging.getLogger(__name__),
    )
    monkeypatch.setattr(
        "app.application.tools.workflow_tools.excel_analysis.natural_language_query", query
    )
    args = {"file_path": str(path), "action": "query", "question": "金额合计"}
    with pytest.raises(ValueError, match="确认表头"):
        detect_header_row_1based(path)
    blocked = analysis.analyze(args, str(tmp_path))
    assert blocked["success"] is False
    assert blocked["error"] == "header_confirmation_required"
    assert blocked["required_field"] == "header_row"
    assert header in blocked["header_candidates"]
    assert len(blocked["header_candidates"]) > 1
    assert all(type(row) is int for row in blocked["header_candidates"])
    read.assert_not_called()
    query.assert_not_called()
    with patch(
        "app.application.tools.workflow_tools.excel_analysis.auto_header_row",
        side_effect=AssertionError("explicit headers and raw read do not infer a header"),
    ):
        result = analysis.analyze({**args, "header_row": header}, str(tmp_path))
        assert result["success"] is True and result["row_count"] == 2
        assert result["total"] == 300 and result["header_row"] == header
        read.assert_called_once_with(path, sheet_name=None, header_row_1based=header)
        raw = analysis.analyze({"file_path": str(path), "action": "read"}, str(tmp_path))
        assert raw["success"] is True
        assert read.call_args.kwargs["header_row_1based"] is None
    query.assert_called_once()
    execute = registered_excel(path)
    with patch(
        "app.application.tools.workflow._read_excel_dataframe", wraps=read_excel_dataframe
    ) as schema_read:
        schema_blocked = execute({"action": "structure"})
        for key in ("success", "error", "required_field", "header_candidates"):
            assert schema_blocked.get(key) == blocked[key]
        assert schema_blocked["message"]
        schema_read.assert_not_called()
        with patch(
            "app.application.tools.workflow_tools.excel_analysis.auto_header_row",
            side_effect=AssertionError("an explicit schema header must not be inferred"),
        ):
            schema_result = execute({"action": "structure", "header_row": header})
        assert schema_result["success"] is True and schema_result["header_row"] == header
        snapshot = schema_result["data"]
        assert snapshot["row_count"] == 2
        expected_columns = (
            ["日期", "产品", "数量", "金额"]
            if layout == "metadata"
            else ["客户", "地区", "备注", "金额"]
        )
        assert snapshot["columns"][:4] == expected_columns
        assert sum(int(row["金额"]) for row in snapshot["sample_rows"]) == 300
        assert schema_read.call_count == 1
        assert schema_read.call_args.kwargs == {"sheet_name": None, "header_row_1based": header}


@pytest.mark.parametrize(
    ("decision", "error"),
    [("failure", "header_detection_failed"), ("unknown", "header_confirmation_required")],
)
@pytest.mark.parametrize("scoped", [True, False])
def test_real_sdk_header_failure_does_not_become_no_model_fallback(
    tmp_path, monkeypatch, unconfigured_header_registry, decision, error, scoped
):
    import httpx
    from openai import AuthenticationError

    from app.application.tools.workflow import handle_excel_analysis
    from app.infrastructure.llm import client

    path = tmp_path / "ledger.xlsx"
    _write_workbook(path)
    create = MagicMock(
        side_effect=AuthenticationError(
            "provider authorization denied",
            response=httpx.Response(
                401, request=httpx.Request("POST", "https://example.invalid/v1/chat/completions")
            ),
            body=None,
        )
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
    assert result["success"] is False and result["error"] == error
    assert "columns" not in result
    assert create.call_count == 1  # An authentication rejection must never replay.


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
        ("2026/9/1-26年9月30日", pd.Timestamp("2026-09-01")),
        ("2026/12/27-27年1月23日", pd.Timestamp("2026-12-27")),
        ("26年9月1日-2026/9/30", pd.Timestamp("2026-09-01")),
        ("2026/9/30-26年9月1日", pd.Timestamp("2026-09-30")),
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


@pytest.mark.parametrize("operation", ["filter", "aggregate", "sort"])
@pytest.mark.parametrize("repair_succeeds", [False, True])
def test_mixed_cell_types_use_the_existing_query_plan_repair(operation, repair_succeeds):
    initial = {
        "filter": {"query_expression": "c0 > 0"},
        "aggregate": {"metrics": [{"column": "value", "op": "sum"}]},
        "sort": {"sort_by": ["value"]},
    }[operation]
    frame = pd.DataFrame({"value": ["heading", 8, 4, None]})
    frame.attrs["source_header"] = 0
    attempts = []

    def translate(_question, _frame, *, error_feedback=None):
        attempts.append(error_feedback)
        if error_feedback and repair_succeeds:
            return json.dumps(
                {
                    **initial,
                    "conversions": [{"column": "value", "kind": "number"}],
                }
            )
        return json.dumps(initial)

    result = natural_language_query(frame, "Operate on the numbers", translate, _execute)
    assert len(attempts) == 2 and "conversion" in attempts[1]
    assert result["success"] is repair_succeeds
    assert result.get("error") == (None if repair_succeeds else "invalid_pandas_query")
    if repair_succeeds:
        assert (
            result["records"]
            == {
                "filter": [{"value": 8}, {"value": 4}],
                "aggregate": [{"value_sum": 12}],
                "sort": [{"value": 4}, {"value": 8}, {"value": None}, {"value": None}],
            }[operation]
        )
    assert frame["value"].tolist() == ["heading", 8, 4, None]
    assert json.dumps(result, allow_nan=False)


def _execute(code: str, df: pd.DataFrame) -> pd.DataFrame:
    from app.application.tools.workflow_tools.excel_analysis import execute_query_plan

    return execute_query_plan(code, df)


def test_natural_language_query_reports_translation_failure() -> None:
    frame = pd.DataFrame({"a": [1]})
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


@pytest.fixture
def registered_excel(tmp_path, monkeypatch, trusted_actor, local_tools):
    import io
    import uuid

    from app.application.agent_orchestrator import SQLAlchemyAgentRunRepository
    from app.application.elt.service_uploads import register_chat_upload
    from app.application.tools.workflow import ERP_CAPABILITY_TOOL_NAME, execute_workflow_tool

    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    actor = trusted_actor(user_id=17, role="admin")
    repo = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    repo._ensure_schema()
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository", lambda: repo
    )

    def register(path):
        upload = register_chat_upload(
            user=SimpleNamespace(id=actor.user_id, tenant_id=actor.tenant_id),
            filename=path.name,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            stream=io.BytesIO(path.read_bytes()),
        )

        def execute(params=None):
            params = dict(params or {})
            action = params.pop("action", "structure")
            payload = json.loads(
                execute_workflow_tool(
                    ERP_CAPABILITY_TOOL_NAME,
                    {
                        "tool_id": "excel_analysis",
                        "action": action,
                        "params": {"file_path": upload["upload_id"], **params},
                    },
                    runtime_context={**actor.context, "idempotency_key": uuid.uuid4().hex},
                )
            )
            run = repo.get(payload.get("run_id", ""))
            assert run is not None and len(run.tool_calls) == 1, payload
            return run.steps[0].output

        return execute

    return register


@pytest.fixture
def registered_workbook(tmp_path, registered_excel):
    path = tmp_path / "ledger.xlsx"
    _write_workbook(path)
    return registered_excel(path)


@pytest.mark.parametrize(
    ("decision", "error"),
    [("failure", "header_detection_failed"), ("unknown", "header_confirmation_required")],
)
def test_configured_model_failure_does_not_succeed_with_first_row(
    registered_workbook, decision, error
):
    from app.infrastructure.llm.structured_output import StructuredOutputError

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
        result = registered_workbook()
    assert result["success"] is False
    assert result["error"] == error and result["required_field"] == "header_row"
    assert "columns" not in result
    if decision == "unknown":
        assert result["physical_preview"][0]["row"] == 1
        assert set(result["physical_preview"][0]["cells"]) == {"A"}


@pytest.mark.parametrize("title", [False, True])
def test_registered_headerless_workbook_preserves_physical_rows_and_columns(
    tmp_path, registered_excel, title
):
    from openpyxl import Workbook

    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

    path = tmp_path / "headerless.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    if title:
        sheet.append(["Sample activity"])
        sheet.merge_cells("A1:D1")
    sheet.append(["First", None, "region", 4])
    sheet.append([])
    sheet.append(["Second", None, "region", 7])
    workbook.save(path)
    original = path.read_bytes()
    execute = registered_excel(path)
    common = {"sheet_name": sheet.title, "header_row": 0}
    with patch(
        "app.infrastructure.excel.header_detection.get_active_provider",
        side_effect=AssertionError("an explicit headerless request does not infer a header"),
    ):
        structure = execute(common)
        read = execute({"action": "read", **common})
        result = execute(
            {"action": "aggregate", **common, "metrics": [{"column": "D", "op": "sum"}]}
        )

    for action in ("structure", "read", "query", "aggregate"):
        assert (
            get_tool_action_spec("excel_analysis", action).input_schema["properties"]["header_row"][
                "minimum"
            ]
            == 0
        )
    assert structure["header_row"] == read["header_row"] == result["header_row"] == 0
    assert structure["columns"] == read["columns"] == ["A", "B", "C", "D"]
    assert [row["A"] for row in read["records"]] == (
        (["Sample activity"] if title else []) + ["First", None, "Second"]
    )
    assert (
        read["source_rows"]["row_ranges"]
        == result["source_rows"]["row_ranges"]
        == [[1, 4 if title else 3]]
    )
    assert result["records"] == [{"D_sum": 11.0}]
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    ("numbers", "middle", "error"),
    [
        ((4, 7), "memo", None),
        ((4, 7), "#VALUE!", "sum_cell_error"),
        ((4, 7), "=2+3", "sum_formula_value_unavailable"),
        (("4", "7"), "memo", "sum_range_has_no_numeric_cells"),
    ],
)
def test_registered_physical_sum_reports_text_cells_and_rejects_unreadable_values(
    tmp_path, registered_excel, numbers, middle, error
):
    from openpyxl import Workbook

    path = tmp_path / "rating.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["activity", None, 1000])
    for row, value in enumerate((numbers[0], middle, numbers[1]), 2):
        sheet.cell(row, 3, value)
    sheet.cell(5, 3, 2000)
    workbook.save(path)
    execute = registered_excel(path)
    result = execute(
        {
            "action": "aggregate",
            "header_row": 0,
            "metrics": [{"column": "C", "op": "sum", "cell_range": "C2:C4"}],
        }
    )
    if error:
        assert result["success"] is False and result["error"] == error
        if error != "sum_range_has_no_numeric_cells":
            assert result["cell"] == "C3"
        return
    assert result["success"] is True and result["records"] == [{"C_sum": 11.0}]
    assert result["source_rows"]["row_ranges"] == [[2, 4]]
    assert result["ignored_non_numeric_rows"]["row_ranges"] == [[3, 3]]
    assert result["numeric_cell_count"] == 2


def test_schema_tool_preserves_snapshot_contract_with_model_header(registered_workbook):
    with (
        patch(
            "app.infrastructure.excel.header_detection.get_active_provider", return_value=object()
        ),
        patch(
            "app.infrastructure.excel.header_detection.complete_structured_sync",
            return_value=SimpleNamespace(data={"header_row": 4}),
        ) as infer,
    ):
        result = registered_workbook()
    assert result["success"] is True and result["header_row"] == 4
    assert result["data"]["columns"] == ["日期", "产品名称", "购货金额"]
    assert result["data"]["row_count"] == 3
    assert infer.call_count == 1


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


def test_header_detection_never_promotes_a_denser_business_row(tmp_path: Path) -> None:
    from openpyxl import Workbook

    path = tmp_path / "sparse-header.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["名称", "日期", None, None])
    sheet.append(["电视柜", "十一月", "已确认", "正常"])
    sheet.append(["茶几", "十二月", "未确认", "正常"])
    workbook.save(path)
    from app.infrastructure.excel.header_detection import HeaderConfirmationRequired

    with pytest.raises(HeaderConfirmationRequired) as error:
        detect_header_row_1based(path)
    assert error.value.candidate_rows == (1, 2, 3)
    frame = read_excel_dataframe(path, sheet_name=None, header_row_1based=1)
    assert len(frame) == 2
    assert frame.iloc[0, 0] == "电视柜"


def test_numeric_header_never_promotes_following_business_row(tmp_path: Path) -> None:
    from openpyxl import Workbook

    path = tmp_path / "numeric-header.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["名称", 2025, 2026])
    sheet.append(["电视柜", "已确认", "正常"])
    workbook.save(path)
    from app.infrastructure.excel.header_detection import HeaderConfirmationRequired

    with pytest.raises(HeaderConfirmationRequired) as error:
        detect_header_row_1based(path)
    assert error.value.candidate_rows == (1, 2)
    frame = read_excel_dataframe(path, sheet_name=None, header_row_1based=1)
    assert list(frame.columns) == ["名称", 2025, 2026]
    assert frame.to_dict(orient="records") == [{"名称": "电视柜", 2025: "已确认", 2026: "正常"}]
