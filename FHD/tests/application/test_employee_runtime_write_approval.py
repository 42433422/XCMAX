# -*- coding: utf-8 -*-
"""employee_runtime.write_approval 写操作审批门 + compose_gates 单元测试。"""

from __future__ import annotations

import pytest

from app.application.employee_runtime import metrics as m
from app.application.employee_runtime.write_approval import (
    build_write_approval_gate,
    compose_gates,
)


class TestBuildWriteApprovalGate:
    def test_non_write_tool_passes(self):
        gate = build_write_approval_gate("e")
        assert gate("excel_analysis", {})["ok"] is True

    def test_approved_write_flag(self):
        gate = build_write_approval_gate("e", {"approved_write": True})
        assert gate("import_excel_to_database", {})["ok"] is True

    def test_allow_write_flag(self):
        gate = build_write_approval_gate("e", {"allow_write": True})
        assert gate("products_bulk_import", {})["ok"] is True

    def test_env_token_allows(self, monkeypatch):
        monkeypatch.setenv("FHD_DB_WRITE_TOKEN", "secret")
        gate = build_write_approval_gate("e")
        assert gate("import_excel_to_database", {})["ok"] is True

    def test_write_tool_without_approval_returns_verdict(self, monkeypatch):
        # 无 env token、无 approved_write：进入审批引擎评估，返回 dict（auto 放行或 pending 拦截）
        monkeypatch.delenv("FHD_DB_WRITE_TOKEN", raising=False)
        gate = build_write_approval_gate("e")
        verdict = gate("import_excel_to_database", {"foo": "bar"})
        assert "ok" in verdict
        if verdict["ok"] is False:
            assert "reason" in verdict


class TestComposeGates:
    def test_all_none_returns_none(self):
        assert compose_gates(None, None) is None

    def test_single_gate_passthrough(self):
        g = lambda name, args: {"ok": True}  # noqa: E731
        combined = compose_gates(g, None)
        assert combined("t", {})["ok"] is True

    def test_returns_first_failure(self):
        g_ok = lambda name, args: {"ok": True}  # noqa: E731
        g_block = lambda name, args: {"ok": False, "reason": "blocked"}  # noqa: E731
        combined = compose_gates(g_ok, g_block)
        verdict = combined("t", {})
        assert verdict["ok"] is False
        assert verdict["reason"] == "blocked"

    def test_all_pass(self):
        g1 = lambda name, args: {"ok": True}  # noqa: E731
        g2 = lambda name, args: {"ok": True}  # noqa: E731
        assert compose_gates(g1, g2)("t", {})["ok"] is True

    def test_gate_raising_recoverable_is_skipped(self):
        def boom(name, args):
            raise ValueError("recoverable")

        g_ok = lambda name, args: {"ok": True}  # noqa: E731
        combined = compose_gates(boom, g_ok)
        # boom 抛 ValueError（在 RECOVERABLE_ERRORS 内）→ 被跳过，最终放行
        assert combined("t", {})["ok"] is True

    def test_verdict_missing_ok_defaults_true(self):
        g = lambda name, args: {}  # noqa: E731
        assert compose_gates(g)("t", {})["ok"] is True
