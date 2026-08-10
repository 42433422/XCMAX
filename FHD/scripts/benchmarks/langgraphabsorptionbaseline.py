#!/usr/bin/env python3
"""LG-W0-09 — LangGraph 吸收基线基准（legacy WorkflowEngine vs vendored LangGraph）。

在可比较的确定性场景下测量两条执行路径：
  1. legacy WorkflowEngine（``app/application/workflow/engine.py``，FHD 当前产品实现）
  2. 仓库 vendored 锁定 LangGraph（``packages/xcagi_langgraph_core``，pinned 1.2.10）

场景（两引擎一致）：
  - compile_100 / compile_1000 ：图构造 + 校验/编译
  - execute_100 / execute_1000 ：顺序执行 100 / 1000 节点
  - fanout_64                  ：64 个独立并行节点
  - checkpoint_200             ：200 节点 + 逐步 checkpoint

方法学：
  - 固定 seed（确定性构造）、warmup=5、measured repeats（默认 7）
  - 每个场景输出 min / median / p95 / max（ms）
  - 输出为稳定 JSON：sort_keys、无绝对路径、无易变时间戳

LangGraph 加载约束（满足 LG-W0-09）：
  - LangGraph 通过 ``uv run --project packages/xcagi_langgraph_core`` 在 vendored 包的
    锁定 uv 环境（uv.lock + [tool.uv.sources] → 兄弟 vendored 包）内以子进程方式导入，
    **不做** PYTHONPATH / sys.path 注入，**不**使用根 site-packages，**不**使用 /tmp 源码。
    即便 core 包 .venv 被外部流程清理，uv run 也会按锁定来源按需重建（wait/retry，不改兄弟包）。
    legacy 引擎为项目自身代码，允许在进程内 import ``app``。

legacy 契约假设：读取 W0-06 fixture（``tests/langgraph_absorption/fixtures/legacy_contract.json``）
作为 legacy 引擎行为冻结门禁（smoke gate）。

用法：
  .venv/bin/python scripts/benchmarks/langgraphabsorptionbaseline.py            # 打印稳定 JSON
  .venv/bin/python scripts/benchmarks/langgraphabsorptionbaseline.py --write-doc  # 额外写 09-baseline.md

退出码：任一回归门禁（p95 上限）超限时非零。
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

# 常量
SEED = 20260810
WARMUP = 5
REPEATS = 7
SPEC = "LG-W0-09"

# 仓库相对路径（输出中只使用相对路径，绝不落绝对路径）
_REPO_ROOT = Path(__file__).resolve().parents[2]  # FHD/scripts/benchmarks -> FHD
_LEGACY_TARGET = "app/application/workflow/engine.py"
_LANGGRAPH_TARGET = "packages/xcagi_langgraph_core (vendored, pinned 1.2.10)"
_CORE_PROJECT = "packages/xcagi_langgraph_core"
_FIXTURE = _REPO_ROOT / "tests" / "langgraph_absorption" / "fixtures" / "legacy_contract.json"
_DOC_PATH = _REPO_ROOT / "docs" / "architecture" / "langgraph-absorption" / "09-baseline.md"

# 回归门禁（p95 上限，ms）—— 阈值取实测值留足余量，仅供 CI 兜底防回归
LEGACY_GATES = {
    "compile_100": 500,
    "execute_100": 1000,
    "compile_1000": 1000,
    "execute_1000": 3000,
    "fanout_64": 500,
    "checkpoint_200": 3000,
}
LANGGRAPH_GATES = {
    "compile_100": 500,
    "execute_100": 2000,
    "compile_1000": 3000,
    "execute_1000": 5000,
    "fanout_64": 3000,
    "checkpoint_200": 5000,
}

SCENARIOS = ("compile_100", "execute_100", "compile_1000", "execute_1000", "fanout_64", "checkpoint_200")


# ---------------------------------------------------------------------------
# 统计辅助
# ---------------------------------------------------------------------------
def _stats(times: list[float]) -> dict[str, float]:
    s = sorted(times)
    n = len(s)
    p95 = s[min(n - 1, int(0.95 * (n - 1)))]
    return {
        "min": round(s[0], 3),
        "median": round(statistics.median(s), 3),
        "p95": round(p95, 3),
        "max": round(s[-1], 3),
    }


def _measure(fn, warmup: int, repeats: int) -> dict[str, float]:
    for _ in range(warmup):
        fn()
    times: list[float] = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000)
    return _stats(times)


# ---------------------------------------------------------------------------
# legacy WorkflowEngine 基准（进程内，FHD venv，import app —— 项目自身代码）
# ---------------------------------------------------------------------------
def _load_legacy_contract_assumptions() -> dict:
    """读取 W0-06 fixture，返回 legacy 引擎行为冻结假设（仅相对路径）。"""
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return {
        "fixture": "tests/langgraph_absorption/fixtures/legacy_contract.json",
        "expected_executed_nodes": data["canonical_run"]["executed_nodes"],
        "expected_success": data["canonical_run"]["success"],
    }


def _legacy_seq_plan(n: int, plan_id: str = "bl"):
    from app.application.workflow.types import PlanGraph, WorkflowNode

    nodes = [
        WorkflowNode(
            node_id=f"n{i}",
            tool_id="t",
            action="a",
            params={"k": i},
            risk="low",
            idempotent=True,
            depends_on=[] if i == 1 else [f"n{i - 1}"],
        )
        for i in range(1, n + 1)
    ]
    return PlanGraph(plan_id=plan_id, intent="baseline", nodes=nodes)


def _legacy_fanout_plan(degree: int) -> object:
    from app.application.workflow.types import PlanGraph, WorkflowNode

    nodes = [
        WorkflowNode(node_id=f"f{i}", tool_id="t", action="a", risk="low", idempotent=True)
        for i in range(degree)
    ]
    return PlanGraph(plan_id="fanout", intent="baseline", nodes=nodes)


def _legacy_dispatch(*, tool_id, action, params):  # noqa: ANN001,ANN202
    return {"success": True, "tool_id": tool_id, "action": action}


def benchmark_legacy() -> dict:
    from app.application.workflow.checkpointer import WorkflowCheckpointer
    from app.application.workflow.engine import WorkflowEngine
    from app.application.workflow.types import validate_plan_graph

    engine = WorkflowEngine(_legacy_dispatch)
    results: dict[str, dict] = {}

    # compile：构造 + 校验
    plan100 = _legacy_seq_plan(100, "bl100")
    plan1000 = _legacy_seq_plan(1000, "bl1000")

    def c100():
        validate_plan_graph(plan100)

    def c1000():
        validate_plan_graph(plan1000)

    results["compile_100"] = _measure(c100, WARMUP, REPEATS)
    results["compile_1000"] = _measure(c1000, WARMUP, REPEATS)

    # execute：复用已校验 plan，仅测 run
    def e100():
        engine.run(plan100)

    def e1000():
        engine.run(plan1000)

    results["execute_100"] = _measure(e100, WARMUP, REPEATS)
    results["execute_1000"] = _measure(e1000, WARMUP, REPEATS)

    # fanout_64
    fan = _legacy_fanout_plan(64)

    def ef():
        engine.run(fan, runtime_context={"max_parallel_workers": 8})

    results["fanout_64"] = _measure(ef, WARMUP, REPEATS)

    # checkpoint_200：200 节点 + 每步 checkpoint
    ck_plan = _legacy_seq_plan(200, "blck")

    def ec():
        engine.run(ck_plan, checkpointer=WorkflowCheckpointer())

    results["checkpoint_200"] = _measure(ec, WARMUP, REPEATS)
    return results


def legacy_contract_gate() -> dict:
    """用 W0-06 fixture 作为 legacy 契约 smoke gate。"""
    from app.application.workflow.engine import WorkflowEngine
    from app.application.workflow.types import PlanGraph, WorkflowNode

    assumptions = _load_legacy_contract_assumptions()
    plan = PlanGraph(
        plan_id="p_ct",
        intent="contract",
        nodes=[
            WorkflowNode(node_id="n1", tool_id="t1", action="a1", params={"k": 1}, risk="low", idempotent=True),
            WorkflowNode(node_id="n2", tool_id="t2", action="a2", params={"k": 2}, risk="low", idempotent=True, depends_on=["n1"]),
            WorkflowNode(node_id="n3", tool_id="t3", action="a3", params={"k": 3}, risk="low", idempotent=True, depends_on=["n2"]),
        ],
    )
    result = WorkflowEngine(_legacy_dispatch).run(plan)
    executed = sorted(result.final_context["workflow_status"]["executed_nodes"])
    match = result.success is True and executed == assumptions["expected_executed_nodes"]
    return {
        "fixture": assumptions["fixture"],
        "expected_executed_nodes": assumptions["expected_executed_nodes"],
        "actual_executed_nodes": executed,
        "success": bool(result.success),
        "match": bool(match),
    }


# ---------------------------------------------------------------------------
# vendored LangGraph 基准 —— 子进程运行于 vendored 包自身锁定 uv 环境
# ---------------------------------------------------------------------------
_LANGGRAPH_WORKER = r"""
import json, statistics, time, random, operator
__SEED__ = __SEED_REPLACE__
WARMUP = __WARMUP_REPLACE__
REPEATS = __REPEATS_REPLACE__
random.seed(__SEED__)
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver

class S(TypedDict):
    i: int

# fan-out 并行节点同写一个 key，需 reducer（operator.add）以满足 LangGraph 单步多写契约
class FS(TypedDict):
    i: Annotated[int, operator.add]

def _inc(state):
    return {"i": state["i"] + 1}

def _inc_f(state):
    return {"i": 1}

def _stats(ts):
    s = sorted(ts); n = len(s)
    p95 = s[min(n - 1, int(0.95 * (n - 1)))]
    return {"min": round(s[0], 3), "median": round(statistics.median(s), 3), "p95": round(p95, 3), "max": round(s[-1], 3)}

def _seq_app(n, checkpointer=None):
    g = StateGraph(S)
    g.add_node("n0", _inc)
    for k in range(1, n):
        g.add_node("n%d" % k, _inc)
        g.add_edge("n%d" % (k - 1), "n%d" % k)
    g.add_edge(START, "n0"); g.add_edge("n%d" % (n - 1), END)
    return g.compile(checkpointer=checkpointer)

def _fanout_app(degree):
    g = StateGraph(S)
    for k in range(degree):
        g.add_node("f%d" % k, _inc)
        g.add_edge(START, "f%d" % k); g.add_edge("f%d" % k, END)
    return g.compile()

def _measure(fn, warmup, repeats):
    for _ in range(warmup):
        fn()
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter(); fn(); t1 = time.perf_counter()
        times.append((t1 - t0) * 1000)
    return _stats(times)

results = {}

def c100(): return _seq_app(100)
def c1000(): return _seq_app(1000)
results["compile_100"] = _measure(c100, WARMUP, REPEATS)
results["compile_1000"] = _measure(c1000, WARMUP, REPEATS)

app100 = _seq_app(100); app1000 = _seq_app(1000)
def e100(): return app100.invoke({"i": 0})
def e1000(): return app1000.invoke({"i": 0})
results["execute_100"] = _measure(e100, WARMUP, REPEATS)
results["execute_1000"] = _measure(e1000, WARMUP, REPEATS)

fan = _fanout_app(64)
def ef(): return fan.invoke({"i": 0})
results["fanout_64"] = _measure(ef, WARMUP, REPEATS)

mem = InMemorySaver()
ck_app = _seq_app(200, checkpointer=mem)
cnt = {"n": 0}
def ec():
    cnt["n"] += 1
    return ck_app.invoke({"i": 0}, config={"configurable": {"thread_id": "thr-%d" % cnt["n"]}})
results["checkpoint_200"] = _measure(ec, WARMUP, REPEATS)

print(json.dumps(results, sort_keys=True, separators=(",", ":")))
"""


def benchmark_langgraph() -> dict:
    """通过 uv run 在 vendored core 包锁定 uv 环境内跑 LangGraph 基准（package-local locked sources）。"""
    uv_bin = shutil.which("uv")
    if uv_bin is None:
        raise RuntimeError("未找到 uv：需用 `uv run --project packages/xcagi_langgraph_core` 从 vendored 包锁定环境导入 langgraph")
    code = (
        _LANGGRAPH_WORKER.replace("__SEED_REPLACE__", repr(SEED))
        .replace("__WARMUP_REPLACE__", repr(WARMUP))
        .replace("__REPEATS_REPLACE__", repr(REPEATS))
    )
    proc = subprocess.run(
        [uv_bin, "run", "--project", _CORE_PROJECT, "--", "python", "-c", code],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    if proc.returncode != 0:
        raise RuntimeError("vendored langgraph worker 失败: " + (proc.stderr or proc.stdout or "")[-2000:])
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------------------
# 回归门禁
# ---------------------------------------------------------------------------
def _evaluate_gates(gates: dict, results: dict) -> dict:
    gate_out: dict = {}
    for scenario in SCENARIOS:
        p95 = results[scenario]["p95"]
        limit = gates[scenario]
        gate_out[scenario + "_p95_ms"] = {
            "limit": limit,
            "measured": p95,
            "pass": p95 <= limit,
        }
    return gate_out


# ---------------------------------------------------------------------------
# 环境元数据（不含绝对路径 / 无时间戳）
# ---------------------------------------------------------------------------
def _environment() -> dict:
    return {
        "python": sys.version.split()[0],
        "python_impl": platform.python_implementation(),
        "os": platform.system(),
        "os_release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor() or platform.machine(),
    }


# ---------------------------------------------------------------------------
# 汇总 JSON
# ---------------------------------------------------------------------------
def _assemble(legacy: dict, langgraph: dict, contract: dict, legacy_gates: dict, lg_gates: dict) -> dict:
    gates = {
        "legacy_workflow_engine": legacy_gates,
        "vendor_langgraph": lg_gates,
    }
    all_pass = all(v["pass"] for g in gates.values() for v in g.values()) and contract["match"]
    return {
        "spec": SPEC,
        "title": "langgraph absorption baseline",
        "engines": ["legacy_workflow_engine", "vendor_langgraph"],
        "seed": SEED,
        "warmup": WARMUP,
        "repeats": REPEATS,
        "scenarios": list(SCENARIOS),
        "source": {
            "legacy_workflow_engine": _LEGACY_TARGET,
            "vendor_langgraph": _LANGGRAPH_TARGET,
        },
        "environment": _environment(),
        "legacy_contract": contract,
        "results": {
            "legacy_workflow_engine": legacy,
            "vendor_langgraph": langgraph,
        },
        "gates": gates,
        "all_gates_pass": bool(all_pass),
    }


# ---------------------------------------------------------------------------
# Markdown 生成（结果来自本次运行）
# ---------------------------------------------------------------------------
def _markdown(doc: dict) -> str:
    env = doc["environment"]
    lg_source = doc["source"]["vendor_langgraph"]
    leg = doc["results"]["legacy_workflow_engine"]
    lgr = doc["results"]["vendor_langgraph"]
    lines: list[str] = []
    lines.append("# LG-W0-09 — LangGraph 吸收基线基准")
    lines.append("")
    lines.append("> spec: `LG-W0-09` · 结果与回归门禁均来自**本次基准运行**（可复现）。")
    lines.append("")
    lines.append("## 测量对象")
    lines.append("")
    lines.append(f"- **legacy WorkflowEngine**：`{doc['source']['legacy_workflow_engine']}`（FHD 当前产品实现）")
    lines.append(f"- **vendored LangGraph**：`{lg_source}`（仓库 vendored、锁定版本）")
    lines.append("")
    lines.append("## 场景与方法学")
    lines.append("")
    lines.append("| 场景 | 含义 |")
    lines.append("|------|------|")
    lines.append("| `compile_100` / `compile_1000` | 图构造 + 校验/编译（100 / 1000 节点） |")
    lines.append("| `execute_100` / `execute_1000` | 顺序执行 100 / 1000 节点 |")
    lines.append("| `fanout_64` | 64 个独立并行节点（fan-out） |")
    lines.append("| `checkpoint_200` | 200 节点 + 逐步 checkpoint |")
    lines.append("")
    lines.append(f"- seed=`{doc['seed']}`（确定性构造）· warmup=`{doc['warmup']}` · measured repeats=`{doc['repeats']}`")
    lines.append("- 每个场景输出 `min` / `median` / `p95` / `max`（单位 ms）")
    lines.append("")
    lines.append("## 机器条件（本次运行）")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("|----|----|")
    lines.append(f"| Python | {env['python']} ({env['python_impl']}) |")
    lines.append(f"| OS | {env['os']} {env['os_release']} |")
    lines.append(f"| Machine | {env['machine']} |")
    lines.append(f"| Processor | {env['processor']} |")
    lines.append("")
    lines.append("## 实测结果（本次运行，ms）")
    lines.append("")
    lines.append("| 引擎 | 场景 | min | median | p95 | max |")
    lines.append("|------|------|-----|--------|-----|-----|")
    for scenario in SCENARIOS:
        l = leg[scenario]
        lines.append(
            f"| legacy_workflow_engine | `{scenario}` | {l['min']} | {l['median']} | {l['p95']} | {l['max']} |"
        )
    for scenario in SCENARIOS:
        r = lgr[scenario]
        lines.append(
            f"| vendor_langgraph | `{scenario}` | {r['min']} | {r['median']} | {r['p95']} | {r['max']} |"
        )
    lines.append("")
    lines.append("## 回归门禁（本次实测，p95 上限）")
    lines.append("")
    lines.append("| 引擎 | 门禁 | 上限(ms) | 实测(ms) | 通过 |")
    lines.append("|------|------|----------|----------|------|")
    for engine, gates in doc["gates"].items():
        for name, g in gates.items():
            lines.append(f"| {engine} | {name} | {g['limit']} | {g['measured']} | {'✅' if g['pass'] else '❌'} |")
    lines.append("")
    c = doc["legacy_contract"]
    lines.append(f"## legacy 契约门禁（W0-06 fixture）")
    lines.append("")
    lines.append(f"- fixture：`{c['fixture']}`")
    lines.append(f"- 期望 executed_nodes：`{c['expected_executed_nodes']}` · 实测：`{c['actual_executed_nodes']}` · success=`{c['success']}`")
    lines.append(f"- **契约匹配：{'✅' if c['match'] else '❌'}**")
    lines.append("")
    lines.append(f"## 总体门禁：**{'PASS' if doc['all_gates_pass'] else 'FAIL'}**")
    lines.append("")
    lines.append("## 精确重跑命令")
    lines.append("")
    lines.append("```bash")
    lines.append("cd FHD")
    lines.append("XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 .venv/bin/python scripts/benchmarks/langgraphabsorptionbaseline.py")
    lines.append("XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 .venv/bin/python scripts/benchmarks/langgraphabsorptionbaseline.py --write-doc")
    lines.append("```")
    lines.append("")
    lines.append("## LangGraph 来源合规说明")
    lines.append("")
    lines.append("- LangGraph 由 vendored 包自身锁定 uv 环境（`uv run --project packages/xcagi_langgraph_core`，uv.lock + [tool.uv.sources] → 兄弟 vendored 包）子进程导入。")
    lines.append("- 不使用根 site-packages、不使用 /tmp 源码、不做 PYTHONPATH / sys.path 注入；core 包 .venv 被外部清理时按锁定来源按需重建，不改兄弟包。")
    lines.append("- 输出 JSON 不含绝对路径、不含易变时间戳。")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LG-W0-09 LangGraph 吸收基线基准")
    parser.add_argument("--write-doc", action="store_true", help="额外写入 09-baseline.md（含本次实测结果）")
    args = parser.parse_args(argv)

    # 保证 app 可导入（项目自身代码，仅 legacy 引擎用；不涉及 langgraph 加载）
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))

    contract = legacy_contract_gate()
    legacy = benchmark_legacy()
    langgraph = benchmark_langgraph()

    legacy_gates = _evaluate_gates(LEGACY_GATES, legacy)
    lg_gates = _evaluate_gates(LANGGRAPH_GATES, langgraph)
    doc = _assemble(legacy, langgraph, contract, legacy_gates, lg_gates)

    out = json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2)
    print(out)

    if args.write_doc:
        _DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
        _DOC_PATH.write_text(_markdown(doc), encoding="utf-8")
        print(f"[LG-W0-09] wrote {_DOC_PATH.relative_to(_REPO_ROOT)}", file=sys.stderr)

    return 0 if doc["all_gates_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
