"""LG-W1-T10-B — 冻结 `XCAGILangGraphRuntime`（LangGraph 图执行器）的独立运行时契约。

本文件以 `app/infrastructure/workflow/langgraph_runtime.py` 的 ``XCAGILangGraphRuntime``
为 SSOT，固化其确定性行为契约：

- ``WorkflowRuntime`` port 契约符合性与精确注入身份（dispatcher / publisher）。
- 具体 vendored ``StateGraph`` 模块来源（`FHD/packages/`）与 fail-closed 来源断言。
- 源码静态边界：不 import legacy ``WorkflowEngine`` / ``LegacyEngineAdapter``。
- build/compile、顺序依赖、稳定结果形态、node_outputs / trace / status / blocked /
  message / branch / next 边。
- StateSchema set/append/merge_dict reducer。
- 重试后成功 / 终止失败与 recovery 字段 / 高风险非幂等不重试。
- 低风险幂等只读节点可并行、高风险/非幂等写节点独占、parallel=False 全串行
  （用 threading Events/Barrier，不用 timing 猜测）。
- 状态 callback 与 publisher 事件形态/顺序。
- agentic_loop / tool_registry 不支持 fail-closed。
- checkpoint 运行期保存稳定形态；resume 跳过已执行节点并使用传入 checkpoint；
  replay 只读、绝不 dispatch；缺失/非法 checkpoint 路径确定性失败。
- state_schema 参数行为；调用方输入不被意外修改。

约束（本任务）
- 只改本文件与 `fixtures/langgraph_runtime_contract.json`；不改产品代码、不触碰
  legacy 契约（`test_legacy_runtime_contract.py` + `fixtures/legacy_contract.json` 只读）。
- 绝不 import / 实例化 legacy 引擎；绝不复制或重写 legacy fixture。
- fixture 字节可复现，且不含绝对路径 / 时间戳 / 耗时 / 随机 ID / 环境特定值。
- pytest 只比较已入库 fixture，绝不重写它（重写仅通过独立 regenerate 入口）。
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import re
import textwrap
import threading
from pathlib import Path

import pytest
from langgraph.graph.state import StateGraph

from app.application.workflow.ports.events import StateUpdateEvent
from app.application.workflow.ports.runtime import WorkflowRuntime
from app.application.workflow.types import (
    Branch,
    NodeExecutionResult,
    PlanGraph,
    StateSchema,
    WorkflowNode,
    WorkflowRunResult,
    apply_state_schema,
)
from app.infrastructure.workflow.langgraph_assert import (
    REQUIRED_VENDORED_MODULES,
    UPSTREAM_TAG,
    assert_vendored_sources,
)
from app.infrastructure.workflow.langgraph_runtime import XCAGILangGraphRuntime

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
_FIXTURE_PATH = _FIXTURE_DIR / "langgraph_runtime_contract.json"

# Event/Barrier wait 的 timeout 仅用于防止死锁时把测试永久挂住，绝不用于时长/并发断言。
_DEADLOCK = 10.0


# ---------------------------------------------------------------------------
# 确定性构造辅助
# ---------------------------------------------------------------------------


def _dispatch_ok(tool_id: str, action: str, params: dict) -> dict:
    """确定性成功 dispatcher：返回仅依赖入参的稳定 dict。"""
    return {"success": True, "tool_id": tool_id, "action": action, "param_k": params.get("k")}


def _sequential_plan(n: int = 3, plan_id: str = "p_rt") -> PlanGraph:
    """n 个顺序节点（n_i 依赖 n_{i-1}），tool_id/action/params 唯一且确定。"""
    nodes = [
        WorkflowNode(
            node_id=f"n{i}",
            tool_id=f"t{i}",
            action=f"a{i}",
            params={"k": i},
            risk="low",
            idempotent=True,
            depends_on=[] if i == 1 else [f"n{i - 1}"],
        )
        for i in range(1, n + 1)
    ]
    return PlanGraph(
        plan_id=plan_id,
        intent="contract",
        todo_steps=[f"s{i}" for i in range(1, n + 1)],
        nodes=nodes,
    )


def _make_runtime(dispatch=None, publisher=None) -> XCAGILangGraphRuntime:
    return XCAGILangGraphRuntime(
        tool_dispatcher=dispatch or _dispatch_ok,
        state_event_publisher=publisher,
    )


def _executed_nodes(result: WorkflowRunResult) -> list[str]:
    return sorted(result.final_context["workflow_status"]["executed_nodes"])


class _FakeStore:
    """确定性内存 CheckpointStore：checkpoint_id 固定 (cp1, cp2, …)，无随机 UUID。"""

    def __init__(self) -> None:
        self._cps: dict[tuple[str, str], dict] = {}
        self._seq = 0

    def save_checkpoint(
        self, plan_id, step_index, runtime_context, executed_nodes, *, blocked=None
    ):
        self._seq += 1
        cid = f"cp{self._seq}"
        self._cps[(plan_id, cid)] = {
            "plan_id": plan_id,
            "checkpoint_id": cid,
            "step_index": int(step_index),
            "runtime_context": dict(runtime_context),
            "executed_nodes": sorted(executed_nodes or []),
            "blocked": sorted(blocked or []),
        }
        return cid

    def get_checkpoint(self, plan_id, checkpoint_id):
        return self._cps.get((plan_id, checkpoint_id))

    def list_checkpoints(self, plan_id):
        return [c for k, c in self._cps.items() if k[0] == plan_id]

    def latest_checkpoint(self, plan_id):
        items = [c for k, c in self._cps.items() if k[0] == plan_id]
        return max(items, key=lambda c: c["step_index"]) if items else None


class _FakePublisher:
    def __init__(self) -> None:
        self.events: list[StateUpdateEvent] = []

    def publish_state_update(self, event: StateUpdateEvent) -> None:
        self.events.append(event)


# ---------------------------------------------------------------------------
# 归一化：去掉时间戳 / 耗时等易变字段，保证字节可复现
# ---------------------------------------------------------------------------

_TRACE_KEYS = ("node_id", "tool_id", "action", "success", "error", "recovery_hint")


def _normalize_node_result(r: NodeExecutionResult) -> dict:
    return {
        "node_id": r.node_id,
        "tool_id": r.tool_id,
        "action": r.action,
        "success": bool(r.success),
        "retries": int(r.retries),
        "retryable": bool(r.retryable),
        "error": str(r.error),
        "recovery_hint": str(r.recovery_hint),
        "params": dict(r.params),
        "output": dict(r.output),
    }


def _normalize_context(ctx: dict) -> dict:
    out: dict = {}
    if "node_outputs" in ctx:
        out["node_outputs"] = dict(ctx["node_outputs"])
    if "workflow_trace" in ctx:
        out["workflow_trace"] = [
            {k: tr[k] for k in _TRACE_KEYS if k in tr} for tr in ctx["workflow_trace"]
        ]
    if "workflow_status" in ctx:
        ws = dict(ctx["workflow_status"])
        if "executed_nodes" in ws:
            ws["executed_nodes"] = sorted(ws["executed_nodes"])
        out["workflow_status"] = ws
    if "message" in ctx:
        out["message"] = ctx["message"]
    return out


# ---------------------------------------------------------------------------
# 确定性 golden 计算（纯 helper，供 fixture 与冻结断言复用）
# ---------------------------------------------------------------------------


def _reducer_golden() -> dict:
    """set/append/merge_dict 三种 reducer 的直接确定性快照。"""
    schema = (
        StateSchema()
        .declare("count", type=int, merge="set")
        .declare("tags", type=list, merge="append")
        .declare("meta", type=dict, merge="merge_dict")
    )
    ctx = apply_state_schema({}, schema, writes={"count": 5})
    ctx = apply_state_schema(ctx, schema, writes={"tags": "a"})
    ctx = apply_state_schema(ctx, schema, writes={"tags": "b"})
    ctx = apply_state_schema(ctx, schema, writes={"meta": {"a": 1}})
    ctx = apply_state_schema(ctx, schema, writes={"meta": {"b": 2}})
    return {"count": ctx["count"], "tags": ctx["tags"], "meta": ctx["meta"]}


def _checkpoint_shape_golden() -> dict:
    """成功运行后最新 checkpoint 的稳定形态（不含 checkpoint_id / 时间戳）。"""
    store = _FakeStore()
    _make_runtime().run(_sequential_plan(), checkpointer=store)
    latest = store.latest_checkpoint("p_rt")
    return {
        "keys": sorted(latest.keys()),
        "plan_id": latest["plan_id"],
        "step_index": latest["step_index"],
        "executed_nodes": latest["executed_nodes"],
        "blocked": latest["blocked"],
        "runtime_context_keys": sorted(latest["runtime_context"].keys()),
    }


def _resume_golden() -> dict:
    """首跑在 t3 失败 → checkpoint 保存到 step2 → resume 使用传入 checkpoint 续跑。"""
    store = _FakeStore()
    plan = _sequential_plan(5, plan_id="p_cp")

    def fail_at3(tool_id, action, params):
        return {"success": False, "message": "boom"} if tool_id == "t3" else {"success": True}

    first = _make_runtime(fail_at3).run(plan, checkpointer=store)
    stored = sorted(c["step_index"] for c in store.list_checkpoints("p_cp"))
    checkpoint_id = store.latest_checkpoint("p_cp")["checkpoint_id"]

    resume_calls: list[str] = []

    def resume_dispatch(tool_id, action, params):
        resume_calls.append(tool_id)
        return {"success": True}

    resumed = _make_runtime(resume_dispatch).resume_run(plan, checkpoint_id, checkpointer=store)
    return {
        "first_success": bool(first.success),
        "stored_steps": stored,
        "resume_checkpoint_id": checkpoint_id,
        "resume_success": bool(resumed.success),
        "resume_executed": _executed_nodes(resumed),
        "resume_dispatched": sorted(resume_calls),
    }


def _replay_golden() -> dict:
    """构造一个已完成 checkpoint 并重放：只读、绝不 dispatch、success=True。"""
    store = _FakeStore()
    plan_id = "p_rp"
    store._cps[(plan_id, "cpX")] = {
        "plan_id": plan_id,
        "checkpoint_id": "cpX",
        "step_index": 2,
        "runtime_context": {
            "results": [
                {
                    "node_id": "n1",
                    "success": True,
                    "tool_id": "t1",
                    "action": "a1",
                    "params": {},
                    "output": {"success": True},
                    "error": "",
                    "recovery_hint": "",
                    "retries": 0,
                    "retryable": True,
                    "started_at": "",
                    "finished_at": "",
                    "duration_ms": 0,
                    "attempts": [],
                },
                {
                    "node_id": "n2",
                    "success": True,
                    "tool_id": "t2",
                    "action": "a2",
                    "params": {},
                    "output": {"success": True},
                    "error": "",
                    "recovery_hint": "",
                    "retries": 0,
                    "retryable": True,
                    "started_at": "",
                    "finished_at": "",
                    "duration_ms": 0,
                    "attempts": [],
                },
            ],
            "workflow_status": {"state": "completed", "executed_nodes": ["n1", "n2"]},
            "node_outputs": {"n1": {"success": True}, "n2": {"success": True}},
        },
        "executed_nodes": ["n1", "n2"],
        "blocked": [],
    }

    def never_dispatch(tool_id, action, params):
        raise AssertionError("replay 不得 dispatch")

    result = _make_runtime(never_dispatch).replay_run(plan_id, "cpX", checkpointer=store)
    return {
        "success": bool(result.success),
        "node_ids": [r.node_id for r in result.node_results],
        "message": result.message,
        "dispatched": False,
    }


def build_contract_golden() -> dict:
    """从当前运行时计算一份确定性契约快照（归一化掉易变字段）。"""
    runtime = _make_runtime()
    plan = _sequential_plan()
    result = runtime.run(plan, runtime_context={"message": "契约"})
    return {
        "spec": "LG-W1-T10-B",
        "spec_title": "XCAGI LangGraph runtime contract freeze",
        "target": "app/infrastructure/workflow/langgraph_runtime.py (WorkflowRuntime port) + ports + types + langgraph_assert",
        "scope": [
            "FHD/tests/langgraph_absorption/test_langgraph_runtime_contract.py",
            "FHD/tests/langgraph_absorption/fixtures/langgraph_runtime_contract.json",
        ],
        "deterministic": True,
        "target_identity": {
            "class_name": XCAGILangGraphRuntime.__name__,
            "implements_protocol": WorkflowRuntime.__name__,
            "graph_source": StateGraph.__module__,
            "upstream_tag": UPSTREAM_TAG,
            "fail_closed_source_assertion": True,
        },
        "vendored_modules": {k: v for k, v in REQUIRED_VENDORED_MODULES.items()},
        "canonical_run": {
            "plan_id": plan.plan_id,
            "success": bool(result.success),
            "message": str(result.message),
            "executed_nodes": _executed_nodes(result),
            "node_results": [_normalize_node_result(r) for r in result.node_results],
            "final_context": _normalize_context(result.final_context),
        },
        "reducer_golden": _reducer_golden(),
        "checkpoint_golden": _checkpoint_shape_golden(),
        "resume_golden": _resume_golden(),
        "replay_golden": _replay_golden(),
    }


def canonical_json(golden: dict) -> str:
    """sort_keys=True、indent=2、UTF-8、末尾换行的规范化 JSON（字节可复现）。"""
    return json.dumps(golden, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def regenerate_fixture() -> Path:
    """把当前运行时行为写入 fixture（仅手动入口，pytest 绝不调用、绝不重写）。"""
    _FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    _FIXTURE_PATH.write_text(canonical_json(build_contract_golden()), encoding="utf-8")
    return _FIXTURE_PATH


# ===========================================================================
# A. Protocol 符合性与精确注入身份
# ===========================================================================


class TestProtocolIdentity:
    def test_runtime_conforms_to_workflow_runtime_protocol(self):
        assert isinstance(_make_runtime(), WorkflowRuntime)

    def test_exact_injected_dispatcher_identity_and_use(self):
        calls: list[str] = []
        dispatch = lambda t, a, p: calls.append(t) or {"success": True}
        runtime = _make_runtime(dispatch)
        assert runtime._dispatch is dispatch
        runtime.run(_sequential_plan())
        assert calls == ["t1", "t2", "t3"]

    def test_exact_injected_publisher_identity_and_use(self):
        pub = _FakePublisher()
        runtime = _make_runtime(publisher=pub)
        assert runtime._publisher is pub
        runtime.run(_sequential_plan())
        assert len(pub.events) == 3

    def test_default_dispatcher_fails_closed_when_unwired(self):
        runtime = XCAGILangGraphRuntime()
        result = runtime.run(_sequential_plan(1))
        assert result.success is False
        assert "未接线 dispatcher" in (result.node_results[0].error or "")


# ===========================================================================
# B. vendored StateGraph 来源 + fail-closed 来源断言 + 静态边界
# ===========================================================================

# ---------------------------------------------------------------------------
# Legacy 导入边界守卫（纯 helper）：ast 解析源码文本，返回确定性违例列表（空=通过）。
# 用 ast.walk 遍历整棵 AST（而非仅 tree.body），函数/类/TYPE_CHECKING 作用域内的
# import 也无法绕过；全程不依赖文本行扫描，多行/别名/相对导入均可覆盖。
# ---------------------------------------------------------------------------

_FORBIDDEN_MODULES = (
    "app.application.workflow.engine",
    "app.infrastructure.workflow.legacy_engine_adapter",
)
_FORBIDDEN_NAMES = ("WorkflowEngine", "LegacyEngineAdapter")
_RUNTIME_PKG = "app.infrastructure.workflow"


def _is_forbidden_module(module: str) -> bool:
    """精确命中或后代命中任一禁入模块。"""
    return any(module == fm or module.startswith(f"{fm}.") for fm in _FORBIDDEN_MODULES)


def _legacy_import_offenders(source: str) -> list[str]:
    """ast.parse 源码，返回违反 legacy 导入边界的确定性违例列表（空 = 通过）。"""
    tree = ast.parse(source)
    offenders: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden_module(alias.name):
                    offenders.append(f"import {alias.name}")
                if alias.asname in _FORBIDDEN_NAMES:
                    offenders.append(f"import {alias.name} as {alias.asname}")
        elif isinstance(node, ast.ImportFrom):
            # 相对/绝对 import 统一解析为 effective module（等价 importlib.util.resolve_name）
            rel = "." * node.level + (node.module or "")
            base = importlib.util.resolve_name(rel, _RUNTIME_PKG)
            if _is_forbidden_module(base):
                offenders.append(f"from {node.module or '.'} import *")
            for alias in node.names:
                imported = alias.name
                effective = f"{base}.{imported}" if base else imported
                if imported != "*" and _is_forbidden_module(effective):
                    offenders.append(f"from {node.module or '.'} import {imported}")
                if imported in _FORBIDDEN_NAMES or alias.asname in _FORBIDDEN_NAMES:
                    offenders.append(f"from {node.module or '.'} import {imported}")

    return sorted(set(offenders))


class TestVendoredSource:
    def test_stategraph_module_resolves_to_vendored_packages(self):
        source = getattr(StateGraph, "__module__", "")
        assert source == "langgraph.graph.state"

    def test_fail_closed_source_assertion_passes(self):
        # 模块 import 即执行了 assert_vendored_sources()；此处再显式复核（fail-closed）。
        assert_vendored_sources()

    def test_required_vendored_modules_all_resolve_under_packages(self):
        from app.infrastructure.workflow.langgraph_assert import _packages_root

        root = _packages_root().resolve()
        for module_name, expected_pkg in REQUIRED_VENDORED_MODULES.items():
            mod = __import__(module_name, fromlist=["*"])
            resolved = Path(mod.__file__).resolve()
            assert resolved.is_relative_to(root), (module_name, resolved)
            assert expected_pkg in resolved.as_posix()

    def test_vendored_module_identity_mapping_is_stable(self):
        assert REQUIRED_VENDORED_MODULES["langgraph.graph.state"] == "xcagi_langgraph_core"
        assert (
            REQUIRED_VENDORED_MODULES["langgraph.prebuilt.tool_node"] == "xcagi_langgraph_prebuilt"
        )
        assert "langgraph.checkpoint.sqlite" in REQUIRED_VENDORED_MODULES
        assert "langgraph_sdk.client" in REQUIRED_VENDORED_MODULES

    def test_runtime_source_does_not_import_legacy_engine(self):
        # 纯 ast helper 断言（非文本行扫描）：能覆盖多行/别名/函数作用域/相对导入
        # 等多达绕过路径；helper 返回空列表 = 通过。
        path = (
            Path(__file__).resolve().parents[2]
            / "app"
            / "infrastructure"
            / "workflow"
            / "langgraph_runtime.py"
        )
        assert _legacy_import_offenders(path.read_text(encoding="utf-8")) == []


class TestLegacyImportGuard:
    """legacy 导入边界纯 helper 的行为契约（合成源码用例）。"""

    def test_clean_imports_pass(self):
        src = textwrap.dedent(
            """\
            from app.application.workflow.ports.runtime import WorkflowRuntime
            from app.application.workflow.types import StateSchema
            import json
            import os.path
            from ..ports.events import StateUpdateEvent
            """
        )
        assert _legacy_import_offenders(src) == []

    def test_multiline_direct_import_caught(self):
        src = textwrap.dedent(
            """\
            from app.application.workflow import (
                engine,
            )
            """
        )
        assert _legacy_import_offenders(src) != []

    def test_function_scoped_import_caught(self):
        src = textwrap.dedent(
            """\
            def build():
                import app.infrastructure.workflow.legacy_engine_adapter
                return None
            """
        )
        assert _legacy_import_offenders(src) != []

    def test_type_checking_scoped_import_caught(self):
        src = textwrap.dedent(
            """\
            if TYPE_CHECKING:
                from app.application.workflow import engine
            """
        )
        assert _legacy_import_offenders(src) != []

    def test_from_parent_package_import_engine_caught(self):
        src = "from app.application.workflow import engine\n"
        assert _legacy_import_offenders(src) != []

    def test_relative_import_of_legacy_adapter_caught(self):
        src = "from . import legacy_engine_adapter\n"
        assert _legacy_import_offenders(src) != []

    def test_aliased_forbidden_class_caught(self):
        src = "from app.application.workflow.engine import WorkflowEngine as XEngine\n"
        assert _legacy_import_offenders(src) != []


# ===========================================================================
# C. build / compile
# ===========================================================================


class TestBuildCompile:
    def test_build_graph_returns_stategraph(self):
        graph = _make_runtime().build_graph(_sequential_plan())
        assert isinstance(graph, StateGraph)

    def test_compile_graph_compiles_to_invocable(self):
        compiled = _make_runtime().compile_graph(_sequential_plan())
        assert callable(getattr(compiled, "invoke", None))

    def test_compile_invalid_cyclic_plan_raises(self):
        cycle = PlanGraph(
            plan_id="p_cyc",
            intent="cycle",
            nodes=[
                WorkflowNode(node_id="n1", tool_id="t1", action="a1", next="n2"),
                WorkflowNode(node_id="n2", tool_id="t2", action="a2", next="n1"),
            ],
        )
        with pytest.raises(ValueError):
            _make_runtime().compile_graph(cycle)

    def test_invoke_graph_returns_final_state(self):
        state = _make_runtime().invoke_graph(_sequential_plan())
        # invoke_graph 返回未映射为 WorkflowRunResult 的原始图终态：
        # executed 是内部累积通道，workflow_status 保持 running（完成化在 run() 里做）。
        assert sorted(state["executed"]) == ["n1", "n2", "n3"]
        assert set(state["node_outputs"]) == {"n1", "n2", "n3"}


# ===========================================================================
# D. 顺序依赖执行
# ===========================================================================


class TestSequential:
    def test_runs_all_nodes_in_topological_order(self):
        result = _make_runtime().run(_sequential_plan())
        assert result.success is True
        assert [r.node_id for r in result.node_results] == ["n1", "n2", "n3"]

    def test_dependency_gates_downstream(self):
        calls: list[str] = []
        runtime = _make_runtime(lambda t, a, p: calls.append(t) or {"success": True})
        runtime.run(_sequential_plan())
        assert calls == ["t1", "t2", "t3"]

    def test_node_outputs_recorded(self):
        result = _make_runtime().run(_sequential_plan())
        assert set(result.final_context["node_outputs"]) == {"n1", "n2", "n3"}

    def test_workflow_status_completed(self):
        result = _make_runtime().run(_sequential_plan())
        assert result.final_context["workflow_status"]["state"] == "completed"
        assert _executed_nodes(result) == ["n1", "n2", "n3"]

    def test_stable_result_shape(self):
        result = _make_runtime().run(_sequential_plan())
        assert isinstance(result, WorkflowRunResult)
        assert all(isinstance(r, NodeExecutionResult) for r in result.node_results)


# ===========================================================================
# E. 条件路由 / branch / next 边
# ===========================================================================


def _conditional_plan() -> PlanGraph:
    return PlanGraph(
        plan_id="p_cond",
        intent="conditional",
        nodes=[
            WorkflowNode(
                node_id="check",
                tool_id="inventory",
                action="check_stock",
                risk="low",
                idempotent=True,
                branches=[Branch(target="buy", condition={"key": "low_stock", "equals": True})],
                next="normal",
            ),
            WorkflowNode(
                node_id="buy",
                tool_id="purchase",
                action="advice",
                risk="low",
                idempotent=True,
                depends_on=["check"],
            ),
            WorkflowNode(
                node_id="normal",
                tool_id="inventory",
                action="normal_advice",
                risk="low",
                idempotent=True,
                depends_on=["check"],
            ),
        ],
    )


class TestBranches:
    def test_condition_match_routes_to_branch(self):
        runtime = _make_runtime(lambda t, a, p: {"success": True, "low_stock": True})
        result = runtime.run(_conditional_plan())
        assert _executed_nodes(result) == ["buy", "check"]

    def test_no_match_falls_back_to_next(self):
        runtime = _make_runtime(lambda t, a, p: {"success": True, "low_stock": False})
        result = runtime.run(_conditional_plan())
        assert _executed_nodes(result) == ["check", "normal"]

    def test_unselected_branch_is_blocked(self):
        runtime = _make_runtime(lambda t, a, p: {"success": True, "low_stock": False})
        result = runtime.run(_conditional_plan())
        assert result.final_context.get("blocked") == ["buy"]
        assert "buy" not in result.final_context["node_outputs"]

    def test_no_match_and_no_next_ends_normally(self):
        plan = PlanGraph(
            plan_id="p_g",
            intent="gate",
            nodes=[
                WorkflowNode(
                    node_id="gate",
                    tool_id="x",
                    action="y",
                    risk="low",
                    idempotent=True,
                    branches=[Branch(target="target", condition={"key": "flag", "equals": True})],
                ),
                WorkflowNode(
                    node_id="target",
                    tool_id="z",
                    action="w",
                    risk="low",
                    idempotent=True,
                    depends_on=["gate"],
                ),
            ],
        )
        runtime = _make_runtime(lambda t, a, p: {"success": True, "flag": False})
        result = runtime.run(plan)
        assert result.success is True
        assert _executed_nodes(result) == ["gate"]

    def test_next_edge_followed_without_condition(self):
        plan = PlanGraph(
            plan_id="p_nx",
            intent="next",
            nodes=[
                WorkflowNode(
                    node_id="a", tool_id="t1", action="a1", risk="low", idempotent=True, next="b"
                ),
                WorkflowNode(
                    node_id="b",
                    tool_id="t2",
                    action="a2",
                    risk="low",
                    idempotent=True,
                    depends_on=["a"],
                ),
            ],
        )
        result = _make_runtime().run(plan)
        assert _executed_nodes(result) == ["a", "b"]


# ===========================================================================
# F. StateSchema reducer（set/append/merge_dict）+ 参数行为
# ===========================================================================


class TestReducers:
    def test_set_reducer_overwrites(self):
        schema = StateSchema().declare("value", type=str, merge="set")
        ctx = apply_state_schema({}, schema, writes={"value": "a"})
        ctx = apply_state_schema(ctx, schema, writes={"value": "b"})
        assert ctx["value"] == "b"

    def test_append_reducer_accumulates_list(self):
        schema = StateSchema().declare("history", type=list, merge="append")
        ctx = apply_state_schema({}, schema, writes={"history": "first"})
        ctx = apply_state_schema(ctx, schema, writes={"history": "second"})
        assert ctx["history"] == ["first", "second"]

    def test_merge_dict_reducer_updates_in_place(self):
        schema = StateSchema().declare("meta", type=dict, merge="merge_dict")
        ctx = apply_state_schema({}, schema, writes={"meta": {"a": 1}})
        ctx = apply_state_schema(ctx, schema, writes={"meta": {"b": 2}})
        assert ctx["meta"] == {"a": 1, "b": 2}

    def test_schema_type_mismatch_raises_fail_closed(self):
        schema = StateSchema().declare("count", type=int, merge="set")
        with pytest.raises(ValueError) as exc:
            apply_state_schema({}, schema, writes={"count": "not-an-int"})
        assert "count" in str(exc.value) and "类型不符" in str(exc.value)

    def test_schema_writes_applied_through_runtime(self):
        def d(tool_id, action, params):
            return {"success": True, "count": 1, "tags": tool_id, "meta": {tool_id: 1}}

        schema = (
            StateSchema()
            .declare("count", type=int, merge="set")
            .declare("tags", type=list, merge="append")
            .declare("meta", type=dict, merge="merge_dict")
        )
        result = _make_runtime(d).run(_sequential_plan(), state_schema=schema)
        assert result.final_context["count"] == 1
        assert result.final_context["tags"] == ["t1", "t2", "t3"]
        assert result.final_context["meta"] == {"t1": 1, "t2": 1, "t3": 1}


class TestStateSchemaParameterAndMutation:
    def test_state_schema_parameter_applied_via_run(self):
        calls: list[str] = []

        def d(tool_id, action, params):
            calls.append(tool_id)
            return {"success": True, "tag": tool_id}

        schema = StateSchema().declare("tag", type=list, merge="append")
        result = _make_runtime(d).run(_sequential_plan(), state_schema=schema)
        assert result.final_context["tag"] == ["t1", "t2", "t3"]

    def test_caller_runtime_context_not_mutated(self):
        # 深嵌套 runtime context：浅拷贝别名无法让断言假绿，只有真正的非修改
        # 分发语义才能通过（运行时只读入参，绝不改写调用方嵌套结构）。
        ctx = {
            "message": "hello",
            "_clarify_answers": {"n1": {"confirmed": True, "extra": [1, 2, {"k": "v"}]}},
            "session": {"meta": {"tags": ["a", "b"], "profile": {"id": 7, "roles": ["r1", "r2"]}}},
        }
        snapshot = copy.deepcopy(ctx)
        _make_runtime().run(_sequential_plan(), runtime_context=ctx)
        assert ctx == snapshot
        assert "executed" not in ctx

    def test_caller_plan_node_params_not_mutated(self):
        # 深嵌套 node params：即便运行时做 dict() 浅拷贝，也绝不能改写调用方
        # 传入的嵌套列表/字典，故用 deepcopy 快照做全等校验。
        plan = _sequential_plan()
        for node in plan.nodes:
            node.params = {
                "k": node.params["k"],
                "meta": {"nested": [node.params["k"], {"id": node.params["k"]}]},
            }
        snapshot = [copy.deepcopy(n.params) for n in plan.nodes]
        _make_runtime().run(plan)
        assert [n.params for n in plan.nodes] == snapshot


# ===========================================================================
# G. 重试与终止失败 / recovery 字段
# ===========================================================================


class TestRetry:
    def test_retry_then_success(self):
        calls = {"n": 0}

        def d(tool_id, action, params):
            calls["n"] += 1
            return {"success": False, "message": "temp"} if calls["n"] <= 1 else {"success": True}

        result = _make_runtime(d).run(_sequential_plan(1), max_retries=2)
        assert result.success is True
        assert result.node_results[0].retries == 1
        assert calls["n"] == 2

    def test_terminal_failure_sets_recovery_fields(self):
        result = _make_runtime(lambda t, a, p: {"success": False, "message": "permanent"}).run(
            _sequential_plan(1), max_retries=1
        )
        node = result.node_results[0]
        assert result.success is False
        assert node.error == "permanent"
        assert node.recovery_hint == "节点具备幂等性，可在修复后重试"
        assert result.final_context["workflow_status"]["state"] == "failed"

    def test_high_risk_non_idempotent_no_retry(self):
        plan = PlanGraph(
            plan_id="p_hr",
            intent="hr",
            nodes=[
                WorkflowNode(
                    node_id="w1",
                    tool_id="sales",
                    action="write",
                    params={},
                    risk="high",
                    idempotent=False,
                )
            ],
        )
        calls = {"n": 0}
        runtime = _make_runtime(
            lambda t, a, p: (
                calls.__setitem__("n", calls["n"] + 1) or {"success": False, "message": "denied"}
            )
        )
        result = runtime.run(plan, max_retries=5)
        node = result.node_results[0]
        assert result.success is False
        assert calls["n"] == 1
        assert node.retries == 0
        assert node.recovery_hint == "高风险/非幂等节点，请人工介入确认后再重试"

    def test_recoverable_exception_is_retried(self):
        calls = {"n": 0}

        def d(tool_id, action, params):
            calls["n"] += 1
            if calls["n"] <= 1:
                raise ValueError("transient")
            return {"success": True}

        result = _make_runtime(d).run(_sequential_plan(1), max_retries=2)
        assert result.success is True
        assert result.node_results[0].retries == 1


# ===========================================================================
# H. 并行 / 独占写 / parallel=False 串行
# ===========================================================================


def _parallel_read_plan() -> PlanGraph:
    return PlanGraph(
        plan_id="p_par",
        intent="parallel",
        nodes=[
            WorkflowNode(
                node_id=f"p{i}",
                tool_id=f"t{i}",
                action="query",
                params={},
                risk="low",
                idempotent=True,
            )
            for i in range(1, 4)
        ],
    )


def _assert_gate_serializes(monkeypatch, plan, *, parallel):
    """Event 驱动的独占证明：首个节点 dispatch 被故意阻塞时，第二个独立节点到达
    writer-acquire 尝试（第 2 次 gate 获取）却尚未进入 dispatch；释放后全部完成。

    不用 time.sleep / 时长比较；Event 的 wait timeout 仅用于防止死锁时挂死测试。
    """
    from app.infrastructure.workflow.langgraph_runtime import _ReadersWriterGate

    first_inside = threading.Event()
    second_acquiring = threading.Event()
    release_first = threading.Event()
    calls: list[str] = []
    first_done = [False]
    call_lock = threading.Lock()
    results: list = []

    original_acquire = _ReadersWriterGate._acquire_writer
    acquire_count = [0]

    def patched_acquire(self):
        acquire_count[0] += 1
        if acquire_count[0] == 2:
            # 每次独占节点恰好获取一次 gate；第二次获取必然来自另一个独立节点，
            # 而此时首个节点仍持有独占锁（被 dispatch 阻塞），故它只能在 acquire 等待。
            second_acquiring.set()
        return original_acquire(self)

    monkeypatch.setattr(_ReadersWriterGate, "_acquire_writer", patched_acquire)

    def dispatch(tool_id, action, params):
        with call_lock:
            calls.append(tool_id)
            am_first = not first_done[0]
            if am_first:
                first_done[0] = True
        if am_first:
            first_inside.set()
            release_first.wait(timeout=_DEADLOCK)
        return {"success": True}

    runtime = _make_runtime(dispatch)
    worker = threading.Thread(
        target=lambda: results.append(runtime.run(plan, parallel=parallel)), daemon=True
    )
    worker.start()
    assert first_inside.wait(timeout=_DEADLOCK), "首个节点未进入 dispatch"
    assert second_acquiring.wait(timeout=_DEADLOCK), "第二个节点未到达 writer-acquire 尝试"
    with call_lock:
        entered = list(calls)
    assert len(entered) == 1, entered  # 独占：第二个节点尚未进入 dispatch
    release_first.set()
    worker.join(timeout=_DEADLOCK)
    assert not worker.is_alive(), "runtime worker 未结束（疑似死锁）"
    result = results[0]
    assert result.success is True
    with call_lock:
        all_calls = list(calls)
    assert set(all_calls) == {n.tool_id for n in plan.nodes}, all_calls


class TestConcurrency:
    def test_low_risk_idempotent_readers_run_concurrently(self):
        barrier = threading.Barrier(3, timeout=5)
        seen: list[int] = []

        def d(tool_id, action, params):
            seen.append(threading.get_ident())
            barrier.wait(timeout=5)
            return {"success": True}

        result = _make_runtime(d).run(_parallel_read_plan())
        assert result.success is True
        assert len(set(seen)) == 3  # 三个只读节点确已并发

    def test_parallel_batch_metadata_recorded(self):
        result = _make_runtime().run(_parallel_read_plan())
        assert result.final_context["parallel_batches"] == [["p1", "p2", "p3"]]

    def test_high_risk_writer_exclusive_no_overlap(self, monkeypatch):
        plan = PlanGraph(
            plan_id="p_w",
            intent="writer",
            nodes=[
                WorkflowNode(
                    node_id="w1",
                    tool_id="s",
                    action="write",
                    params={},
                    risk="high",
                    idempotent=False,
                ),
                WorkflowNode(
                    node_id="w2",
                    tool_id="s",
                    action="write",
                    params={},
                    risk="high",
                    idempotent=False,
                ),
            ],
        )
        _assert_gate_serializes(monkeypatch, plan, parallel=True)

    def test_non_idempotent_writer_exclusive_no_overlap(self, monkeypatch):
        plan = PlanGraph(
            plan_id="p_ni",
            intent="nonidem",
            nodes=[
                WorkflowNode(
                    node_id="w1",
                    tool_id="s",
                    action="write",
                    params={},
                    risk="low",
                    idempotent=False,
                ),
                WorkflowNode(
                    node_id="w2",
                    tool_id="s",
                    action="write",
                    params={},
                    risk="low",
                    idempotent=False,
                ),
            ],
        )
        _assert_gate_serializes(monkeypatch, plan, parallel=True)

    def test_parallel_false_serializes_all_nodes(self, monkeypatch):
        _assert_gate_serializes(monkeypatch, _parallel_read_plan(), parallel=False)
        result = _make_runtime().run(_parallel_read_plan(), parallel=False)
        assert result.success is True
        assert result.final_context.get("parallel_batches") is None


# ===========================================================================
# I. 状态 callback 与 publisher 事件
# ===========================================================================


class TestEvents:
    def test_state_callback_emits_per_node_in_order(self):
        events: list[dict] = []
        _make_runtime().run(_sequential_plan(), state_event_callback=events.append)
        assert [e["type"] for e in events] == ["state.update"] * 3
        assert [e["node_id"] for e in events] == ["n1", "n2", "n3"]
        assert all(e["status"] == "succeeded" for e in events)

    def test_publisher_emits_state_update_events_in_order(self):
        pub = _FakePublisher()
        _make_runtime(publisher=pub).run(_sequential_plan())
        assert len(pub.events) == 3
        assert all(isinstance(e, StateUpdateEvent) for e in pub.events)
        assert [e.node_id for e in pub.events] == ["n1", "n2", "n3"]
        assert all(e.runtime == "xcagi-langgraph" for e in pub.events)
        assert pub.events[0].payload["type"] == "state.update"

    def test_callback_failure_does_not_break_run(self):
        def bad(_event):
            raise RuntimeError("callback boom")

        result = _make_runtime().run(_sequential_plan(), state_event_callback=bad)
        assert result.success is True

    def test_publisher_failure_does_not_break_run(self):
        class BoomPub:
            def publish_state_update(self, event):
                raise RuntimeError("pub boom")

        result = _make_runtime(publisher=BoomPub()).run(_sequential_plan())
        assert result.success is True


# ===========================================================================
# J. 不支持能力 fail-closed
# ===========================================================================


class TestUnsupportedFailClosed:
    def test_agentic_loop_fails_closed(self):
        with pytest.raises(NotImplementedError):
            _make_runtime().run(_sequential_plan(), agentic_loop=True)

    def test_tool_registry_fails_closed(self):
        with pytest.raises(NotImplementedError):
            _make_runtime().run(_sequential_plan(), tool_registry={"tools": []})


# ===========================================================================
# K. checkpoint / resume / replay
# ===========================================================================


class TestCheckpointResumeReplay:
    def test_checkpoint_saved_during_run_with_stable_shape(self):
        store = _FakeStore()
        _make_runtime().run(_sequential_plan(), checkpointer=store)
        latest = store.latest_checkpoint("p_rt")
        assert sorted(latest.keys()) == [
            "blocked",
            "checkpoint_id",
            "executed_nodes",
            "plan_id",
            "runtime_context",
            "step_index",
        ]
        assert latest["step_index"] == 3
        assert latest["executed_nodes"] == ["n1", "n2", "n3"]

    def test_checkpoints_recorded_per_successful_step(self):
        store = _FakeStore()

        def fail_at3(tool_id, action, params):
            return {"success": False, "message": "boom"} if tool_id == "t3" else {"success": True}

        _make_runtime(fail_at3).run(_sequential_plan(5, plan_id="p_cp"), checkpointer=store)
        assert sorted(c["step_index"] for c in store.list_checkpoints("p_cp")) == [1, 2]

    def test_resume_skips_executed_nodes_and_uses_supplied_checkpoint(self):
        store = _FakeStore()

        def fail_at3(tool_id, action, params):
            return {"success": False, "message": "boom"} if tool_id == "t3" else {"success": True}

        plan = _sequential_plan(5, plan_id="p_cp")
        _make_runtime(fail_at3).run(plan, checkpointer=store)
        checkpoint_id = store.latest_checkpoint("p_cp")["checkpoint_id"]

        resume_calls: list[str] = []
        resumed = _make_runtime(
            lambda t, a, p: resume_calls.append(t) or {"success": True}
        ).resume_run(plan, checkpoint_id, checkpointer=store)
        assert resumed.success is True
        assert _executed_nodes(resumed) == ["n1", "n2", "n3", "n4", "n5"]
        assert sorted(resume_calls) == ["t3", "t4", "t5"]  # 已完成节点不重跑
        assert "t1" not in resume_calls and "t2" not in resume_calls

    def test_resume_missing_checkpoint_fails_deterministically(self):
        result = _make_runtime().resume_run(_sequential_plan(), "cp-zzz", checkpointer=_FakeStore())
        assert result.success is False
        assert "checkpoint 不存在" in result.message

    def test_replay_read_only_never_dispatches(self):
        store = _FakeStore()
        plan_id = "p_rp"
        store._cps[(plan_id, "cpX")] = {
            "plan_id": plan_id,
            "checkpoint_id": "cpX",
            "step_index": 2,
            "runtime_context": {
                "results": [
                    {
                        "node_id": "n1",
                        "success": True,
                        "tool_id": "t1",
                        "action": "a1",
                        "params": {},
                        "output": {"success": True},
                        "error": "",
                        "recovery_hint": "",
                        "retries": 0,
                        "retryable": True,
                        "started_at": "",
                        "finished_at": "",
                        "duration_ms": 0,
                        "attempts": [],
                    },
                    {
                        "node_id": "n2",
                        "success": True,
                        "tool_id": "t2",
                        "action": "a2",
                        "params": {},
                        "output": {"success": True},
                        "error": "",
                        "recovery_hint": "",
                        "retries": 0,
                        "retryable": True,
                        "started_at": "",
                        "finished_at": "",
                        "duration_ms": 0,
                        "attempts": [],
                    },
                ],
                "workflow_status": {"state": "completed", "executed_nodes": ["n1", "n2"]},
                "node_outputs": {"n1": {"success": True}, "n2": {"success": True}},
            },
            "executed_nodes": ["n1", "n2"],
            "blocked": [],
        }

        def never_dispatch(tool_id, action, params):
            raise AssertionError("replay 不得 dispatch")

        result = _make_runtime(never_dispatch).replay_run(plan_id, "cpX", checkpointer=store)
        assert result.success is True
        assert [r.node_id for r in result.node_results] == ["n1", "n2"]

    def test_replay_missing_checkpoint_fails(self):
        result = _make_runtime().replay_run("ghost", checkpointer=_FakeStore())
        assert result.success is False
        assert "checkpoint 不存在" in result.message

    def test_invalid_checkpoint_id_path_fails(self):
        store = _FakeStore()
        store._cps[("p_ok", "cpY")] = {"plan_id": "p_ok", "checkpoint_id": "cpY", "step_index": 1}
        result = _make_runtime().replay_run("p_ok", "cp-bad", checkpointer=store)
        assert result.success is False


# ===========================================================================
# Fixture 冻结契约（只比较入库 fixture，绝不重写）
# ===========================================================================


class TestFixtureFreeze:
    def test_fixture_matches_current_runtime_behavior(self):
        assert _FIXTURE_PATH.exists(), "fixture 缺失，请手动运行 regenerate_fixture()"
        canonical = canonical_json(build_contract_golden())
        assert _FIXTURE_PATH.read_text(encoding="utf-8") == canonical, (
            "当前运行时行为与 fixture 不一致 —— 契约被破坏，禁止放宽断言或修改产品行为"
        )

    def test_canonical_rebuild_twice_is_identical(self):
        first = canonical_json(build_contract_golden())
        second = canonical_json(build_contract_golden())
        assert first == second
        assert first == canonical_json(json.loads(first))  # 规范化往返亦恒等

    def test_fixture_has_no_volatile_fields(self):
        assert _FIXTURE_PATH.exists()
        text = _FIXTURE_PATH.read_text(encoding="utf-8")
        assert not re.search(r"/(Users|private|opt|tmp|var)/", text)  # 无绝对路径
        assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", text) is None  # 无 ISO 时间戳
        assert re.search(r"cp-\d{14}", text) is None  # 无时间戳式 checkpoint ID
        assert re.search(r"\b[0-9a-f]{32}\b", text) is None  # 无 32 位十六进制随机 ID
        assert '"duration_ms"' not in text

    def test_fixture_is_valid_deterministic_json(self):
        assert _FIXTURE_PATH.exists()
        data = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
        assert data["spec"] == "LG-W1-T10-B"
        assert data["deterministic"] is True
        assert data["target_identity"]["class_name"] == "XCAGILangGraphRuntime"
        assert data["target_identity"]["implements_protocol"] == "WorkflowRuntime"
        assert data["canonical_run"]["success"] is True
        assert data["canonical_run"]["executed_nodes"] == ["n1", "n2", "n3"]
        assert data["vendored_modules"]["langgraph.graph.state"] == "xcagi_langgraph_core"


if __name__ == "__main__":
    # 独立手动入口：python tests/langgraph_absorption/test_langgraph_runtime_contract.py
    path = regenerate_fixture()
    print(f"fixture regenerated -> {path}")
