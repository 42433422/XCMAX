"""employee_runtime.write_approval 写操作审批门 + compose_gates 单元测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.application.employee_runtime.write_approval import (
    build_write_approval_gate,
    compose_gates,
)


class TestComposeGates:
    def test_all_none_returns_none(self):
        assert compose_gates(None, None) is None

    def test_single_gate_passthrough(self):
        g = lambda name, args: {"ok": True}
        combined = compose_gates(g, None)
        assert combined("t", {})["ok"] is True

    def test_returns_first_failure(self):
        g_ok = lambda name, args: {"ok": True}
        g_block = lambda name, args: {"ok": False, "reason": "blocked"}
        combined = compose_gates(g_ok, g_block)
        verdict = combined("t", {})
        assert verdict["ok"] is False
        assert verdict["reason"] == "blocked"

    def test_all_pass(self):
        g1 = lambda name, args: {"ok": True}
        g2 = lambda name, args: {"ok": True}
        assert compose_gates(g1, g2)("t", {})["ok"] is True

    def test_gate_raising_recoverable_blocks(self):
        def boom(name, args):
            raise ValueError("recoverable")

        g_ok = lambda name, args: {"ok": True}
        combined = compose_gates(boom, g_ok)
        assert combined("t", {})["ok"] is False

    @pytest.mark.parametrize("verdict", [{}, None, [], {"ok": 1}, {"ok": "yes"}])
    def test_invalid_verdict_blocks(self, verdict):
        assert compose_gates(lambda name, args: verdict)("t", {})["ok"] is False
