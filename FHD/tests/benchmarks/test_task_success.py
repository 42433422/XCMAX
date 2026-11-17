"""任务级基准评测（τ-bench 方法论：工具序列断言 + DB 终态断言 + pass^k）。

运行方式（与 intent benchmark 同款 env 门禁，避免拖慢常规套件）：

    TASK_BENCHMARK_RUN=1 python -m pytest tests/benchmarks/test_task_success.py -v

可选 env：
    TASK_BENCHMARK_TRIALS=3        # pass^k 的 k（默认 1）
    TASK_BENCHMARK_MIN_PASS=0.5    # 硬门禁阈值（默认 0.2 = 棘轮下限，只拦回退；显式设 0 退回只报告）

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
from collections import defaultdict
from pathlib import Path

import pytest

BENCH_DIR = Path(__file__).resolve().parent
RUNNER_PATH = BENCH_DIR / "task_success_runner.py"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = PROJECT_ROOT / "test_reports"

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
    out = REPORT_DIR / f"task_benchmark_trial_{trial}.jsonl"
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
    trials = max(1, int(os.environ.get("TASK_BENCHMARK_TRIALS", "1") or "1"))

    per_trial: list[list[dict]] = [_run_trial(spec["path"], i) for i in range(trials)]
    by_task: dict[str, list[dict]] = defaultdict(list)
    for trial_results in per_trial:
        assert len(trial_results) == len(tasks), "runner 结果数与评测集不一致"
        for row in trial_results:
            by_task[row["task_id"]].append(row)

    domain_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "pass_k": 0})
    pass_k_count = 0
    pass_at_k_count = 0
    failures: list[dict] = []
    for task in tasks:
        tid = task["task_id"]
        rows = by_task[tid]
        all_pass = all(r["pass"] for r in rows)
        any_pass = any(r["pass"] for r in rows)
        pass_k_count += all_pass
        pass_at_k_count += any_pass
        domain = task.get("domain") or "unknown"
        domain_stats[domain]["total"] += 1
        domain_stats[domain]["pass_k"] += all_pass
        if not all_pass:
            first_fail = next(r for r in rows if not r["pass"])
            failures.append(
                {
                    "task_id": tid,
                    "instruction": task["instruction"],
                    "difficulty": task.get("difficulty"),
                    "failure": first_fail.get("failure"),
                    "plan": first_fail.get("plan"),
                    "trials_failed": sum(1 for r in rows if not r["pass"]),
                }
            )

    total = len(tasks)
    report = {
        "set": spec["name"],
        "golden_set": spec["path"].name,
        "total_tasks": total,
        "model_responses": sum(
            int(r.get("model_responses", 0)) for rows in per_trial for r in rows
        ),
        "trials": trials,
        "pass_1": round(sum(1 for r in per_trial[0] if r["pass"]) / total, 4),
        "pass_k": round(pass_k_count / total, 4),
        "pass_at_k": round(pass_at_k_count / total, 4),
        "by_domain": {
            d: {"pass_k": s["pass_k"], "total": s["total"]} for d, s in sorted(domain_stats.items())
        },
        "failures": failures,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / spec["report"]
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n===== 任务级基准（τ-bench 口径）=====")
    print(
        f"set={spec['name']} tasks={total} trials={trials} pass^1={report['pass_1']} pass^{trials}={report['pass_k']} pass@{trials}={report['pass_at_k']}"
    )
    for d, s in report["by_domain"].items():
        print(f"  {d:12s} {s['pass_k']}/{s['total']}")
    print(f"报告: {report_path}")

    # N03（2026-09-08）：默认即硬门禁（棘轮只升不降）；
    # 显式设 TASK_BENCHMARK_MIN_PASS=0 退回只报告模式。此前默认 0 导致全失败也放行。
    # Task 6（2026-09-09）上调 0.2 → 0.4：规则层修复后实测 pass^1=0.4545（10/22），
    # 按 spec「实测下调约 5% 取整」定标。
    # 留出集默认只报告（阈值 0），建立真实模型基线后再单独上棘轮。
    floor = float(os.environ.get(spec["floor_env"], str(spec["default_floor"])) or "0")
    assert report["pass_k"] >= floor, (
        f"任务级基准低于门禁：pass^{trials}={report['pass_k']} < {floor}；"
        f"失败 {len(failures)} 项，详见 {report_path}"
    )
