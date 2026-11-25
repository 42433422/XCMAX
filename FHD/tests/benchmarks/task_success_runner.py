"""任务级基准 runner（τ-bench 方法论）。

每个进程 = 一次独立 trial = 一份全新 SQLite 测试库，保证 pass^k 的
多次试验之间互不污染（τ-bench 的可靠性口径：同一任务 k 次试验全过才算过）。

用法（由 test_task_success.py 按 trial 逐个拉起）：

    python tests/benchmarks/task_success_runner.py \
        --tasks tests/benchmarks/task_golden_set.json \
        --trial 0 --out /tmp/trial_0.jsonl

评测链路：instruction → qualified Codex runtime → durable host child tasks
（包含审批、依赖和工具结果校验）→ DB 终态断言（复用
business_db_write_verification._model_config 的实体映射 SSOT）。
"""

from __future__ import annotations

import argparse
import atexit
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
    """在导入 app 之前设置隔离环境：独立 SQLite 文件；模型仅使用显式配置且已认证的 Codex 路由。"""
    global _BOOTED
    if _BOOTED:
        return
    workspace = tempfile.TemporaryDirectory(prefix="xcagi-task-bench-")
    atexit.register(workspace.cleanup)
    tmpdir = workspace.name
    url = f"sqlite+pysqlite:///{tmpdir}/trial.sqlite3"
    os.environ["DATABASE_URL"] = url
    os.environ["VECTOR_DB_URL"] = url
    os.environ.setdefault("XCAGI_SKIP_INTENT_LLM", "1")
    os.environ["XCAGI_AGENT_RUNTIME_HOOKS"] = "0"
    os.environ["MODEL_USAGE_LEDGER_PATH"] = f"{tmpdir}/usage.json"
    os.environ["MODEL_USAGE_WALLET_BACKEND"] = "audit"
    os.environ.pop("MODEL_USAGE_WALLET_REQUIRED", None)
    os.environ["XCAGI_DATA_DIR"] = f"{tmpdir}/data"
    os.environ["XCAGI_DIALOGUE_MEMORY_DIR"] = f"{tmpdir}/dialogue"
    os.environ["XCAGI_TOOL_IDEMPOTENCY_PATH"] = f"{tmpdir}/idempotency.sqlite"
    # 计划追溯日志重定向到临时目录，避免污染仓库 resources/routing_policies/
    os.environ["XCAGI_PLAN_GRAPH_LOG"] = f"{tmpdir}/plan_graphs.jsonl"
    _BOOTED = True


def _completed_model_requests(metadata: dict[str, Any]) -> int:
    """Count only original-run requests that actually returned and settled usage."""
    calls = metadata.get("codex_runtime", {}).get("model_requests", {})
    return sum(
        row.get("state") == "completed" and isinstance(row.get("usage"), dict)
        for row in calls.values()
        if isinstance(row, dict)
    )


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
    from app.db import SessionLocal, engine
    from app.db.db_base import Base
    from app.infrastructure.tenant_scope import current_tenant_id
    from scripts.dev.task_benchmark_assertions import assertion_model_config as _model_config

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


def _execute_plan(plan: Any, task: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    """Exercise the product orchestrator, including its approval and dependency gates.

    Approvals are explicit scenario inputs, never inferred from expected success.
    Clarification remains waiting until a later user turn is represented in a case.
    Durability and HTTP authorization are verified separately from this benchmark.
    """
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository

    orchestrator = AgentOrchestrator(repository=InMemoryAgentRunRepository())
    context = {"tenant_id": 1, "source": "task_benchmark"}
    run = orchestrator.start_run_from_plan(
        user_id="bench-user", message=task["instruction"], plan=plan, runtime_context=context
    )
    approval_error = ""
    for answer in task.get("answers") or []:
        waiting = next((step for step in run.steps if step.status == "waiting_user"), None)
        target = next(
            (
                step
                for step in run.steps
                if waiting is not None and step.node_id == waiting.params.get("target_node_id")
            ),
            None,
        )
        if (
            waiting is None
            or waiting.tool_id != "clarify"
            or target is None
            or _action_sig(target) != {"tool_id": answer["tool_id"], "action": answer["action"]}
        ):
            approval_error = "scripted answer does not match the pending clarification target"
            break
        orchestrator.stage_clarification_answer(
            run.run_id,
            step_id=waiting.step_id,
            parameters=answer["parameters"],
            requested_by="bench-user",
        )
        continued = orchestrator.execute_dispatched_run(run.run_id)
        if continued is None:
            approval_error = "answered run disappeared"
            break
        run = continued
    for approval in task.get("approvals") or []:
        if approval_error:
            break
        waiting = next((step for step in run.steps if step.status == "waiting_user"), None)
        if (
            run.status != "waiting_user"
            or waiting is None
            or waiting.tool_id == "clarify"
            or _action_sig(waiting)
            != {"tool_id": approval["tool_id"], "action": approval["action"]}
            or waiting.params != approval["params"]
        ):
            approval_error = "scripted approval does not match the pending action and parameters"
            break
        continued = orchestrator.continue_run(
            run.run_id,
            approved_by="bench-user",
            approved_step_id=waiting.step_id,
            runtime_context=context,
        )
        if continued is None:
            approval_error = "approved run disappeared"
            break
        run = continued
    expected_status = (task.get("expect") or {}).get("run_status", "completed")
    success = not approval_error and run.status == expected_status
    reason = approval_error or (
        "" if success else f"run status: expected {expected_status}, got {run.status}; {run.error}"
    )
    return (
        success,
        reason,
        {
            "run_id": run.run_id,
            "artifacts": [artifact.to_dict() for artifact in run.artifacts],
            "status": run.status,
            "steps": [step.to_dict() for step in run.steps],
            "tool_calls": [call.to_dict() for call in run.tool_calls],
            "final_output": run.final_output,
            "error": run.error,
        },
    )


def _trial_session_factory():
    """Bind a real engine once; the lazy proxy is not an ORM transaction identity."""
    from sqlalchemy.orm import sessionmaker

    from app.db import get_runtime_engine

    return sessionmaker(bind=get_runtime_engine())

def _execute_goal(task: dict[str, Any]) -> tuple[bool, str, dict[str, Any], list[Any]]:
    """Use the same authenticated Codex/SQL queue as product requests.

    The caller's explicit scenario answers/approvals are the only continuation
    authority. No expected success can approve an action or select another model.
    A missing qualified route fails this live benchmark visibly.
    """
    from datetime import timedelta
    from types import SimpleNamespace
    from uuid import uuid4

    from starlette.requests import Request

    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.approval_grant import issue_approval_grant
    from app.application.agent_orchestrator.approval_transaction import approve_and_enqueue
    from app.application.agent_orchestrator.run_repository import set_agent_run_repository_for_tests
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher
    from app.application.agent_orchestrator.task_execution_repository import (
        set_task_execution_repository_for_tests,
    )
    from app.application.agent_orchestrator.task_execution_sql_repository import (
        SQLAlchemyTaskExecutionRepository,
    )
    from app.application.agent_runtime.gateway import run_runtime_task
    from app.db.models.permission import Role
    from app.db.models.user import Session as UserSession
    from app.db.models.user import User
    from app.fastapi_routes.domains.agent.route_support import authenticated_runtime_context
    from app.infrastructure.auth.agent_principal import require_agent_principal
    from app.infrastructure.codex.binding import CodexBindingStore
    from app.infrastructure.codex.receipt_projection import (
        refresh_codex_receipts,
        resume_ready_codex_runs,
    )
    from app.utils.security.password_hash import generate_password_hash
    from app.utils.time import utc_now_naive

    factory = _trial_session_factory()
    sid = uuid4().hex
    with factory.begin() as db:
        # Reuse the real bootstrap grants: never manufacture a second copy of
        # every Permission while runtime startup may also be seeding RBAC.
        role = db.query(Role).filter(Role.name == "admin").one_or_none()
        if role is None or not role.is_system:
            raise RuntimeError("task benchmark requires seeded system admin RBAC")
        actor = User(
            username="task-benchmark-" + sid,
            password=generate_password_hash(uuid4().hex),
            tenant_id=1,
            role="admin",
            tier="enterprise",
        )
        db.add(actor)
        db.flush()
        db.add(
            UserSession(
                session_id=sid, user_id=actor.id, expires_at=utc_now_naive() + timedelta(hours=1)
            )
        )
    principal = require_agent_principal(
        Request({"type": "http", "headers": [(b"x-session-id", sid.encode())]}), x_user_id=None
    )
    context = authenticated_runtime_context(
        {"source": "task_benchmark", "turn_id": uuid4().hex}, principal
    )
    repository = SQLAlchemyAgentRunRepository(session_factory=factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=factory)
    set_agent_run_repository_for_tests(repository)
    set_task_execution_repository_for_tests(queue)
    dispatcher = AgentTaskDispatcher(execution_repository=queue, run_repository=repository)

    def drain(run_id):
        owner = "task-benchmark-worker"
        execution = queue.claim(owner, lease_seconds=600)
        if execution is None or execution.run_id != run_id:
            raise RuntimeError("original benchmark task was not claimed")
        dispatcher._execute_claim(execution, owner)
        return repository.get(run_id)

    admitted = run_runtime_task(
        task=task["instruction"],
        system_prompt="",
        runtime_context=context,
        completion_mode="auto",
        start_queued=True,
        _repository=repository,
    )
    if admitted.get("execution_state") != "queued":
        return (
            False,
            str(admitted.get("error_code") or "runtime admission failed"),
            {
                "status": "blocked",
                "final_output": admitted,
                "runtime_admitted": False,
                "model_responses": 0,
            },
            [],
        )
    parent = drain(admitted["run_id"])
    store = CodexBindingStore(repository)
    approvals, answers = list(task.get("approvals") or []), list(task.get("answers") or [])
    error = ""
    for _ in range(32):
        rows = store.receipt_snapshot(parent.run_id)
        children = [repository.get(row["child_run_id"]) for row in rows]
        waiting = [
            (child, step)
            for child in children
            for step in child.steps
            if step.status == "waiting_user"
        ]
        if not waiting:
            binding = store.get(parent.run_id)
            if (
                binding.metadata.get("waiting_input")
                and answers
                and isinstance(answers[0].get("reply"), str)
            ):
                answer = answers.pop(0)
                staged = run_runtime_task(
                    task=answer["reply"],
                    system_prompt="",
                    runtime_context={**context, "turn_id": uuid4().hex},
                    run_id=parent.run_id,
                    completion_mode="auto",
                    answer_to_waiting_input=True,
                    start_queued=True,
                    _repository=repository,
                )
                if staged.get("execution_state") != "queued":
                    error = "original input wait could not be resumed"
                    break
                parent = drain(parent.run_id)
                continue
            if resume_ready_codex_runs(repository=repository):
                parent = drain(parent.run_id)
                continue
            break
        child, step = waiting[0]
        if step.tool_id == "clarify":
            target = next(
                (node for node in child.steps if node.node_id == step.params.get("target_node_id")),
                None,
            )
            if not answers:
                break
            answer = answers.pop(0)
            if target is None or _action_sig(target) != {
                key: answer[key] for key in ("tool_id", "action")
            }:
                error = "scripted answer does not match the original clarification target"
                break
            AgentOrchestrator(repository=repository).stage_clarification_answer(
                child.run_id,
                step_id=step.step_id,
                parameters=answer["parameters"],
                requested_by=principal.user_id,
                queue=queue,
                parent_snapshot=parent,
            )
        else:
            if not approvals:
                break
            approval = approvals.pop(0)
            if (
                _action_sig(step) != {key: approval[key] for key in ("tool_id", "action")}
                or step.params != approval["params"]
            ):
                error = "scripted approval does not match the pending action and parameters"
                break
            grant = issue_approval_grant(child, principal_id=principal.user_id)
            if grant is None:
                error = "pending child has no host approval grant"
                break
            approve_and_enqueue(
                repository,
                queue,
                run_id=child.run_id,
                token=grant["grant"],
                principal_id=principal.user_id,
                runtime_context={},
                authenticated_binding=principal.mod_authorization,
                authenticated_actor_binding=principal.actor_authorization,
            )
        drain(child.run_id)
        parent = refresh_codex_receipts(repository.get(parent.run_id), repository=repository)
    parent = refresh_codex_receipts(repository.get(parent.run_id), repository=repository)
    rows = store.receipt_snapshot(parent.run_id)
    children = [repository.get(row["child_run_id"]) for row in rows]
    nodes = [SimpleNamespace(tool_id=row["tool_id"], action=row["action"]) for row in rows]
    expected_status = (task.get("expect") or {}).get("run_status", "completed")
    passed = not error and parent.status == expected_status
    reason = error or (
        ""
        if passed
        else f"run status: expected {expected_status}, got {parent.status}; {parent.error}"
    )
    execution = {
        **parent.to_dict(),
        "runtime_admitted": True,
        "steps": [step.to_dict() for child in children for step in child.steps],
        "tool_calls": [call.to_dict() for child in children for call in child.tool_calls],
        "final_output": {
            **parent.final_output,
            "node_outputs": {
                key: value
                for child in children
                for key, value in child.final_output.get("node_outputs", {}).items()
            },
        },
        "model_responses": _completed_model_requests(parent.metadata),
    }
    return passed, reason, execution, nodes


def run_trial(tasks_path: Path, trial: int, out_path: Path) -> None:
    _bootstrap_isolated_db()
    import app.db.models
    from app.db import engine
    from app.db.db_base import Base
    from app.db.init_db import ensure_sqlite_rbac_bootstrap
    from app.infrastructure.tenant_scope import tenant_scope
    from scripts.dev.task_benchmark_assertions import (
        check_returned_records,
        check_spreadsheets,
        seed_inventory_quantities,
        seed_ledger_period_entries,
        seed_records,
        seed_sales_period_orders,
    )

    data = json.loads(tasks_path.read_text(encoding="utf-8"))
    tasks = data["tasks"]

    out_path.parent.mkdir(parents=True, exist_ok=True)

    def _reset_db() -> None:
        """每任务前重建 schema：对齐 τ-bench「每个任务从初始 DB 状态出发」。"""
        engine.dispose()
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine, checkfirst=True)
        # Each task starts from the production RBAC seed, on the isolated trial
        # database, before the runtime imports can attempt lazy initialization.
        ensure_sqlite_rbac_bootstrap(engine=engine, swallow_errors=False)

    with out_path.open("w", encoding="utf-8") as out, tenant_scope(1):
        for task in tasks:
            expect = task.get("expect") or {}
            result: dict[str, Any] = {
                "task_id": task["task_id"],
                "domain": task.get("domain"),
                "difficulty": task.get("difficulty"),
                "trial": trial,
                "routing_pass": False,
                "runtime_admitted": False,
                "exec_pass": None,
                "db_pass": None,
                "pass": False,
                "failure": None,
            }
            try:
                _reset_db()
                seed_records(task.get("fixtures") or [])
                seed_inventory_quantities(task.get("inventory_quantities") or [])
                seed_sales_period_orders(task.get("sales_period_orders") or [])
                seed_ledger_period_entries(task.get("ledger_period_entries") or [])
                exec_ok, exec_why, executed, nodes = _execute_goal(task)
                result["runtime_admitted"] = executed.get("runtime_admitted") is True
                ok, why = _check_no_actions(nodes, expect)
                if ok:
                    ok, why = _check_routing(nodes, expect)
                if ok:
                    ok, why = _check_forbid(nodes, expect)
                result["routing_pass"] = ok
                result["plan"] = [_action_sig(n) for n in nodes]
                result["execution"] = executed
                if expect.get("no_tool_calls") and executed.get("tool_calls"):
                    exec_ok = False
                    exec_why = "unexpected tool execution while user input was required"
                result["exec_pass"] = exec_ok
                db_ok, db_why = _check_db_state(expect)
                result["db_pass"] = db_ok
                output_ok, output_why = check_returned_records(
                    executed, expect.get("returned_records") or []
                )
                result["output_pass"] = output_ok
                artifact_ok, artifact_why = check_spreadsheets(
                    executed, expect.get("spreadsheets") or []
                )
                result["artifact_pass"] = artifact_ok
                result["failure"] = (
                    "; ".join(
                        reason
                        for reason in (why, exec_why, db_why, output_why, artifact_why)
                        if reason
                    )
                    or None
                )
                result["pass"] = ok and exec_ok and db_ok and output_ok and artifact_ok
            except _TRIAL_BOUNDARY_ERRORS as exc:
                result["failure"] = f"{type(exc).__name__}: {exc}"
            result["model_responses"] = (result.get("execution") or {}).get("model_responses", 0)
            out.write(json.dumps(result, ensure_ascii=False) + "\n")
            out.flush()


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
