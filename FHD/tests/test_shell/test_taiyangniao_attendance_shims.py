"""Tests for app.shell.taiyangniao_attendance shim modules.

These are deprecated shim modules that re-export from the mod-local
taiyangniao_attendance package. We test that the re-exports work correctly.
"""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest


class TestInitModule:
    def test_ensure_mod_backend_on_path(self):
        from app.shell.taiyangniao_attendance import _ensure_mod_backend_on_path

        # Should not raise even if path already present
        _ensure_mod_backend_on_path()

    def test_load_mod_submodule(self):
        from app.shell.taiyangniao_attendance import _load_mod_submodule

        # Load the parser submodule - should return the mod's parser module
        mod = _load_mod_submodule("parser")
        assert hasattr(mod, "parse_attendance_workbook")

    def test_load_mod_submodule_rules(self):
        from app.shell.taiyangniao_attendance import _load_mod_submodule

        mod = _load_mod_submodule("rules")
        assert hasattr(mod, "TimeRange")
        assert hasattr(mod, "is_rest_shift")

    def test_load_mod_submodule_mapping(self):
        from app.shell.taiyangniao_attendance import _load_mod_submodule

        mod = _load_mod_submodule("mapping")
        assert hasattr(mod, "DEFAULT_COLUMN_MAP")

    def test_load_mod_submodule_header_resolver(self):
        from app.shell.taiyangniao_attendance import _load_mod_submodule

        mod = _load_mod_submodule("header_resolver")
        assert hasattr(mod, "ResolvedHeader")
        assert hasattr(mod, "resolve_daily_stats_header")
        assert hasattr(mod, "resolve_raw_records_header")
        assert hasattr(mod, "llm_enabled_by_env")

    def test_load_mod_submodule_mapper(self):
        from app.shell.taiyangniao_attendance import _load_mod_submodule

        mod = _load_mod_submodule("mapper")
        assert hasattr(mod, "build_template_profiles")


class TestParserShim:
    def test_import_parser(self):
        from app.shell.taiyangniao_attendance import parser

        assert hasattr(parser, "AttendanceDayRecord")
        assert hasattr(parser, "ParsedAttendanceWorkbook")
        assert hasattr(parser, "parse_attendance_workbook")
        assert hasattr(parser, "parse_work_date")
        assert hasattr(parser, "parse_clock_datetime")
        assert hasattr(parser, "extract_month_label")

    def test_parser_all_exports(self):
        from app.shell.taiyangniao_attendance import parser

        expected = [
            "AttendanceDayRecord",
            "ParsedAttendanceWorkbook",
            "parse_attendance_workbook",
            "parse_work_date",
            "parse_clock_datetime",
            "extract_month_label",
        ]
        for name in expected:
            assert name in parser.__all__


class TestHeaderResolverShim:
    def test_import_header_resolver(self):
        from app.shell.taiyangniao_attendance import header_resolver

        assert hasattr(header_resolver, "ResolvedHeader")
        assert hasattr(header_resolver, "resolve_daily_stats_header")
        assert hasattr(header_resolver, "resolve_raw_records_header")
        assert hasattr(header_resolver, "llm_enabled_by_env")

    def test_header_resolver_all_exports(self):
        from app.shell.taiyangniao_attendance import header_resolver

        expected = [
            "ResolvedHeader",
            "resolve_daily_stats_header",
            "resolve_raw_records_header",
            "llm_enabled_by_env",
        ]
        for name in expected:
            assert name in header_resolver.__all__


class TestRulesShim:
    def test_import_rules(self):
        from app.shell.taiyangniao_attendance import rules

        assert hasattr(rules, "TimeRange")
        assert hasattr(rules, "is_rest_shift")

    def test_rules_all_exports(self):
        from app.shell.taiyangniao_attendance import rules

        assert "TimeRange" in rules.__all__
        assert "is_rest_shift" in rules.__all__


class TestMappingShim:
    def test_import_mapping(self):
        from app.shell.taiyangniao_attendance import mapping

        assert hasattr(mapping, "DEFAULT_COLUMN_MAP")

    def test_mapping_all_exports(self):
        from app.shell.taiyangniao_attendance import mapping

        assert "DEFAULT_COLUMN_MAP" in mapping.__all__


class TestMapperShim:
    def test_import_mapper(self):
        from app.shell.taiyangniao_attendance import mapper

        # Mapper uses dynamic attribute assignment
        # Check that at least some attributes exist
        assert hasattr(mapper, "build_template_profiles") or hasattr(mapper, "DayBandEntry")
