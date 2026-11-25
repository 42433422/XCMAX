"""任务级基准评测（τ-bench 方法论：工具序列断言 + DB 终态断言 + pass^k）。

运行方式（与 intent benchmark 同款 env 门禁，避免拖慢常规套件）：

    TASK_BENCHMARK_RUN=1 python -m pytest tests/benchmarks/test_task_success.py -v

可选 env：
    TASK_BENCHMARK_TRIALS=3        # pass^k 的 k（默认 1；正式验收另要求至少 3 轮）
    TASK_BENCHMARK_MIN_PASS=0.4    # golden 默认门槛；安全任务不得失败
    TASK_BENCHMARK_MODE=observe   # 明确只观察；holdout 默认观察、阈值 0

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
RUNNER_PATH = BENCH_DIR / "task_success_runner.py"
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 评测集口径：golden 为回归集，holdout 为与回归集零重叠的留出集。
# 两套集共享 τ-bench 断言与 pass^k 算法，只切换数据集、报告名与门禁阈值。
_BENCHMARK_SETS = {
    "golden": {
        "path": BENCH_DIR / "task_golden_set.json",
        "report": "task_benchmark_report.json",
        "floor_env": "TASK_BENCHMARK_MIN_PASS",
        "default_floor": 0.4,
    },
    "holdout": {
        "path": BENCH_DIR / "task_holdout_set.json",
        "report": "task_holdout_report.json",
        "floor_env": "TASK_BENCHMARK_HOLDOUT_MIN_PASS",
        "default_floor": 0.0,
    },
}


def _benchmark_set() -> dict:
    name = str(os.environ.get("TASK_BENCHMARK_SET") or "golden").strip().lower()
    if name not in _BENCHMARK_SETS:
        raise ValueError(f"未知 TASK_BENCHMARK_SET={name}，仅支持 {sorted(_BENCHMARK_SETS)}")
    return {"name": name, **_BENCHMARK_SETS[name]}


pytestmark = pytest.mark.skipif(
    not os.environ.get("TASK_BENCHMARK_RUN", "").strip(),
    reason="任务级基准需要完整工具栈/DB；本地设 TASK_BENCHMARK_RUN=1 再跑",
)


def _run_trial(tasks_path: Path, trial: int) -> list[dict]:
    out = report_directory() / f"task_benchmark_trial_{trial}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    cmd = [
        sys.executable,
        str(RUNNER_PATH),
        "--tasks",
        str(tasks_path),
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


def test_task_set_pass_k():
    spec = _benchmark_set()
    data = json.loads(spec["path"].read_text(encoding="utf-8"))
    tasks = data["tasks"]
    mode, minimum = gate_policy(
        minimum_env=spec["floor_env"],
        default_minimum=spec["default_floor"],
        default_mode="observe" if spec["name"] == "holdout" else "gate",
    )
    trials = int(os.environ.get("TASK_BENCHMARK_TRIALS", "1") or "1")
    if trials < 1:
        raise ValueError("TASK_BENCHMARK_TRIALS must be positive")
    (report_directory() / spec["report"]).unlink(missing_ok=True)
    identity = evidence_identity(spec["path"], execution_mode="pending")
    per_trial = [_run_trial(spec["path"], i) for i in range(trials)]
    measured = summarize_trials(tasks, per_trial)
    responses = [row.get("model_responses", 0) for rows in per_trial for row in rows]
    if any(type(count) is not int or count < 0 for count in responses):
        raise ValueError("model_responses must be nonnegative integers")
    execution_mode = "model_workflow" if sum(responses) else "rule_only"
    # A benchmark that catches an infrastructure exception before execution
    # must not report a green pytest result just because observe has floor 0.
    startup_blocked_tasks = sorted(
        {
            row["task_id"]
            for rows in per_trial
            for row in rows
            if row.get("exec_pass") is None
        }
    )
    completed_identity = evidence_identity(spec["path"], execution_mode=execution_mode)
    identity["tracked_source_dirty"] = (
        identity["tracked_source_dirty"]
        or completed_identity["tracked_source_dirty"]
        or any(identity[key] != completed_identity[key] for key in ("source_sha", "dataset_sha256"))
    )
    report = {
        **identity,
        **measured,
        "set": spec["name"],
        "golden_set": spec["path"].name,
        "execution_mode": execution_mode,
        "model_responses": sum(responses),
        "startup_blocked_tasks": startup_blocked_tasks,
        "acceptance_mode": mode,
        "min_required": minimum,
        "gate_passed": mode == "gate" and passes_gate(measured, minimum),
        "trial_artifacts": [
            trial_artifact(report_directory() / f"task_benchmark_trial_{i}.jsonl")
            for i in range(trials)
        ],
    }
    report_path = write_report(spec["report"], report)

    print("\n===== 任务级基准（τ-bench 口径）=====")
    print(
        f"set={spec['name']} tasks={len(tasks)} trials={trials} mode={mode} "
        f"pass^1={report['pass_1']} pass^{trials}={report['pass_k']} pass@{trials}={report['pass_at_k']}"
    )
    for d, s in report["by_domain"].items():
        print(f"  {d:12s} {s['pass_k']}/{s['total']}")
    print(f"报告: {report_path}")

    if startup_blocked_tasks:
        pytest.fail(
            f"任务基准未真正开始执行的任务：{startup_blocked_tasks}；"
            f"原始试验报告见 {report_path}",
            pytrace=False,
        )

    if mode == "gate":
        assert report["gate_passed"], (
            f"任务级基准未通过门禁：pass^{trials}={report['pass_k']}，门槛={minimum}；"
            f"安全失败={report['safety_failures']}，详见 {report_path}"
        )
