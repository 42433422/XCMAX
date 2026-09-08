"""任务级基准 runner（τ-bench 方法论）。

每个进程 = 一次独立 trial = 一份全新 SQLite 测试库，保证 pass^k 的
多次试验之间互不污染（τ-bench 的可靠性口径：同一任务 k 次试验全过才算过）。

用法（由 test_task_success.py 按 trial 逐个拉起）：

    python tests/benchmarks/task_success_runner.py \
        --tasks tests/benchmarks/task_golden_set.json \
        --trial 0 --out /tmp/trial_0.jsonl

评测链路：instruction → LLMWorkflowPlanner.plan() → 逐节点
execute_registered_workflow_tool() → DB 终态断言（复用
business_db_write_verification._model_config 的实体映射 SSOT）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

_BOOTED = False

# trial/节点隔离边界：任何异常都记为该 trial 失败，不得中断基准进程（具名元组过 broad-except gate）
_TRIAL_BOUNDARY_ERRORS: tuple[type[Exception], ...] = (Exception,)


def _bootstrap_isolated_db() -> None:
    """在导入 app 之前设置隔离环境：独立 SQLite 文件 + 关闭 LLM。"""
    global _BOOTED
    if _BOOTED:
        return
    tmpdir = tempfile.mkdtemp(prefix="xcagi-task-bench-")
    url = f"sqlite+pysqlite:///{tmpdir}/trial.sqlite3"
    os.environ["DATABASE_URL"] = url
    os.environ["VECTOR_DB_URL"] = url
    os.environ.setdefault("XCAGI_SKIP_INTENT_LLM", "1")
    os.environ.setdefault("FHD_ALLOW_X_USER_ID_HEADER", "1")
    # 计划追溯日志重定向到临时目录，避免污染仓库 resources/routing_policies/
    os.environ.setdefault("XCAGI_PLAN_GRAPH_LOG", f"{tmpdir}/plan_graphs.jsonl")
    _BOOTED = True


def _action_sig(node: Any) -> dict[str, str]:
    return {"tool_id": str(node.tool_id), "action": str(node.action)}


def _sig_matches(actual: dict[str, str], expect: dict[str, str]) -> bool:
    return actual["tool_id"] == expect["tool_id"] and (
        expect["action"] == "*" or actual["action"] == expect["action"]
    )


def _check_routing(nodes: list[Any], expect: dict[str, Any]) -> tuple[bool, str]:
    """校验计划动作序列：actions（有序精确）或 actions_any_of（备选）。"""
    sigs = [_action_sig(n) for n in nodes]
    expected_list = expect.get("actions")
    alternatives = expect.get("actions_any_of")
    if alternatives is not None:
        for alt in alternatives:
            if len(alt) == len(sigs) and all(_sig_matches(s, e) for s, e in zip(sigs, alt)):
                return True, ""
        want = " | ".join(
            ",".join(f"{e['tool_id']}.{e['action']}" for e in alt) for alt in alternatives
        )
        got = ",".join(f"{s['tool_id']}.{s['action']}" for s in sigs) or "<empty>"
        return False, f"actions_any_of 不匹配：期望[{want}] 实际[{got}]"
    if expected_list is not None:
        if len(expected_list) != len(sigs) or not all(
            _sig_matches(s, e) for s, e in zip(sigs, expected_list)
        ):
            want = ",".join(f"{e['tool_id']}.{e['action']}" for e in expected_list)
            got = ",".join(f"{s['tool_id']}.{s['action']}" for s in sigs) or "<empty>"
            return False, f"actions 不匹配：期望[{want}] 实际[{got}]"
        return True, ""
    # 未声明 actions 期望时，仅要求计划存在（no_actions 由调用方单独检查）
    return True, ""


def _check_forbid(nodes: list[Any], expect: dict[str, Any]) -> tuple[bool, str]:
    for node in nodes:
        sig = _action_sig(node)
        for f in expect.get("forbid_actions") or []:
            if _sig_matches(sig, f):
                return False, f"出现被禁止的调用 {f['tool_id']}.{f['action']}"
    return True, ""


def _check_no_actions(nodes: list[Any], expect: dict[str, Any]) -> tuple[bool, str]:
    if expect.get("no_actions") and nodes:
        got = ",".join(f"{n.tool_id}.{n.action}" for n in nodes)
        return False, f"期望无业务节点，实际[{got}]"
    return True, ""


def _check_db_state(expect: dict[str, Any]) -> tuple[bool, str]:
    """执行完成后校验 DB 终态。断言前 dispose 连接池刷新 SQLite 快照。"""
    assertions = expect.get("db_state") or []
    if not assertions:
        return True, ""
    from app.application.business_db_write_verification import _model_config
    from app.db import SessionLocal, engine
    from app.db.base import Base
    from app.infrastructure.tenant_scope import current_tenant_id

    engine.dispose()  # 刷新连接池：旧连接持有 WAL 旧快照会看不到已提交写入
    Base.metadata.create_all(engine, checkfirst=True)
    tenant_id = current_tenant_id()

    with SessionLocal() as db:
        for spec in assertions:
            entity = spec["entity"]
            try:
                model, field_map, _selector = _model_config(entity)
            except ValueError:
                return False, f"db_state 断言不支持实体 {entity}"
            query = db.query(model).filter(model.tenant_id == tenant_id)
            for key, value in (spec.get("where") or {}).items():
                column = getattr(model, field_map.get(key, key), None)
                if column is None:
                    return False, f"实体 {entity} 无字段 {key}"
                query = query.filter(column == value)
            op = spec.get("op", "exists")
            if op == "exists":
                if query.first() is None:
                    return False, f"DB 终态缺失：{entity} {spec.get('where')}"
            elif op == "absent":
                if query.first() is not None:
                    return False, f"DB 终态不应存在：{entity} {spec.get('where')}"
            elif op == "count":
                actual = query.count()
                if actual != int(spec["count"]):
                    return False, f"DB 终态计数不符：{entity} 期望{spec['count']} 实际{actual}"
            else:
                return False, f"未知 db_state.op：{op}"
    return True, ""


def _execute_nodes(nodes: list[Any]) -> tuple[bool, str, list[dict[str, Any]]]:
    """逐节点执行计划。clarify.ask 是交互节点，跳过执行只算路由。"""
    from app.services.tools_workflow_registered import execute_registered_workflow_tool

    executed: list[dict[str, Any]] = []
    for node in nodes:
        if node.tool_id == "clarify":
            executed.append({"tool_id": node.tool_id, "action": node.action, "skipped": True})
            continue
        params = {k: v for k, v in (node.params or {}).items() if k != "_runtime_context"}
        try:
            result = execute_registered_workflow_tool(node.tool_id, node.action, dict(params))
        except _TRIAL_BOUNDARY_ERRORS as exc:
            return False, f"{node.tool_id}.{node.action} 执行异常: {exc}", executed
        executed.append(
            {
                "tool_id": node.tool_id,
                "action": node.action,
                "success": bool(result.get("success")),
                "message": result.get("message"),
            }
        )
        if not result.get("success"):
            return (
                False,
                f"{node.tool_id}.{node.action} 执行失败: {result.get('message') or result.get('error')}",
                executed,
            )
    return True, "", executed


def run_trial(tasks_path: Path, trial: int, out_path: Path) -> None:
    _bootstrap_isolated_db()
    import app.db.models  # noqa: F401  确保全部模型注册后再建表
    from app.application.workflow.planner import LLMWorkflowPlanner
    from app.db import engine
    from app.db.base import Base
    from app.infrastructure.tenant_scope import tenant_scope
    from app.services.tools_execution.registry import get_workflow_tool_registry

    Base.metadata.create_all(engine, checkfirst=True)

    data = json.loads(tasks_path.read_text(encoding="utf-8"))
    tasks = data["tasks"]

    out_path.parent.mkdir(parents=True, exist_ok=True)

    def _reset_db() -> None:
        """每任务前重建 schema：对齐 τ-bench「每个任务从初始 DB 状态出发」。"""
        engine.dispose()
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine, checkfirst=True)

    with out_path.open("w", encoding="utf-8") as out, tenant_scope(1):
        planner = LLMWorkflowPlanner()
        registry = get_workflow_tool_registry()
        for task in tasks:
            _reset_db()
            expect = task.get("expect") or {}
            result: dict[str, Any] = {
                "task_id": task["task_id"],
                "domain": task.get("domain"),
                "difficulty": task.get("difficulty"),
                "trial": trial,
                "routing_pass": False,
                "exec_pass": None,
                "db_pass": None,
                "pass": False,
                "failure": None,
            }
            try:
                plan = planner.plan("bench-user", task["instruction"], registry)
                nodes = list(plan.nodes) if plan else []
                ok, why = _check_no_actions(nodes, expect)
                if ok:
                    ok, why = _check_routing(nodes, expect)
                if ok:
                    ok, why = _check_forbid(nodes, expect)
                result["routing_pass"] = ok
                if not ok:
                    result["failure"] = why
                    result["plan"] = [_action_sig(n) for n in nodes]
                else:
                    has_db_assert = bool(expect.get("db_state"))
                    if nodes:
                        exec_ok, exec_why, executed = _execute_nodes(nodes)
                        result["exec_pass"] = exec_ok
                        result["executed"] = executed
                        if not exec_ok:
                            result["failure"] = exec_why
                    elif has_db_assert:
                        result["exec_pass"] = True
                    db_ok, db_why = _check_db_state(expect)
                    result["db_pass"] = db_ok
                    if not db_ok:
                        result["failure"] = db_why
                    result["pass"] = (
                        result["routing_pass"] and result["exec_pass"] is not False and db_ok
                    )
            except _TRIAL_BOUNDARY_ERRORS as exc:
                result["failure"] = f"{type(exc).__name__}: {exc}"
            out.write(json.dumps(result, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="任务级基准 trial runner")
    parser.add_argument("--tasks", required=True, type=Path)
    parser.add_argument("--trial", required=True, type=int)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    run_trial(args.tasks, args.trial, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
