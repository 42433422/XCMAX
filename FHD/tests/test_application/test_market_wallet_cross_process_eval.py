from __future__ import annotations

import sys

import pytest

from evals.run_market_wallet_cross_process_eval import run_cross_process_eval

# 该 eval 通过 subprocess.Popen 启动 uvicorn 子进程做跨进程钱包扣费/退款验证。
# 在 --cov 下 coverage.py 会通过 sitecustomize 向子进程注入 trace 钩子，
# 子进程继承 COVERAGE_PROCESS_START 后与父进程的 coverage 实例竞争同一 .coverage 文件，
# 导致子进程启动时死锁（卡在 45% 进度）。
# 该 eval 本身是集成性质（非单元测试），覆盖率收益极低，--cov 下跳过即可。
pytestmark = pytest.mark.skipif(
    sys.gettrace() is not None,
    reason="跨进程 eval 在 coverage 追踪下子进程死锁，--cov 时跳过（不带 --cov 时正常通过）",
)


def test_market_wallet_cross_process_debit_and_refund() -> None:
    result = run_cross_process_eval()

    assert result["passed"] is True, result
