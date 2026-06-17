"""Tests for app.infrastructure.attendance.dingtalk_convert."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from app.infrastructure.attendance.dingtalk_convert import (
    aggregate_monthly_stats,
    build_normalized_frame,
    convert_dingtalk_file,
)


class TestBuildNormalizedFrame:
    """Tests for build_normalized_frame."""

    def test_empty_dataframe(self) -> None:
        result = build_normalized_frame(pd.DataFrame())
        assert list(result.columns) == ["工号", "姓名", "部门", "日期", "上班打卡", "下班打卡", "工作时长", "考勤结果"]
        assert len(result) == 0

    def test_none_dataframe(self) -> None:
        result = build_normalized_frame(None)
        assert len(result) == 0

    def test_normalizes_columns(self) -> None:
        df = pd.DataFrame({
            "工号": ["E001"],
            "姓名": ["张三"],
            "部门": ["技术部"],
            "日期": ["2026-01-15"],
            "上班打卡时间": ["2026-01-15 09:00:00"],
            "下班打卡时间": ["2026-01-15 18:00:00"],
            "考勤结果": ["正常"],
        })
        result = build_normalized_frame(df)
        assert len(result) == 1
        assert result.iloc[0]["工号"] == "E001"
        assert result.iloc[0]["姓名"] == "张三"
        assert result.iloc[0]["工作时长"] == 9.0
        assert result.iloc[0]["考勤结果"] == "正常"

    def test_missing_date_columns_produce_nat(self) -> None:
        # Provide all required columns but with invalid date values
        df = pd.DataFrame({
            "工号": ["E001"],
            "姓名": ["李四"],
            "部门": ["销售"],
            "日期": ["invalid-date"],
            "上班打卡时间": ["not-a-time"],
            "下班打卡时间": ["also-not"],
            "考勤结果": ["异常"],
        })
        result = build_normalized_frame(df)
        assert len(result) == 1
        # Date should be NaT -> strftime produces None
        assert result.iloc[0]["日期"] is None or pd.isna(result.iloc[0]["日期"])

    def test_missing_optional_columns(self) -> None:
        # Missing 上班打卡时间/下班打卡时间 columns entirely
        df = pd.DataFrame({
            "工号": ["E001"],
            "姓名": ["王五"],
            "部门": ["市场"],
            "日期": ["2026-02-01"],
            "考勤结果": ["正常"],
        })
        result = build_normalized_frame(df)
        assert len(result) == 1
        assert result.iloc[0]["工号"] == "E001"
        # 工作时长 should be NaN since both clock-in/out are NaT
        assert pd.isna(result.iloc[0]["工作时长"])


class TestAggregateMonthlyStats:
    """Tests for aggregate_monthly_stats."""

    def test_empty_dataframe(self) -> None:
        result = aggregate_monthly_stats(pd.DataFrame())
        assert len(result) == 0

    def test_none_dataframe(self) -> None:
        result = aggregate_monthly_stats(None)
        assert len(result) == 0

    def test_aggregates_by_employee_and_date(self) -> None:
        df = pd.DataFrame({
            "工号": ["E001", "E001"],
            "姓名": ["张三", "张三"],
            "部门": ["技术部", "技术部"],
            "日期": ["2026-01-15", "2026-01-15"],
            "上班打卡": pd.to_datetime(["2026-01-15 09:00:00", "2026-01-15 08:30:00"]),
            "下班打卡": pd.to_datetime(["2026-01-15 18:00:00", "2026-01-15 19:00:00"]),
            "工作时长": [9.0, 10.5],
            "考勤结果": ["正常", "加班"],
        })
        result = aggregate_monthly_stats(df)
        assert len(result) == 1
        # min 上班 = 08:30, max 下班 = 19:00, max 工作时长 = 10.5, last 考勤结果 = 加班
        assert result.iloc[0]["工作时长"] == 10.5
        assert result.iloc[0]["考勤结果"] == "加班"


class TestConvertDingtalkFile:
    """Tests for convert_dingtalk_file."""

    def test_converts_excel_file(self, tmp_path: Path) -> None:
        # Create a test Excel file
        input_data = pd.DataFrame({
            "工号": ["E001"],
            "姓名": ["张三"],
            "部门": ["技术部"],
            "日期": ["2026-01-15"],
            "上班打卡时间": ["2026-01-15 09:00:00"],
            "下班打卡时间": ["2026-01-15 18:00:00"],
            "考勤结果": ["正常"],
        })
        input_path = tmp_path / "input.xlsx"
        output_path = tmp_path / "output.xlsx"
        input_data.to_excel(input_path, index=False, engine="openpyxl")

        result = convert_dingtalk_file(input_path, output_path)
        assert result["rows_in"] == 1
        assert output_path.exists()

    def test_creates_output_directory(self, tmp_path: Path) -> None:
        input_data = pd.DataFrame({
            "工号": ["E001"],
            "姓名": ["张三"],
            "部门": ["技术部"],
            "日期": ["2026-01-15"],
            "上班打卡时间": ["2026-01-15 09:00:00"],
            "下班打卡时间": ["2026-01-15 18:00:00"],
            "考勤结果": ["正常"],
        })
        input_path = tmp_path / "input.xlsx"
        output_path = tmp_path / "subdir" / "output.xlsx"
        input_data.to_excel(input_path, index=False, engine="openpyxl")

        result = convert_dingtalk_file(input_path, output_path)
        assert output_path.exists()

    def test_with_month_parameter(self, tmp_path: Path) -> None:
        input_data = pd.DataFrame({
            "工号": ["E001"],
            "姓名": ["张三"],
            "部门": ["技术部"],
            "日期": ["2026-01-15"],
            "上班打卡时间": ["2026-01-15 09:00:00"],
            "下班打卡时间": ["2026-01-15 18:00:00"],
            "考勤结果": ["正常"],
        })
        input_path = tmp_path / "input.xlsx"
        output_path = tmp_path / "output.xlsx"
        input_data.to_excel(input_path, index=False, engine="openpyxl")

        result = convert_dingtalk_file(input_path, output_path, month="2026-01")
        assert result["month"] == "2026-01"
