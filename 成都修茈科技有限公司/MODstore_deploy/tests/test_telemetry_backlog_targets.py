"""telemetry_backlog_loop 信号路由目标员工。"""

from modstore_server.telemetry_backlog_loop import _target_employees_for_signal


def test_coverage_drop_targets_fhd_maintainer():
    ids = _target_employees_for_signal("coverage_drop")
    assert "fhd-core-maintainer" in ids


def test_market_signal_targets_intake():
    ids = _target_employees_for_signal("market_signal")
    assert "intake-dispatcher" in ids
