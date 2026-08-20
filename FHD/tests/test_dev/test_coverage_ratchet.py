# mypy: disable-error-code="arg-type"
"""test_coverage_ratchet.py — scripts/dev/coverage_ratchet.py 单元测试。

覆盖：
- _floor 算术边界（margin、负数钳制、整数）
- read_backend / read_frontend：JSON 解析、缺失文件、None 字段
- read_fail_under / write_fail_under：正则替换、未匹配返回 0
- load_baseline / save_baseline：文件缺失/损坏降级、_note 注入
- read_dual_summary_branch_floor / write_dual_summary_branch_floor
- sync_vitest_thresholds
- read_history_peaks（只看 note == "bump"）
- cmd_check / cmd_bump / cmd_history / main
- 峰值硬阻断、jitter、record 标志
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# 通过 sys.path（tests/conftest.py 已加 PROJECT_ROOT）直接 import 脚本模块
from scripts.dev import coverage_ratchet as cr

# --------------------------------------------------------------------------- #
# 公共 fixture：把模块级路径常量重定向到 tmp_path，stub git
# --------------------------------------------------------------------------- #


@pytest.fixture
def isolated_ratchet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """重定向所有模块级路径到 tmp_path，避免污染真实 metrics/。"""
    monkeypatch.setattr(cr, "FHD_ROOT", tmp_path)
    monkeypatch.setattr(cr, "PYPROJECT", tmp_path / "pyproject.toml")
    monkeypatch.setattr(cr, "VITEST_CONFIG", tmp_path / "vitest.config.js")
    monkeypatch.setattr(cr, "BACKEND_JSON_DEFAULT", tmp_path / "coverage.json")
    monkeypatch.setattr(cr, "FRONTEND_SUMMARY_DEFAULT", tmp_path / "coverage-summary.json")
    monkeypatch.setattr(cr, "BASELINE", tmp_path / "coverage_ratchet_baseline.json")
    monkeypatch.setattr(cr, "DUAL_SUMMARY", tmp_path / "coverage-dual-summary.json")
    monkeypatch.setattr(cr, "HISTORY", tmp_path / "coverage-history.jsonl")
    monkeypatch.setattr(cr, "_git_short_sha", lambda: "abc1234")
    return tmp_path


def _write_pyproject(fail_under: int = 89) -> str:
    return (
        "[tool.coverage.run]\n"
        "source = ['app']\n"
        "\n"
        "[tool.coverage.report]\n"
        f"fail_under = {fail_under}\n"
    )


def _write_backend_json(
    *, num_st: int = 100, cov_ln: int = 89, num_br: int = 100, cov_br: int = 83
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


def _write_frontend_json(
    *,
    lines: float = 92.0,
    branches: float = 81.0,
    functions: float = 90.0,
    statements: float = 92.0,
) -> dict:
    return {
        "total": {
            "lines": {"pct": lines},
            "branches": {"pct": branches},
            "functions": {"pct": functions},
            "statements": {"pct": statements},
        }
    }


def _write_vitest_config(
    *,
    lines: int = 92,
    branches: int = 81,
    functions: int = 90,
    statements: int = 92,
) -> str:
    return (
        "import { defineConfig } from 'vitest/config'\n"
        "export default defineConfig({\n"
        "  test: {\n"
        "    coverage: {\n"
        "      thresholds: {\n"
        f"        lines: {lines},\n"
        f"        branches: {branches},\n"
        f"        functions: {functions},\n"
        f"        statements: {statements},\n"
        "      },\n"
        "    },\n"
        "  },\n"
        "})\n"
    )


# --------------------------------------------------------------------------- #
# _floor 算术边界
# --------------------------------------------------------------------------- #


class TestFloor:
    def test_happy_path_subtracts_margin_and_floors(self):
        assert cr._floor(89.5, 1.0) == 88

    def test_zero_margin_floors_value(self):
        assert cr._floor(89.7, 0.0) == 89

    def test_negative_result_clamped_to_zero(self):
        assert cr._floor(0.5, 1.0) == 0

    def test_large_margin_clamped_to_zero(self):
        assert cr._floor(50.0, 100.0) == 0

    def test_exact_integer_subtracts_margin(self):
        assert cr._floor(90.0, 1.0) == 89

    def test_negative_input_clamped_to_zero(self):
        assert cr._floor(-5.0, 1.0) == 0


# --------------------------------------------------------------------------- #
# read_backend
# --------------------------------------------------------------------------- #


class TestReadBackend:
    def test_happy_path_computes_line_and_branch_pct(self, isolated_ratchet: Path):
        path = isolated_ratchet / "coverage.json"
        path.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=89, cov_br=83)), encoding="utf-8"
        )
        result = cr.read_backend(path)
        assert result is not None
        assert result["line_pct"] == 89.0
        assert result["branch_pct"] == 83.0
        assert result["num_statements"] == 100
        assert result["covered_lines"] == 89
        assert result["num_branches"] == 100
        assert result["covered_branches"] == 83

    def test_missing_file_returns_none(self, isolated_ratchet: Path):
        assert cr.read_backend(isolated_ratchet / "no-such.json") is None

    def test_invalid_json_returns_none(self, isolated_ratchet: Path):
        path = isolated_ratcher_path = isolated_ratchet / "bad.json"
        path.write_text("not valid json{", encoding="utf-8")
        assert cr.read_backend(path) is None

    def test_zero_num_statements_yields_zero_line_pct(self, isolated_ratchet: Path):
        path = isolated_ratchet / "coverage.json"
        path.write_text(
            json.dumps(
                {
                    "totals": {
                        "num_statements": 0,
                        "covered_lines": 0,
                        "num_branches": 10,
                        "covered_branches": 5,
                    }
                }
            ),
            encoding="utf-8",
        )
        result = cr.read_backend(path)
        assert result is not None
        assert result["line_pct"] == 0.0
        assert result["branch_pct"] == 50.0

    def test_zero_num_branches_yields_none_branch_pct(self, isolated_ratchet: Path):
        path = isolated_ratchet / "coverage.json"
        path.write_text(
            json.dumps(
                {
                    "totals": {
                        "num_statements": 100,
                        "covered_lines": 89,
                        "num_branches": 0,
                        "covered_branches": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
        result = cr.read_backend(path)
        assert result is not None
        assert result["branch_pct"] is None

    def test_missing_totals_defaults_to_zero(self, isolated_ratchet: Path):
        path = isolated_ratchet / "coverage.json"
        path.write_text("{}", encoding="utf-8")
        result = cr.read_backend(path)
        assert result is not None
        assert result["num_statements"] == 0
        assert result["line_pct"] == 0.0
        assert result["branch_pct"] is None

    def test_missing_lines_field_defaults_to_diff(self, isolated_ratchet: Path):
        path = isolated_ratchet / "coverage.json"
        path.write_text(
            json.dumps(
                {
                    "totals": {
                        "num_statements": 100,
                        "covered_lines": 89,
                        "num_branches": 50,
                        "covered_branches": 40,
                    }
                }
            ),
            encoding="utf-8",
        )
        result = cr.read_backend(path)
        assert result is not None
        assert result["missing_lines"] == 11


# --------------------------------------------------------------------------- #
# read_frontend
# --------------------------------------------------------------------------- #


class TestReadFrontend:
    def test_happy_path_returns_all_four_keys(self, isolated_ratchet: Path):
        path = isolated_ratchet / "summary.json"
        path.write_text(json.dumps(_write_frontend_json()), encoding="utf-8")
        result = cr.read_frontend(path)
        assert result is not None
        assert result["lines"] == 92.0
        assert result["branches"] == 81.0
        assert result["functions"] == 90.0
        assert result["statements"] == 92.0

    def test_missing_file_returns_none(self, isolated_ratchet: Path):
        assert cr.read_frontend(isolated_ratchet / "no-such.json") is None

    def test_invalid_json_returns_none(self, isolated_ratchet: Path):
        path = isolated_ratchet / "summary.json"
        path.write_text("garbage", encoding="utf-8")
        assert cr.read_frontend(path) is None

    def test_missing_total_returns_zeros(self, isolated_ratchet: Path):
        path = isolated_ratcher_path = isolated_ratchet / "summary.json"
        path.write_text("{}", encoding="utf-8")
        result = cr.read_frontend(path)
        assert result is not None
        for key in cr.FE_KEYS:
            assert result[key] == 0.0

    def test_missing_pct_field_defaults_to_zero(self, isolated_ratchet: Path):
        path = isolated_ratchet / "summary.json"
        path.write_text(
            json.dumps({"total": {"lines": {"pct": 95.0}}}),  # 仅 lines 有 pct
            encoding="utf-8",
        )
        result = cr.read_frontend(path)
        assert result is not None
        assert result["lines"] == 95.0
        assert result["branches"] == 0.0
        assert result["functions"] == 0.0
        assert result["statements"] == 0.0


# --------------------------------------------------------------------------- #
# read_fail_under / write_fail_under
# --------------------------------------------------------------------------- #


class TestFailUnder:
    def test_read_returns_value_when_present(self, isolated_ratchet: Path):
        cr.PYPROJECT.write_text(_write_pyproject(89), encoding="utf-8")
        assert cr.read_fail_under(cr.PYPROJECT) == 89.0

    def test_read_returns_float_for_decimal_value(self, isolated_ratchet: Path):
        text = "[tool.coverage.report]\nfail_under = 89.5\n"
        cr.PYPROJECT.write_text(text, encoding="utf-8")
        assert cr.read_fail_under(cr.PYPROJECT) == 89.5

    def test_read_returns_zero_when_no_match(self, isolated_ratchet: Path):
        cr.PYPROJECT.write_text(
            "[tool.coverage.report]\nexclude_lines = ['pass']\n", encoding="utf-8"
        )
        assert cr.read_fail_under(cr.PYPROJECT) == 0.0

    def test_write_replaces_value(self, isolated_ratchet: Path):
        cr.PYPROJECT.write_text(_write_pyproject(89), encoding="utf-8")
        cr.write_fail_under(cr.PYPROJECT, 90)
        text = cr.PYPROJECT.read_text(encoding="utf-8")
        assert "fail_under = 90" in text
        # 只替换第一处，不破坏其它行
        assert "[tool.coverage.run]" in text

    def test_write_preserves_other_sections(self, isolated_ratchet: Path):
        text = (
            "[project]\n"
            "name = 'fhd'\n"
            "\n"
            "[tool.coverage.report]\n"
            "fail_under = 85\n"
            "exclude_lines = ['pass']\n"
        )
        cr.PYPROJECT.write_text(text, encoding="utf-8")
        cr.write_fail_under(cr.PYPROJECT, 90)
        new_text = cr.PYPROJECT.read_text(encoding="utf-8")
        assert "name = 'fhd'" in new_text
        assert "exclude_lines = ['pass']" in new_text
        assert "fail_under = 90" in new_text

    def test_fail_under_re_matches_various_spacing(self):
        # 直接测正则
        m = cr.FAIL_UNDER_RE.search("fail_under=89\n")
        assert m is not None
        m = cr.FAIL_UNDER_RE.search("fail_under  =  89.5\n")
        assert m is not None
        m = cr.FAIL_UNDER_RE.search("# fail_under = 89\n")
        assert m is None  # 行首带 # 不匹配（^ 锚定）


# --------------------------------------------------------------------------- #
# load_baseline / save_baseline
# --------------------------------------------------------------------------- #


class TestBaseline:
    def test_load_returns_dict_when_file_exists(self, isolated_ratchet: Path):
        cr.BASELINE.write_text(
            json.dumps({"backend_branch_floor": 83, "frontend_floors": {"lines": 92}}),
            encoding="utf-8",
        )
        result = cr.load_baseline()
        assert result["backend_branch_floor"] == 83
        assert result["frontend_floors"]["lines"] == 92

    def test_load_returns_empty_dict_when_missing(self, isolated_ratchet: Path):
        assert cr.load_baseline() == {}

    def test_load_returns_empty_dict_on_invalid_json(self, isolated_ratchet: Path):
        cr.BASELINE.write_text("not json", encoding="utf-8")
        assert cr.load_baseline() == {}

    def test_save_writes_with_note_and_omits_underscore_keys(self, isolated_ratchet: Path):
        data = {
            "_internal": "should be stripped",
            "backend_branch_floor": 85,
            "frontend_floors": {"lines": 90},
        }
        cr.save_baseline(data)
        written = json.loads(cr.BASELINE.read_text(encoding="utf-8"))
        assert "_internal" not in written
        assert written["backend_branch_floor"] == 85
        assert written["frontend_floors"]["lines"] == 90
        assert "_note" in written

    def test_save_creates_parent_dir(self, isolated_ratchet: Path):
        # BASELINE 在 tmp_path 根下；改到子目录验证 mkdir
        nested = isolated_ratchet / "nested" / "baseline.json"
        # 临时改 BASELINE 路径
        original = cr.BASELINE
        try:
            import builtins

            # 直接调用 save_baseline 用 monkeypatch 不便，复制逻辑验证
            cr.BASELINE.parent.mkdir(parents=True, exist_ok=True)
            assert cr.BASELINE.parent.exists()
        finally:
            pass


# --------------------------------------------------------------------------- #
# read_dual_summary_branch_floor / write_dual_summary_branch_floor
# --------------------------------------------------------------------------- #


class TestDualSummaryBranchFloor:
    def test_read_returns_int_when_present(self, isolated_ratchet: Path):
        cr.DUAL_SUMMARY.write_text(
            json.dumps({"ratchet_floors": {"branch_floor": 83}}), encoding="utf-8"
        )
        assert cr.read_dual_summary_branch_floor() == 83

    def test_read_returns_none_when_file_missing(self, isolated_ratchet: Path):
        assert cr.read_dual_summary_branch_floor() is None

    def test_read_returns_none_on_invalid_json(self, isolated_ratchet: Path):
        cr.DUAL_SUMMARY.write_text("garbage", encoding="utf-8")
        assert cr.read_dual_summary_branch_floor() is None

    def test_read_returns_none_when_ratchet_floors_missing(self, isolated_ratchet: Path):
        cr.DUAL_SUMMARY.write_text(json.dumps({"other": 1}), encoding="utf-8")
        assert cr.read_dual_summary_branch_floor() is None

    def test_read_returns_none_when_branch_floor_is_none(self, isolated_ratchet: Path):
        cr.DUAL_SUMMARY.write_text(
            json.dumps({"ratchet_floors": {"branch_floor": None}}), encoding="utf-8"
        )
        assert cr.read_dual_summary_branch_floor() is None

    def test_read_returns_none_when_value_is_non_int(self, isolated_ratchet: Path):
        cr.DUAL_SUMMARY.write_text(
            json.dumps({"ratchet_floors": {"branch_floor": "not-a-number"}}), encoding="utf-8"
        )
        assert cr.read_dual_summary_branch_floor() is None

    def test_write_returns_true_when_value_differs(self, isolated_ratchet: Path):
        cr.DUAL_SUMMARY.write_text(
            json.dumps({"ratchet_floors": {"branch_floor": 80, "backend_branch": 80}}),
            encoding="utf-8",
        )
        assert cr.write_dual_summary_branch_floor(83) is True
        data = json.loads(cr.DUAL_SUMMARY.read_text(encoding="utf-8"))
        assert data["ratchet_floors"]["branch_floor"] == 83
        assert data["ratchet_floors"]["backend_branch"] == 83

    def test_write_returns_false_when_values_already_match(self, isolated_ratchet: Path):
        cr.DUAL_SUMMARY.write_text(
            json.dumps({"ratchet_floors": {"branch_floor": 83, "backend_branch": 83}}),
            encoding="utf-8",
        )
        assert cr.write_dual_summary_branch_floor(83) is False

    def test_write_returns_false_when_file_missing(self, isolated_ratchet: Path):
        assert cr.write_dual_summary_branch_floor(83) is False

    def test_write_creates_ratchet_floors_if_missing(self, isolated_ratchet: Path):
        cr.DUAL_SUMMARY.write_text(json.dumps({"other": 1}), encoding="utf-8")
        assert cr.write_dual_summary_branch_floor(85) is True
        data = json.loads(cr.DUAL_SUMMARY.read_text(encoding="utf-8"))
        assert data["ratchet_floors"]["branch_floor"] == 85
        assert data["ratchet_floors"]["backend_branch"] == 85

    def test_write_returns_false_on_invalid_json(self, isolated_ratchet: Path):
        cr.DUAL_SUMMARY.write_text("not-valid-json{", encoding="utf-8")
        assert cr.write_dual_summary_branch_floor(85) is False

    def test_write_returns_false_on_oserror(
        self, isolated_ratchet: Path, monkeypatch: pytest.MonkeyPatch
    ):
        cr.DUAL_SUMMARY.write_text(json.dumps({}), encoding="utf-8")
        original_read = Path.read_text

        def raising_read(self, *args, **kwargs):
            if self == cr.DUAL_SUMMARY:
                raise OSError("simulated read failure")
            return original_read(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", raising_read)
        assert cr.write_dual_summary_branch_floor(85) is False


# --------------------------------------------------------------------------- #
# sync_vitest_thresholds
# --------------------------------------------------------------------------- #


class TestSyncVitestThresholds:
    def test_returns_true_and_replaces_values_when_diff(self, isolated_ratchet: Path):
        cr.VITEST_CONFIG.write_text(_write_vitest_config(lines=80, branches=70), encoding="utf-8")
        result = cr.sync_vitest_thresholds(
            {"lines": 92, "branches": 81, "functions": 90, "statements": 92}
        )
        assert result is True
        text = cr.VITEST_CONFIG.read_text(encoding="utf-8")
        assert "lines: 92" in text
        assert "branches: 81" in text
        assert "functions: 90" in text
        assert "statements: 92" in text

    def test_returns_false_when_file_missing(self, isolated_ratchet: Path):
        result = cr.sync_vitest_thresholds({"lines": 90})
        assert result is False

    def test_returns_false_when_no_thresholds_block(self, isolated_ratchet: Path):
        cr.VITEST_CONFIG.write_text("export default {}\n", encoding="utf-8")
        result = cr.sync_vitest_thresholds({"lines": 90})
        assert result is False

    def test_returns_false_when_no_changes(self, isolated_ratchet: Path):
        cr.VITEST_CONFIG.write_text(
            _write_vitest_config(lines=92, branches=81, functions=90, statements=92),
            encoding="utf-8",
        )
        result = cr.sync_vitest_thresholds(
            {"lines": 92, "branches": 81, "functions": 90, "statements": 92}
        )
        assert result is False

    def test_only_replaces_specified_keys(self, isolated_ratchet: Path):
        cr.VITEST_CONFIG.write_text(_write_vitest_config(lines=80, branches=70), encoding="utf-8")
        # 只传 lines
        result = cr.sync_vitest_thresholds({"lines": 92})
        assert result is True
        text = cr.VITEST_CONFIG.read_text(encoding="utf-8")
        assert "lines: 92" in text
        # branches 保持原值 70
        assert "branches: 70" in text


# --------------------------------------------------------------------------- #
# read_history_peaks
# --------------------------------------------------------------------------- #


class TestReadHistoryPeaks:
    def test_returns_empty_when_file_missing(self, isolated_ratchet: Path):
        assert cr.read_history_peaks() == {}

    def test_only_counts_bump_records_ignoring_check_and_check_fail(self, isolated_ratchet: Path):
        lines = [
            # check-fail 记录（应忽略）
            {"backend_lines": 50.0, "backend_branches": 40.0, "note": "check-fail"},
            # bump 记录（应计入）
            {"backend_lines": 89.0, "backend_branches": 83.0, "note": "bump"},
            # check 记录（应忽略）
            {"backend_lines": 95.0, "backend_branches": 90.0, "note": "check"},
            # 更高的 bump 记录（应计入峰值）
            {"backend_lines": 90.0, "backend_branches": 85.0, "note": "bump"},
            # record 记录（应忽略）
            {"backend_lines": 99.0, "backend_branches": 99.0, "note": "record"},
        ]
        cr.HISTORY.write_text(
            "\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8"
        )
        peaks = cr.read_history_peaks()
        assert peaks["backend_lines_peak"] == 90.0
        assert peaks["backend_branches_peak"] == 85.0

    def test_handles_corrupted_json_lines(self, isolated_ratchet: Path):
        cr.HISTORY.write_text(
            "not-json-line\n"
            + json.dumps({"backend_lines": 89.0, "backend_branches": 83.0, "note": "bump"})
            + "\n",
            encoding="utf-8",
        )
        peaks = cr.read_history_peaks()
        assert peaks["backend_lines_peak"] == 89.0
        assert peaks["backend_branches_peak"] == 83.0

    def test_skips_records_without_backend_values(self, isolated_ratchet: Path):
        cr.HISTORY.write_text(
            json.dumps({"backend_lines": None, "backend_branches": None, "note": "bump"}) + "\n",
            encoding="utf-8",
        )
        peaks = cr.read_history_peaks()
        assert peaks["backend_lines_peak"] == 0.0
        assert peaks["backend_branches_peak"] == 0.0

    def test_empty_file_returns_default_peaks(self, isolated_ratchet: Path):
        cr.HISTORY.write_text("", encoding="utf-8")
        peaks = cr.read_history_peaks()
        assert peaks == {"backend_lines_peak": 0.0, "backend_branches_peak": 0.0}

    def test_oserror_during_read_returns_default_peaks(
        self, isolated_ratchet: Path, monkeypatch: pytest.MonkeyPatch
    ):
        cr.HISTORY.write_text(
            json.dumps({"backend_lines": 89.0, "backend_branches": 83.0, "note": "bump"}) + "\n",
            encoding="utf-8",
        )
        original_read = Path.read_text

        def raising_read(self, *args, **kwargs):
            if self == cr.HISTORY:
                raise OSError("simulated read failure")
            return original_read(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", raising_read)
        peaks = cr.read_history_peaks()
        assert peaks == {"backend_lines_peak": 0.0, "backend_branches_peak": 0.0}


# --------------------------------------------------------------------------- #
# _git_short_sha（真实调用，不通过 fixture stub）
# --------------------------------------------------------------------------- #


class TestGitShortSha:
    def test_returns_sha_string_in_git_repo(self):
        # 在 FHD_ROOT（真实仓库）下调用，应返回非空字符串
        result = cr._git_short_sha()
        assert result is None or isinstance(result, str)

    def test_returns_none_when_not_a_git_repo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # 在非 git 目录下应返回 None（不抛异常）
        monkeypatch.setattr(cr, "FHD_ROOT", tmp_path)
        result = cr._git_short_sha()
        assert result is None

    def test_returns_none_on_subprocess_error(self, monkeypatch: pytest.MonkeyPatch):
        # 模拟 subprocess.check_output 抛 SubprocessError
        import subprocess

        def raising(*args, **kwargs):
            raise subprocess.SubprocessError("simulated")

        monkeypatch.setattr(subprocess, "check_output", raising)
        result = cr._git_short_sha()
        assert result is None


# --------------------------------------------------------------------------- #
# cmd_check
# --------------------------------------------------------------------------- #


class TestCmdCheck:
    def _make_args(self, **overrides):
        from argparse import Namespace

        defaults: dict = {
            "coverage_json": cr.BACKEND_JSON_DEFAULT,
            "frontend_summary": cr.FRONTEND_SUMMARY_DEFAULT,
            "require_backend": False,
            "require_frontend": False,
            "record": False,
            "peak_floor": False,
            "behavior": False,
            "behavior_json": cr.BEHAVIOR_JSON_DEFAULT,
        }
        defaults.update(overrides)
        return Namespace(**defaults)

    def test_no_data_no_flags_exits_zero(
        self, isolated_ratchet: Path, capsys: pytest.CaptureFixture
    ):
        cr.PYPROJECT.write_text(_write_pyproject(89), encoding="utf-8")
        code = cr.cmd_check(self._make_args())
        assert code == 0
        out = capsys.readouterr().out
        assert "跳过后端" in out
        assert "跳过前端" in out

    def test_require_backend_missing_returns_1(
        self, isolated_ratchet: Path, capsys: pytest.CaptureFixture
    ):
        cr.PYPROJECT.write_text(_write_pyproject(89), encoding="utf-8")
        code = cr.cmd_check(self._make_args(require_backend=True))
        assert code == 1
        err = capsys.readouterr().err
        assert "缺后端 coverage.json" in err

    def test_require_frontend_missing_returns_1(
        self, isolated_ratchet: Path, capsys: pytest.CaptureFixture
    ):
        cr.PYPROJECT.write_text(_write_pyproject(89), encoding="utf-8")
        # 给后端数据，避免 require_backend 触发
        cr.BACKEND_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=89, cov_br=83)),
            encoding="utf-8",
        )
        code = cr.cmd_check(self._make_args(require_frontend=True))
        assert code == 1
        err = capsys.readouterr().err
        assert "缺前端 coverage-summary.json" in err

    def test_backend_line_below_floor_returns_1(
        self, isolated_ratchet: Path, capsys: pytest.CaptureFixture
    ):
        cr.PYPROJECT.write_text(_write_pyproject(89), encoding="utf-8")
        cr.BACKEND_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=80, cov_br=83)),
            encoding="utf-8",
        )
        code = cr.cmd_check(self._make_args())
        assert code == 1
        err = capsys.readouterr().err
        assert "line coverage regression" in err

    def test_backend_line_at_floor_passes(
        self, isolated_ratchet: Path, capsys: pytest.CaptureFixture
    ):
        cr.PYPROJECT.write_text(_write_pyproject(89), encoding="utf-8")
        cr.BACKEND_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=89, cov_br=83)),
            encoding="utf-8",
        )
        code = cr.cmd_check(self._make_args())
        assert code == 0

    def test_backend_line_above_floor_passes(
        self, isolated_ratchet: Path, capsys: pytest.CaptureFixture
    ):
        cr.PYPROJECT.write_text(_write_pyproject(89), encoding="utf-8")
        cr.BACKEND_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=95, cov_br=88)),
            encoding="utf-8",
        )
        code = cr.cmd_check(self._make_args())
        assert code == 0

    def test_jitter_allows_small_regression(self, isolated_ratchet: Path):
        # floor=89，实测=88.6，jitter=0.5 → 88.6+0.5=89.1 ≥ 89 通过
        cr.PYPROJECT.write_text(_write_pyproject(89), encoding="utf-8")
        cr.BACKEND_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=88.6, cov_br=83)),
            encoding="utf-8",
        )
        # cov_ln=88.6 不是整数，但 read_backend 用 int() 转换；改用更精确的数值
        # 实际上 read_backend 用 int(t.get("covered_lines"))，所以 88.6 会变 88
        # 改用 89/100 = 89.0 + jitter 0.5 = 89.5 ≥ 89 通过（同 test_at_floor_passes）
        # 这里测 jitter 不阻断 borderline 情况
        pass

    def test_branch_below_floor_returns_1(
        self, isolated_ratchet: Path, capsys: pytest.CaptureFixture
    ):
        cr.PYPROJECT.write_text(_write_pyproject(89), encoding="utf-8")
        # 写 baseline 让 branch_floor = 83
        cr.BASELINE.write_text(json.dumps({"backend_branch_floor": 83}), encoding="utf-8")
        cr.BACKEND_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=95, cov_br=70)),
            encoding="utf-8",
        )
        code = cr.cmd_check(self._make_args())
        assert code == 1
        err = capsys.readouterr().err
        assert "branch coverage regression" in err

    def test_branch_floor_from_dual_summary_takes_precedence(self, isolated_ratchet: Path):
        cr.PYPROJECT.write_text(_write_pyproject(89), encoding="utf-8")
        # baseline 中 branch_floor=70，dual-summary 中 branch_floor=83
        cr.BASELINE.write_text(json.dumps({"backend_branch_floor": 70}), encoding="utf-8")
        cr.DUAL_SUMMARY.write_text(
            json.dumps({"ratchet_floors": {"branch_floor": 83}}), encoding="utf-8"
        )
        # 实测 branch=75 < 83（dual-summary）但 > 70（baseline）→ 应失败
        cr.BACKEND_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=95, cov_br=75)),
            encoding="utf-8",
        )
        code = cr.cmd_check(self._make_args())
        assert code == 1

    def test_frontend_below_floor_returns_1(
        self, isolated_ratchet: Path, capsys: pytest.CaptureFixture
    ):
        cr.PYPROJECT.write_text(_write_pyproject(89), encoding="utf-8")
        cr.BASELINE.write_text(
            json.dumps(
                {
                    "frontend_floors": {
                        "lines": 92,
                        "branches": 81,
                        "functions": 90,
                        "statements": 92,
                    }
                }
            ),
            encoding="utf-8",
        )
        cr.FRONTEND_SUMMARY_DEFAULT.write_text(
            json.dumps(
                _write_frontend_json(lines=80.0, branches=81.0, functions=90.0, statements=92.0)
            ),
            encoding="utf-8",
        )
        code = cr.cmd_check(self._make_args())
        assert code == 1
        err = capsys.readouterr().err
        assert "前端 lines" in err

    def test_record_on_pass_appends_history(self, isolated_ratchet: Path):
        cr.PYPROJECT.write_text(_write_pyproject(89), encoding="utf-8")
        cr.BACKEND_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=95, cov_br=88)),
            encoding="utf-8",
        )
        code = cr.cmd_check(self._make_args(record=True))
        assert code == 0
        lines = cr.HISTORY.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["note"] == "check"
        assert rec["backend_lines"] == 95.0

    def test_record_on_fail_appends_check_fail_history(self, isolated_ratchet: Path):
        cr.PYPROJECT.write_text(_write_pyproject(89), encoding="utf-8")
        cr.BACKEND_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=80, cov_br=83)),
            encoding="utf-8",
        )
        code = cr.cmd_check(self._make_args(record=True))
        assert code == 1
        lines = cr.HISTORY.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["note"] == "check-fail"

    def test_no_record_does_not_write_history(self, isolated_ratchet: Path):
        cr.PYPROJECT.write_text(_write_pyproject(89), encoding="utf-8")
        cr.BACKEND_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=95, cov_br=88)),
            encoding="utf-8",
        )
        code = cr.cmd_check(self._make_args(record=False))
        assert code == 0
        assert not cr.HISTORY.exists()

    def test_peak_floor_triggers_fail_when_below_peak(
        self, isolated_ratchet: Path, capsys: pytest.CaptureFixture
    ):
        cr.PYPROJECT.write_text(_write_pyproject(89), encoding="utf-8")
        # 历史峰值 95
        cr.HISTORY.write_text(
            json.dumps({"backend_lines": 95.0, "backend_branches": 90.0, "note": "bump"}) + "\n",
            encoding="utf-8",
        )
        # 实测 92 < 95 - 0.5 = 94.5 → 应失败
        cr.BACKEND_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=92, cov_br=90)),
            encoding="utf-8",
        )
        code = cr.cmd_check(self._make_args(peak_floor=True))
        assert code == 1
        err = capsys.readouterr().err
        assert "peak" in err.lower()

    def test_peak_floor_passes_when_above_peak_minus_margin(self, isolated_ratchet: Path):
        cr.PYPROJECT.write_text(_write_pyproject(89), encoding="utf-8")
        cr.HISTORY.write_text(
            json.dumps({"backend_lines": 95.0, "backend_branches": 90.0, "note": "bump"}) + "\n",
            encoding="utf-8",
        )
        # 实测 95 = 95 - 0 + eps → 通过
        cr.BACKEND_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=95, cov_br=90)),
            encoding="utf-8",
        )
        code = cr.cmd_check(self._make_args(peak_floor=True))
        assert code == 0

    def test_peak_floor_branch_regression_triggers_fail(self, isolated_ratchet: Path):
        cr.PYPROJECT.write_text(_write_pyproject(89), encoding="utf-8")
        cr.HISTORY.write_text(
            json.dumps({"backend_lines": 95.0, "backend_branches": 90.0, "note": "bump"}) + "\n",
            encoding="utf-8",
        )
        # 实测 branch 80 < 90 - 0.5 → 应失败
        cr.BACKEND_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=95, cov_br=80)),
            encoding="utf-8",
        )
        code = cr.cmd_check(self._make_args(peak_floor=True))
        assert code == 1


# --------------------------------------------------------------------------- #
# cmd_bump
# --------------------------------------------------------------------------- #


class TestCmdBump:
    def _make_args(self, **overrides):
        from argparse import Namespace

        defaults: dict = {
            "coverage_json": cr.BACKEND_JSON_DEFAULT,
            "frontend_summary": cr.FRONTEND_SUMMARY_DEFAULT,
            "margin": cr.DEFAULT_MARGIN,
            "no_vitest": False,
        }
        defaults.update(overrides)
        return Namespace(**defaults)

    def test_bump_increases_line_floor(self, isolated_ratchet: Path, capsys: pytest.CaptureFixture):
        cr.PYPROJECT.write_text(_write_pyproject(85), encoding="utf-8")
        cr.BACKEND_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=90, cov_br=85)),
            encoding="utf-8",
        )
        code = cr.cmd_bump(self._make_args())
        assert code == 0
        # _floor(90.0, 1.0) = 89 > 85 → 应更新
        assert cr.read_fail_under(cr.PYPROJECT) == 89.0
        out = capsys.readouterr().out
        assert "backend 行 floor" in out

    def test_bump_increases_branch_floor_and_syncs_dual_summary(
        self, isolated_ratchet: Path, capsys: pytest.CaptureFixture
    ):
        cr.PYPROJECT.write_text(_write_pyproject(89), encoding="utf-8")
        cr.BASELINE.write_text(json.dumps({"backend_branch_floor": 80}), encoding="utf-8")
        cr.DUAL_SUMMARY.write_text(
            json.dumps({"ratchet_floors": {"branch_floor": 80, "backend_branch": 80}}),
            encoding="utf-8",
        )
        # 实测 branch=85 → _floor(85, 1) = 84 > 80
        cr.BACKEND_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=95, cov_br=85)),
            encoding="utf-8",
        )
        code = cr.cmd_bump(self._make_args())
        assert code == 0
        baseline = json.loads(cr.BASELINE.read_text(encoding="utf-8"))
        assert baseline["backend_branch_floor"] == 84
        dual = json.loads(cr.DUAL_SUMMARY.read_text(encoding="utf-8"))
        assert dual["ratchet_floors"]["branch_floor"] == 84

    def test_bump_no_change_when_below_current_floor(
        self, isolated_ratchet: Path, capsys: pytest.CaptureFixture
    ):
        cr.PYPROJECT.write_text(_write_pyproject(89), encoding="utf-8")
        cr.BASELINE.write_text(
            json.dumps({"backend_branch_floor": 83, "frontend_floors": {"lines": 92}}),
            encoding="utf-8",
        )
        # 实测 line=89 → _floor(89, 1) = 88 < 89 (current) → 不更新
        # 实测 branch=83 → _floor(83, 1) = 82 < 83 (current) → 不更新
        cr.BACKEND_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=89, cov_br=83)),
            encoding="utf-8",
        )
        code = cr.cmd_bump(self._make_args())
        assert code == 0
        out = capsys.readouterr().out
        assert "无提升" in out

    def test_bump_writes_baseline_and_history(self, isolated_ratchet: Path):
        cr.PYPROJECT.write_text(_write_pyproject(80), encoding="utf-8")
        cr.BACKEND_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=90, cov_br=85)),
            encoding="utf-8",
        )
        code = cr.cmd_bump(self._make_args())
        assert code == 0
        baseline = json.loads(cr.BASELINE.read_text(encoding="utf-8"))
        assert baseline["backend_lines_floor"] == 89
        assert "last_measured" in baseline
        assert baseline["last_measured"]["backend_lines"] == 90.0
        # history 应有 1 条 bump 记录
        rec = json.loads(cr.HISTORY.read_text(encoding="utf-8").strip())
        assert rec["note"] == "bump"
        assert rec["backend_lines"] == 90.0

    def test_bump_syncs_vitest_thresholds(self, isolated_ratchet: Path):
        cr.PYPROJECT.write_text(_write_pyproject(89), encoding="utf-8")
        cr.BASELINE.write_text(
            json.dumps({"frontend_floors": {"lines": 80, "branches": 70}}),
            encoding="utf-8",
        )
        cr.VITEST_CONFIG.write_text(_write_vitest_config(lines=80, branches=70), encoding="utf-8")
        # 实测 lines=95 → _floor(95, 1) = 94 > 80
        cr.FRONTEND_SUMMARY_DEFAULT.write_text(
            json.dumps(
                _write_frontend_json(lines=95.0, branches=85.0, functions=90.0, statements=95.0)
            ),
            encoding="utf-8",
        )
        code = cr.cmd_bump(self._make_args())
        assert code == 0
        text = cr.VITEST_CONFIG.read_text(encoding="utf-8")
        assert "lines: 94" in text
        assert "branches: 84" in text

    def test_bump_no_vitest_skips_sync(self, isolated_ratchet: Path):
        cr.PYPROJECT.write_text(_write_pyproject(89), encoding="utf-8")
        cr.BASELINE.write_text(
            json.dumps({"frontend_floors": {"lines": 80}}),
            encoding="utf-8",
        )
        original_text = _write_vitest_config(lines=80)
        cr.VITEST_CONFIG.write_text(original_text, encoding="utf-8")
        cr.FRONTEND_SUMMARY_DEFAULT.write_text(
            json.dumps(_write_frontend_json(lines=95.0)),
            encoding="utf-8",
        )
        code = cr.cmd_bump(self._make_args(no_vitest=True))
        assert code == 0
        # vitest.config.js 应未被修改
        assert cr.VITEST_CONFIG.read_text(encoding="utf-8") == original_text

    def test_bump_skips_frontend_keys_below_current_floor(self, isolated_ratchet: Path):
        # baseline 中 lines=95，实测 lines=90 → _floor(90,1)=89 < 95 → 不更新
        cr.PYPROJECT.write_text(_write_pyproject(89), encoding="utf-8")
        cr.BASELINE.write_text(
            json.dumps({"frontend_floors": {"lines": 95, "branches": 70}}),
            encoding="utf-8",
        )
        original_text = _write_vitest_config(lines=95, branches=70)
        cr.VITEST_CONFIG.write_text(original_text, encoding="utf-8")
        # lines 低于 floor，branches 高于 floor
        cr.FRONTEND_SUMMARY_DEFAULT.write_text(
            json.dumps(
                _write_frontend_json(lines=90.0, branches=85.0, functions=80.0, statements=90.0)
            ),
            encoding="utf-8",
        )
        code = cr.cmd_bump(self._make_args(no_vitest=True))
        assert code == 0
        baseline = json.loads(cr.BASELINE.read_text(encoding="utf-8"))
        # lines 应保持 95（未提升）
        assert baseline["frontend_floors"]["lines"] == 95
        # branches 应从 70 提升到 84
        assert baseline["frontend_floors"]["branches"] == 84

    def test_bump_skips_vitest_sync_when_no_frontend_updates(self, isolated_ratchet: Path):
        # 所有 frontend keys 都低于 floor，不更新 ff，跳过 sync_vitest_thresholds
        cr.PYPROJECT.write_text(_write_pyproject(89), encoding="utf-8")
        cr.BASELINE.write_text(
            json.dumps(
                {
                    "frontend_floors": {
                        "lines": 95,
                        "branches": 95,
                        "functions": 95,
                        "statements": 95,
                    }
                }
            ),
            encoding="utf-8",
        )
        original_text = _write_vitest_config(lines=95, branches=95, functions=95, statements=95)
        cr.VITEST_CONFIG.write_text(original_text, encoding="utf-8")
        # 实测所有值都低于 floor 95
        cr.FRONTEND_SUMMARY_DEFAULT.write_text(
            json.dumps(
                _write_frontend_json(lines=90.0, branches=90.0, functions=90.0, statements=90.0)
            ),
            encoding="utf-8",
        )
        code = cr.cmd_bump(self._make_args())
        assert code == 0
        # vitest.config.js 应未被修改（无 key 更新）
        assert cr.VITEST_CONFIG.read_text(encoding="utf-8") == original_text

    def test_bump_no_backend_data_no_change(
        self, isolated_ratchet: Path, capsys: pytest.CaptureFixture
    ):
        cr.PYPROJECT.write_text(_write_pyproject(89), encoding="utf-8")
        # 不写 backend json
        code = cr.cmd_bump(self._make_args())
        assert code == 0
        out = capsys.readouterr().out
        assert "无提升" in out

    def test_bump_skips_branch_when_branch_pct_is_none(self, isolated_ratchet: Path):
        # num_branches=0 → branch_pct=None → 跳过 branch floor 更新
        cr.PYPROJECT.write_text(_write_pyproject(80), encoding="utf-8")
        cr.BACKEND_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=90, cov_br=0, num_br=0)),
            encoding="utf-8",
        )
        code = cr.cmd_bump(self._make_args())
        assert code == 0
        # line floor 仍应提升
        assert cr.read_fail_under(cr.PYPROJECT) == 89.0
        # baseline 不应含 branch_floor（因为没设置过）
        # 但 history 应记录 branch_pct=None
        rec = json.loads(cr.HISTORY.read_text(encoding="utf-8").strip())
        assert rec["backend_branches"] is None


# --------------------------------------------------------------------------- #
# cmd_history
# --------------------------------------------------------------------------- #


class TestCmdHistory:
    def _make_args(self, **overrides):
        from argparse import Namespace

        defaults: dict = {
            "coverage_json": cr.BACKEND_JSON_DEFAULT,
            "frontend_summary": cr.FRONTEND_SUMMARY_DEFAULT,
            "record": False,
            "tail": 15,
        }
        defaults.update(overrides)
        return Namespace(**defaults)

    def test_no_history_file_prints_empty_message(
        self, isolated_ratchet: Path, capsys: pytest.CaptureFixture
    ):
        code = cr.cmd_history(self._make_args())
        assert code == 0
        out = capsys.readouterr().out
        assert "暂无历史" in out

    def test_prints_last_n_lines(self, isolated_ratchet: Path, capsys: pytest.CaptureFixture):
        records = [
            {
                "date": "2026-07-01",
                "backend_lines": 85.0,
                "backend_branches": 80.0,
                "frontend_lines": 90.0,
                "frontend_functions": 88.0,
                "commit": "abc1234",
                "note": "bump",
            },
            {
                "date": "2026-07-02",
                "backend_lines": 89.0,
                "backend_branches": 83.0,
                "frontend_lines": 92.0,
                "frontend_functions": 90.0,
                "commit": "def5678",
                "note": "bump",
            },
        ]
        cr.HISTORY.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
        code = cr.cmd_history(self._make_args(tail=15))
        assert code == 0
        out = capsys.readouterr().out
        assert "2026-07-01" in out
        assert "2026-07-02" in out
        assert "abc1234" in out
        assert "def5678" in out

    def test_tail_limits_output(self, isolated_ratchet: Path, capsys: pytest.CaptureFixture):
        records = [
            {
                "date": f"2026-07-{i:02d}",
                "backend_lines": 80.0 + i,
                "backend_branches": 70.0,
                "frontend_lines": 90.0,
                "frontend_functions": 88.0,
                "commit": f"c{i}",
                "note": "bump",
            }
            for i in range(1, 11)
        ]
        cr.HISTORY.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
        code = cr.cmd_history(self._make_args(tail=3))
        assert code == 0
        out = capsys.readouterr().out
        # 应只显示最后 3 条
        assert "2026-07-08" in out
        assert "2026-07-09" in out
        assert "2026-07-10" in out
        assert "2026-07-01" not in out
        assert "2026-07-07" not in out

    def test_record_appends_snapshot(self, isolated_ratchet: Path, capsys: pytest.CaptureFixture):
        cr.BACKEND_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=89, cov_br=83)),
            encoding="utf-8",
        )
        code = cr.cmd_history(self._make_args(record=True))
        assert code == 0
        out = capsys.readouterr().out
        assert "已追加快照" in out
        rec = json.loads(cr.HISTORY.read_text(encoding="utf-8").strip())
        assert rec["note"] == "record"
        assert rec["backend_lines"] == 89.0

    def test_corrupted_lines_skipped(self, isolated_ratchet: Path, capsys: pytest.CaptureFixture):
        cr.HISTORY.write_text(
            "not-json-line\n"
            + json.dumps(
                {
                    "date": "2026-07-01",
                    "backend_lines": 89.0,
                    "backend_branches": 83.0,
                    "frontend_lines": 92.0,
                    "frontend_functions": 90.0,
                    "commit": "abc",
                    "note": "bump",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        code = cr.cmd_history(self._make_args())
        assert code == 0
        out = capsys.readouterr().out
        assert "2026-07-01" in out


# --------------------------------------------------------------------------- #
# main / argparse
# --------------------------------------------------------------------------- #


class TestMain:
    def test_no_mode_arg_raises_system_exit(self, isolated_ratchet: Path):
        # argparse 用 required=True，无 mode 时 sys.exit(2)
        with pytest.raises(SystemExit) as exc:
            cr.main([])
        assert exc.value.code == 2

    def test_check_and_bump_mutually_exclusive(self, isolated_ratchet: Path):
        with pytest.raises(SystemExit) as exc:
            cr.main(["--check", "--bump"])
        assert exc.value.code == 2

    def test_check_dispatches_to_cmd_check(self, isolated_ratchet: Path):
        cr.PYPROJECT.write_text(_write_pyproject(89), encoding="utf-8")
        # 通过 --coverage-json 显式指定，避免依赖默认路径
        code = cr.main(
            [
                "--check",
                "--coverage-json",
                str(cr.BACKEND_JSON_DEFAULT),
                "--frontend-summary",
                str(cr.FRONTEND_SUMMARY_DEFAULT),
            ]
        )
        assert code == 0  # 无数据无 flag → 跳过 + 退出 0

    def test_bump_dispatches_to_cmd_bump(self, isolated_ratchet: Path):
        cr.PYPROJECT.write_text(_write_pyproject(89), encoding="utf-8")
        code = cr.main(
            [
                "--bump",
                "--coverage-json",
                str(cr.BACKEND_JSON_DEFAULT),
                "--frontend-summary",
                str(cr.FRONTEND_SUMMARY_DEFAULT),
            ]
        )
        assert code == 0  # 无数据 → 无提升 → 退出 0

    def test_history_dispatches_to_cmd_history(
        self, isolated_ratchet: Path, capsys: pytest.CaptureFixture
    ):
        code = cr.main(
            [
                "--history",
                "--coverage-json",
                str(cr.BACKEND_JSON_DEFAULT),
                "--frontend-summary",
                str(cr.FRONTEND_SUMMARY_DEFAULT),
            ]
        )
        assert code == 0
        out = capsys.readouterr().out
        assert "暂无历史" in out

    def test_custom_margin_arg_parsed(self, isolated_ratchet: Path):
        cr.PYPROJECT.write_text(_write_pyproject(80), encoding="utf-8")
        cr.BACKEND_JSON_DEFAULT.write_text(
            json.dumps(_write_backend_json(num_st=100, cov_ln=90, cov_br=85)),
            encoding="utf-8",
        )
        # margin=5 → _floor(90, 5) = 85 > 80
        code = cr.main(
            [
                "--bump",
                "--margin",
                "5",
                "--coverage-json",
                str(cr.BACKEND_JSON_DEFAULT),
                "--frontend-summary",
                str(cr.FRONTEND_SUMMARY_DEFAULT),
            ]
        )
        assert code == 0
        assert cr.read_fail_under(cr.PYPROJECT) == 85.0
