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
    def test_none_input_returns_empty_frame(self):
        result = build_normalized_frame(None)
        expected_cols = [
            "工号",
            "姓名",
            "部门",
            "日期",
            "上班打卡",
            "下班打卡",
            "工作时长",
            "考勤结果",
        ]
        assert list(result.columns) == expected_cols
        assert len(result) == 0

    def test_empty_dataframe_returns_empty_frame(self):
        result = build_normalized_frame(pd.DataFrame())
        expected_cols = [
            "工号",
            "姓名",
            "部门",
            "日期",
            "上班打卡",
            "下班打卡",
            "工作时长",
            "考勤结果",
        ]
        assert list(result.columns) == expected_cols
        assert len(result) == 0

    def test_basic_normalization(self):
        df = pd.DataFrame(
            {
                "工号": ["001"],
                "姓名": ["张三"],
                "部门": ["技术部"],
                "日期": ["2026-06-01"],
                "上班打卡时间": ["2026-06-01 09:00:00"],
                "下班打卡时间": ["2026-06-01 18:00:00"],
                "考勤结果": ["正常"],
            }
        )
        result = build_normalized_frame(df)
        assert len(result) == 1
        assert result.iloc[0]["工号"] == "001"
        assert result.iloc[0]["姓名"] == "张三"
        assert result.iloc[0]["考勤结果"] == "正常"
        assert result.iloc[0]["工作时长"] == 9.0

    def test_missing_columns_handled(self):
        df = pd.DataFrame(
            {
                "工号": ["001"],
                "姓名": ["李四"],
                "日期": ["2026-06-01"],
            }
        )
        result = build_normalized_frame(df)
        assert len(result) == 1
        assert result.iloc[0]["工号"] == "001"
        # Missing clock-in/out columns should produce NaN values
        assert pd.isna(result.iloc[0]["上班打卡"])

    def test_invalid_date_coerced_to_nat(self):
        df = pd.DataFrame(
            {
                "工号": ["001"],
                "姓名": ["王五"],
                "日期": ["invalid-date"],
                "上班打卡时间": ["invalid"],
                "下班打卡时间": ["invalid"],
            }
        )
        result = build_normalized_frame(df)
        assert len(result) == 1
        assert pd.isna(result.iloc[0]["日期"])


class TestAggregateMonthlyStats:
    def test_none_input_returns_empty(self):
        result = aggregate_monthly_stats(None)
        expected_cols = [
            "工号",
            "姓名",
            "部门",
            "日期",
            "上班打卡",
            "下班打卡",
            "工作时长",
            "考勤结果",
        ]
        assert list(result.columns) == expected_cols
        assert len(result) == 0

    def test_empty_dataframe_returns_empty(self):
        result = aggregate_monthly_stats(pd.DataFrame())
        assert len(result) == 0

    def test_aggregation_groups_by_employee_and_date(self):
        df = pd.DataFrame(
            {
                "工号": ["001", "001"],
                "姓名": ["张三", "张三"],
                "部门": ["技术部", "技术部"],
                "日期": ["2026-06-01", "2026-06-01"],
                "上班打卡": [pd.Timestamp("2026-06-01 09:00"), pd.Timestamp("2026-06-01 08:30")],
                "下班打卡": [pd.Timestamp("2026-06-01 18:00"), pd.Timestamp("2026-06-01 19:00")],
                "工作时长": [9.0, 10.5],
                "考勤结果": ["正常", "加班"],
            }
        )
        result = aggregate_monthly_stats(df)
        assert len(result) == 1
        assert result.iloc[0]["工作时长"] == 10.5  # max
        assert result.iloc[0]["考勤结果"] == "加班"  # last


class TestConvertDingtalkFile:
    def test_convert_produces_output(self, tmp_path):
        input_file = tmp_path / "input.xlsx"
        output_file = tmp_path / "output.xlsx"

        df = pd.DataFrame(
            {
                "工号": ["001"],
                "姓名": ["张三"],
                "部门": ["技术部"],
                "日期": ["2026-06-01"],
                "上班打卡时间": ["2026-06-01 09:00:00"],
                "下班打卡时间": ["2026-06-01 18:00:00"],
                "考勤结果": ["正常"],
            }
        )
        df.to_excel(input_file, index=False, engine="openpyxl")

        result = convert_dingtalk_file(input_file, output_file)
        assert result["rows_in"] == 1
        assert output_file.exists()

    def test_convert_with_month_param(self, tmp_path):
        input_file = tmp_path / "input.xlsx"
        output_file = tmp_path / "output.xlsx"

        df = pd.DataFrame(
            {
                "工号": ["001"],
                "姓名": ["张三"],
                "部门": ["技术部"],
                "日期": ["2026-06-01"],
                "上班打卡时间": ["2026-06-01 09:00:00"],
                "下班打卡时间": ["2026-06-01 18:00:00"],
                "考勤结果": ["正常"],
            }
        )
        df.to_excel(input_file, index=False, engine="openpyxl")

        result = convert_dingtalk_file(input_file, output_file, month="2026-06")
        assert result["month"] == "2026-06"
