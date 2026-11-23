"""Excel 自然语言查询链路的回归测试：表头探测、日期归一化、失败重试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from app.application.tools.workflow_tools.excel_analysis import (
    natural_language_query,
    read_excel_dataframe,
)
from app.infrastructure.excel.date_norm import cn_date, first_date
from app.infrastructure.excel.header_detection import detect_header_row_1based


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


def test_detect_header_row_skips_title_rows(tmp_path: Path) -> None:
    path = tmp_path / "ledger.xlsx"
    _write_workbook(path)
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
            return "result = df[df['amount'] > 1]"
        return "result = df.loc['missing']"

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
