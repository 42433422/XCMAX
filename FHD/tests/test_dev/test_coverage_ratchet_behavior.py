"""test_coverage_ratchet_behavior.py — coverage_ratchet.py 的 --behavior（Delta A）口径测试。

Delta A（P0-1）：后端覆盖率门禁唯一硬 gate 切换为行为口径（``-m 'not coverage_ramp'``，
排除行覆盖率填充 stub 注水）。覆盖：
- ``--check --behavior``：缺 coverage-behavior.json（require-backend 时失败 / 否则跳过）
- ``--check --behavior``：行为行/分支回退 → 退出码 1；达到 floor → 通过
- 向后兼容：不带 ``--behavior`` 时完全不读行为 json（即便其值低于 floor）
- ``--bump --behavior``：行为 floor 只升不降并写入 baseline + last_measured
- ``append_history`` 在 beh 存在时记录 behavior_lines/branches
"""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from scripts.dev import coverage_ratchet as cr


@pytest.fixture
def isolated_ratchet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """重定向所有模块级路径到 tmp_path，避免污染真实 metrics/。"""
    monkeypatch.setattr(cr, "FHD_ROOT", tmp_path)
    monkeypatch.setattr(cr, "PYPROJECT", tmp_path / "pyproject.toml")
    monkeypatch.setattr(cr, "VITEST_CONFIG", tmp_path / "vitest.config.js")
    monkeypatch.setattr(cr, "BACKEND_JSON_DEFAULT", tmp_path / "coverage.json")
    monkeypatch.setattr(cr, "BEHAVIOR_JSON_DEFAULT", tmp_path / "coverage-behavior.json")
    monkeypatch.setattr(cr, "FRONTEND_SUMMARY_DEFAULT", tmp_path / "coverage-summary.json")
    monkeypatch.setattr(cr, "BASELINE", tmp_path / "coverage_ratchet_baseline.json")
    monkeypatch.setattr(cr, "DUAL_SUMMARY", tmp_path / "coverage-dual-summary.json")
    monkeypatch.setattr(cr, "HISTORY", tmp_path / "coverage-history.jsonl")
    monkeypatch.setattr(cr, "_git_short_sha", lambda: "abc1234")
    return tmp_path


def _write_pyproject(fail_under: int = 88) -> str:
    return (
        "[tool.coverage.run]\n"
        "source = ['app']\n"
        "\n"
        "[tool.coverage.report]\n"
        f"fail_under = {fail_under}\n"
    )


def _write_backend_json(
    *, num_st: int = 100, cov_ln: int = 88, num_br: int = 100, cov_br: int = 81
) -> dict:
    return {
        "totals": {
            "num_statements": num_st,
            "covered_lines": cov_ln,
            "num_branches": num_br,
            "covered_branches": cov_br,
            "missing_lines": num_st - cov_ln,
        }
    }


def _write_behavior_floors(*, lines: int = 80, branches: int = 70) -> str:
    return json.dumps({"behavior_floors": {"lines": lines, "branches": branches}})


class TestCheckBehavior:
    def _make_args(self, **overrides):
        defaults: dict = {
            "coverage_json": cr.BACKEND_JSON_DEFAULT,
            "behavior_json": cr.BEHAVIOR_JSON_DEFAULT,
            "frontend_summary": cr.FRONTEND_SUMMARY_DEFAULT,
            "require_backend": False,
            "require_frontend": False,
            "record": False,
            "peak_floor": False,
            "behavior": True,
        }
        defaults.update(overrides)
        return Namespace(**defaults)

    def test_no_behavior_json_with_require_backend_returns_1(
        self, isolated_ratchet: Path, capsys: pytest.CaptureFixture
    ):
        cr.PYPROJECT.write_text(_write_pyproject(88), encoding="utf-8")
        cr.BASELINE.write_text(_write_behavior_floors(), encoding="utf-8")
        # 写 coverage.json（backend 通过），但缺 coverage-behavior.json → 行为 gate 失败
        cr.BACKEND_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=88, cov_br=81)), encoding="utf-8"
        )
        code = cr.cmd_check(self._make_args(require_backend=True))
        assert code == 1
        err = capsys.readouterr().err
        assert "缺行为覆盖率" in err
        assert "coverage-behavior.json" in err

    def test_no_behavior_json_without_require_skips(self, isolated_ratchet: Path, capsys):
        cr.PYPROJECT.write_text(_write_pyproject(88), encoding="utf-8")
        cr.BASELINE.write_text(_write_behavior_floors(), encoding="utf-8")
        code = cr.cmd_check(self._make_args())
        assert code == 0
        out = capsys.readouterr().out
        assert "跳过行为覆盖率" in out

    def test_behavior_line_below_floor_returns_1(self, isolated_ratchet: Path, capsys):
        cr.PYPROJECT.write_text(_write_pyproject(88), encoding="utf-8")
        cr.BASELINE.write_text(_write_behavior_floors(lines=80, branches=70), encoding="utf-8")
        # 行为行覆盖率 75 < floor 80 → 失败
        cr.BEHAVIOR_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=75, cov_br=70)), encoding="utf-8"
        )
        code = cr.cmd_check(self._make_args())
        assert code == 1
        err = capsys.readouterr().err
        assert "behavior line coverage regression" in err

    def test_behavior_branch_below_floor_returns_1(self, isolated_ratchet: Path, capsys):
        cr.PYPROJECT.write_text(_write_pyproject(88), encoding="utf-8")
        cr.BASELINE.write_text(_write_behavior_floors(lines=80, branches=70), encoding="utf-8")
        # 行为分支覆盖率 60 < floor 70 → 失败
        cr.BEHAVIOR_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=85, cov_br=60)), encoding="utf-8"
        )
        code = cr.cmd_check(self._make_args())
        assert code == 1
        err = capsys.readouterr().err
        assert "behavior branch coverage regression" in err

    def test_behavior_at_floor_passes(self, isolated_ratchet: Path, capsys):
        cr.PYPROJECT.write_text(_write_pyproject(88), encoding="utf-8")
        cr.BASELINE.write_text(_write_behavior_floors(lines=80, branches=70), encoding="utf-8")
        # 行为行 80 = floor 80（+jitter 0.5 ≥ 80）→ 通过；分支 70 = floor 70 → 通过
        cr.BEHAVIOR_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=80, cov_br=70)), encoding="utf-8"
        )
        code = cr.cmd_check(self._make_args())
        assert code == 0
        out = capsys.readouterr().out
        assert "behavior line=80.0%" in out
        assert "OK" in out

    def test_jitter_allows_small_behavior_regression(self, isolated_ratchet: Path):
        # floor line=80，实测 79.6 → 79.6 + jitter 0.5 = 80.1 ≥ 80 通过
        cr.PYPROJECT.write_text(_write_pyproject(88), encoding="utf-8")
        cr.BASELINE.write_text(_write_behavior_floors(lines=80, branches=70), encoding="utf-8")
        cr.BEHAVIOR_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=1000, cov_ln=796, cov_br=700)), encoding="utf-8"
        )
        code = cr.cmd_check(self._make_args())
        assert code == 0

    def test_backward_compat_no_behavior_flag_ignores_behavior_json(
        self, isolated_ratchet: Path, capsys
    ):
        # 不带 --behavior：即便 coverage-behavior.json 存在且低于 floor 也不检查
        cr.PYPROJECT.write_text(_write_pyproject(88), encoding="utf-8")
        cr.BASELINE.write_text(_write_behavior_floors(lines=80, branches=70), encoding="utf-8")
        cr.BACKEND_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=88, cov_br=81)), encoding="utf-8"
        )
        cr.BEHAVIOR_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=10, cov_br=5)), encoding="utf-8"
        )
        code = cr.cmd_check(self._make_args(behavior=False))
        assert code == 0
        out = capsys.readouterr().out
        # 行为分支覆盖 5% 远低于 floor 70，但不带 --behavior 时不应触发失败
        assert "OK" in out
        assert "behavior" not in out

    def test_no_behavior_floors_in_baseline_does_not_fail(self, isolated_ratchet: Path, capsys):
        # baseline 无 behavior_floors 时，行为检查打印 floor None 但不阻断
        cr.PYPROJECT.write_text(_write_pyproject(88), encoding="utf-8")
        cr.BASELINE.write_text(json.dumps({"backend_branch_floor": 81}), encoding="utf-8")
        cr.BEHAVIOR_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=50, cov_br=30)), encoding="utf-8"
        )
        code = cr.cmd_check(self._make_args())
        assert code == 0
        out = capsys.readouterr().out
        assert "behavior line=50.0%" in out

    def test_record_on_behavior_pass_writes_history(self, isolated_ratchet: Path):
        cr.PYPROJECT.write_text(_write_pyproject(88), encoding="utf-8")
        cr.BASELINE.write_text(_write_behavior_floors(lines=80, branches=70), encoding="utf-8")
        cr.BEHAVIOR_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=85, cov_br=75)), encoding="utf-8"
        )
        code = cr.cmd_check(self._make_args(record=True))
        assert code == 0
        rec = json.loads(cr.HISTORY.read_text(encoding="utf-8").strip())
        assert rec["note"] == "check"
        assert rec["behavior_lines"] == 85.0
        assert rec["behavior_branches"] == 75.0


class TestBumpBehavior:
    def _make_args(self, **overrides):
        defaults: dict = {
            "coverage_json": cr.BACKEND_JSON_DEFAULT,
            "behavior_json": cr.BEHAVIOR_JSON_DEFAULT,
            "frontend_summary": cr.FRONTEND_SUMMARY_DEFAULT,
            "margin": cr.DEFAULT_MARGIN,
            "no_vitest": False,
            "behavior": True,
        }
        defaults.update(overrides)
        return Namespace(**defaults)

    def test_bump_raises_behavior_floors_only_up(self, isolated_ratchet: Path, capsys):
        cr.PYPROJECT.write_text(_write_pyproject(88), encoding="utf-8")
        cr.BASELINE.write_text(_write_behavior_floors(lines=80, branches=70), encoding="utf-8")
        # 实测 line=85 → _floor(85,1)=84 > 80 → 提升；branch=75 → _floor(75,1)=74 > 70 → 提升
        cr.BEHAVIOR_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=85, cov_br=75)), encoding="utf-8"
        )
        code = cr.cmd_bump(self._make_args())
        assert code == 0
        baseline = json.loads(cr.BASELINE.read_text(encoding="utf-8"))
        assert baseline["behavior_floors"]["lines"] == 84
        assert baseline["behavior_floors"]["branches"] == 74
        assert baseline["last_measured"]["behavior_lines"] == 85.0
        assert baseline["last_measured"]["behavior_branches"] == 75.0
        out = capsys.readouterr().out
        assert "behavior 行 floor" in out
        assert "behavior 分支 floor" in out

    def test_bump_does_not_lower_behavior_floors(self, isolated_ratchet: Path, capsys):
        cr.PYPROJECT.write_text(_write_pyproject(88), encoding="utf-8")
        cr.BASELINE.write_text(_write_behavior_floors(lines=90, branches=85), encoding="utf-8")
        # 实测低于现有 floor → 不降（只升不降）
        cr.BEHAVIOR_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=80, cov_br=70)), encoding="utf-8"
        )
        code = cr.cmd_bump(self._make_args())
        assert code == 0
        baseline = json.loads(cr.BASELINE.read_text(encoding="utf-8"))
        assert baseline["behavior_floors"]["lines"] == 90
        assert baseline["behavior_floors"]["branches"] == 85
        out = capsys.readouterr().out
        assert "无提升" in out

    def test_bump_without_behavior_flag_ignores_behavior_json(self, isolated_ratchet: Path, capsys):
        cr.PYPROJECT.write_text(_write_pyproject(88), encoding="utf-8")
        # baseline 不含 behavior_floors
        cr.BASELINE.write_text(json.dumps({"backend_branch_floor": 81}), encoding="utf-8")
        cr.BEHAVIOR_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=95, cov_br=90)), encoding="utf-8"
        )
        code = cr.cmd_bump(self._make_args(behavior=False))
        assert code == 0
        baseline = json.loads(cr.BASELINE.read_text(encoding="utf-8"))
        # 不带 --behavior 时不应写入 behavior_floors
        assert "behavior_floors" not in baseline
        out = capsys.readouterr().out
        assert "无提升" in out


class TestAppendHistoryBehavior:
    def test_records_behavior_fields(self, isolated_ratchet: Path):
        be = {"line_pct": 88.0, "branch_pct": 81.0, "num_statements": 100}
        beh = {"line_pct": 85.0, "branch_pct": 75.0, "num_statements": 50}
        cr.append_history(be, None, note="bump", beh=beh)
        rec = json.loads(cr.HISTORY.read_text(encoding="utf-8").strip())
        assert rec["behavior_lines"] == 85.0
        assert rec["behavior_branches"] == 75.0
        assert rec["backend_lines"] == 88.0

    def test_records_none_when_no_behavior(self, isolated_ratchet: Path):
        be = {"line_pct": 88.0, "branch_pct": 81.0, "num_statements": 100}
        cr.append_history(be, None, note="bump")
        rec = json.loads(cr.HISTORY.read_text(encoding="utf-8").strip())
        assert rec["behavior_lines"] is None
        assert rec["behavior_branches"] is None
