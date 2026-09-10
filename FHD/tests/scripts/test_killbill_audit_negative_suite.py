"""#1858 负向回归：Kill Bill 审计脚本必须以进程退出码反映业务断言。

脚本自身带 "negative-suite" 自测入口，但此前没有任何测试/CI 调用它，
"SUMMARY 后显式退出判定" 无法被门禁守住。本测试把该入口接入 CI：
分别强制 B1/B2/B3 失败必须非零退出，全 PASS 才返回 0，且失败时仍保留结果报告。
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "evidence"
    / "audit-benchmark"
    / "java-payment-killbill-tasks-20260910.sh"
)


def _run(selftest: str) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    assert bash, "需要 bash 运行审计脚本"
    env = {**os.environ, "KB_SELFTEST": selftest}
    return subprocess.run(
        [bash, str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_negative_suite_passes() -> None:
    result = _run("negative-suite")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NEGATIVE-SUITE PASS" in result.stdout


def test_forced_failures_exit_nonzero_with_report() -> None:
    expected = {"force-b1": "B1", "force-b2": "B2", "force-b3": "B3"}
    for selftest, bit in expected.items():
        result = _run(selftest)
        assert result.returncode != 0, f"{selftest} 必须非零退出，实际 0：{result.stdout}"
        assert "SUMMARY" in result.stdout, f"{selftest} 失败时必须保留结果报告"
        assert f"{bit}=FAIL" in result.stdout, f"{selftest} 应把 {bit} 标为 FAIL"


def test_all_pass_exits_zero() -> None:
    result = _run("all-pass")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SUMMARY B1=PASS B2=PASS B3=PASS" in result.stdout


def test_unknown_mode_is_environment_block() -> None:
    result = _run("bogus-mode")
    assert result.returncode == 2, result.stdout + result.stderr
