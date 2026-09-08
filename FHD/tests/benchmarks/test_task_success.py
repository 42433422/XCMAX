"""任务级基准评测（τ-bench 方法论：工具序列断言 + DB 终态断言 + pass^k）。

运行方式（与 intent benchmark 同款 env 门禁，避免拖慢常规套件）：

    TASK_BENCHMARK_RUN=1 python -m pytest tests/benchmarks/test_task_success.py -v

可选 env：
    TASK_BENCHMARK_TRIALS=3        # pass^k 的 k（默认 3）
    TASK_BENCHMARK_MODE=observe   # 显式只报告；默认 gate，成功率门槛 1.0

口径（对齐 τ-bench）：
    pass^1  = 单次试验通过的任务占比
    pass^k  = k 次试验全部通过的任务占比（可靠性）
    pass@k  = k 次试验至少一次通过的任务占比（能力上限，参考值）
报告落盘：test_reports/task_benchmark_report.json
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.dev.benchmark_evidence import (
    evidence_identity,
    gate_policy,
    report_directory,
    trial_artifact,
    write_report,
)
from scripts.dev.task_benchmark_report import passes_gate, summarize_trials

BENCH_DIR = Path(__file__).resolve().parent
GOLDEN_PATH = BENCH_DIR / "task_golden_set.json"
RUNNER_PATH = BENCH_DIR / "task_success_runner.py"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = report_directory()

pytestmark = pytest.mark.skipif(
    not os.environ.get("TASK_BENCHMARK_RUN", "").strip(),
    reason="任务级基准需要完整工具栈/DB；本地设 TASK_BENCHMARK_RUN=1 再跑",
)


def _run_trial(trial: int) -> list[dict]:
    out = REPORT_DIR / f"task_benchmark_trial_{trial}.jsonl"
    cmd = [
        sys.executable,
        str(RUNNER_PATH),
        "--tasks",
        str(GOLDEN_PATH),
        "--trial",
        str(trial),
        "--out",
        str(out),
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=900,
        env={
            **os.environ,
            "PYTHONPATH": str(PROJECT_ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""),
        },
    )
    if proc.returncode != 0:
        pytest.fail(
            f"trial {trial} runner 失败（exit={proc.returncode}）:\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
        )
    return [
        json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def test_task_golden_set_pass_k():
    mode, minimum = gate_policy()
    data = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    trials = int(os.environ.get("TASK_BENCHMARK_TRIALS", "3"))
    if trials < 1 or (mode == "gate" and trials < 3):
        raise ValueError("gate mode requires at least three independent trials")
    per_trial = [_run_trial(i) for i in range(trials)]
    report = summarize_trials(data["tasks"], per_trial)
    report.update(evidence_identity(GOLDEN_PATH, execution_mode="deterministic_tools"))
    report.update(
        {
            "golden_set": GOLDEN_PATH.name,
            "acceptance_mode": mode,
            "min_required": minimum,
            "gate_passed": mode == "gate" and passes_gate(report, minimum),
            "trial_artifacts": [
                trial_artifact(REPORT_DIR / f"task_benchmark_trial_{number}.jsonl")
                for number in range(trials)
            ],
        }
    )
    report_path = write_report("task_benchmark_report.json", report)
    print(
        f"tasks={report['total_tasks']} trials={trials} pass^k={report['pass_k']:.4f}; {report_path}"
    )
    if mode == "gate":
        assert report["gate_passed"], (
            f"Task gate failed: pass^{trials}={report['pass_k']:.4f}, required={minimum}; "
            f"safety failures={report['safety_failures']}; report={report_path}"
        )
