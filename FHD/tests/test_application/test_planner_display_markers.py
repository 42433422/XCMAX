"""planner_display_markers SSOT — 与前端 chatBubbleDisplay 对齐。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_mod_path = (
    Path(__file__).resolve().parents[2] / "app" / "application" / "planner_display_markers.py"
)
_spec = importlib.util.spec_from_file_location("planner_display_markers", _mod_path)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
strip_planner_stream_markers = _mod.strip_planner_stream_markers


class TestStripPlannerStreamMarkers:
    def test_halfwidth_tool_marker(self):
        raw = "答案[正在调用工具:excel.read]完成"
        user, thinking = strip_planner_stream_markers(raw)
        assert "[正在调用工具" not in user
        assert "答案" in user
        assert thinking and "excel.read" in thinking

    def test_fullwidth_tool_marker(self):
        raw = "结果【正在调用工具:excel.read】完成"
        user, thinking = strip_planner_stream_markers(raw)
        assert "【正在调用工具" not in user
        assert "结果" in user
        assert thinking and "excel.read" in thinking

    def test_unclosed_halfwidth_marker(self):
        raw = "前缀[正在调用工具:search 后缀"
        user, _ = strip_planner_stream_markers(raw)
        assert "[正在调用工具" not in user
        assert "前缀" in user

    def test_bare_tool_prefix_without_brackets(self):
        raw = "说明正在调用工具:db.query 继续"
        user, _ = strip_planner_stream_markers(raw)
        assert "正在调用工具:db.query" not in user
        assert "说明" in user
        assert "继续" in user
