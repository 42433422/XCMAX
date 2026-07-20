"""Smoke 测试：验证 cvm_autonomy_watcher.py 在「直接脚本调用」方式下能正常启动。

回归 bug：[FHD/scripts/autonomy/cvm_autonomy_watcher.py] 顶部用了相对导入
``from .cvm_adapter import ...``，而 GitHub Actions 在 CVM 上以
``python3 /opt/fhd-full/scripts/autonomy/cvm_autonomy_watcher.py`` 直接调用，
此时 ``__package__`` 为 None，相对导入在 main() 之前立即抛
``ImportError: attempted relative import with no known parent package``，
导致 cron 每 10 分钟必失败且无任何 follow-up（闭环断链）。

现有的 test_cvm_watcher.py 通过 ``tests/test_autonomy/conftest.py`` 注入 sys.path 后
用绝对导入 ``from scripts.autonomy.*`` 加载被测模块，绕开了生产调用路径，
所以全绿但生产挂——本测试用真实 subprocess 调用脚本以覆盖该路径。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# FHD 根目录（cvm_autonomy_watcher.py 的 parents[2]）
FHD_ROOT = Path(__file__).resolve().parents[2]
WATCHER_SCRIPT = FHD_ROOT / "scripts" / "autonomy" / "cvm_autonomy_watcher.py"


def test_watcher_script_invocable_directly_without_import_error() -> None:
    """直接 ``python3 <abs_path> --help`` 应返回 0 且 stderr 无 ImportError。

    --help 在任何相对导入都加载完之后才被 argparse 处理，所以这条用例能完整覆盖
    「模块加载阶段」的导入路径——只要相对导入失败，--help 也会跟着失败。
    """
    result = subprocess.run(
        [sys.executable, str(WATCHER_SCRIPT), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        # 关键：不继承当前 PYTHONPATH/sys.path，模拟 CVM 上的纯净环境
        env={
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": "/tmp",
        },
    )
    assert result.returncode == 0, (
        f"watcher --help exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "ImportError" not in result.stderr, (
        f"relative import bug 回归：stderr 含 ImportError\n{result.stderr}"
    )
    # argparse 默认会把 usage 写到 stdout
    assert "--deploy-root" in result.stdout or "usage" in result.stdout.lower()


def test_watcher_module_invocable_via_dash_m() -> None:
    """``python3 -m scripts.autonomy.cvm_autonomy_watcher --help`` 也能工作（双保险）。

    这条用例覆盖了「如果未来 workflow 改用 -m 启动」的回归路径。
    """
    result = subprocess.run(
        [sys.executable, "-m", "scripts.autonomy.cvm_autonomy_watcher", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(FHD_ROOT),
        env={
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": "/tmp",
            "PYTHONPATH": str(FHD_ROOT),
        },
    )
    assert result.returncode == 0, (
        f"watcher -m --help exited {result.returncode}\nstderr:\n{result.stderr}"
    )
    assert "ImportError" not in result.stderr
