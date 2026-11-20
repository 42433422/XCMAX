"""Compose the existing employee, GitHub and audit components through LangGraph."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.integrations.repository_packages import load_repository_module
from modstore_server.models import RetortEvolutionRun, get_engine, get_session_factory
from modstore_server.operational_errors import RECOVERABLE_ERRORS

TERMINAL = {"completed", "rejected", "failed", "cancelled", "customer_impact_rejected"}


def catalog():
    root = Path(os.environ.get("XCMAX_MONOREPO_ROOT") or Path(__file__).resolve().parents[3])
    return json.loads((root / "FHD/config/audit_benchmark_ssot.json").read_text())


@contextmanager
def checkpoint():
    dsn = os.environ.get("MODSTORE_RETORT_CHECKPOINT_DSN", "")
    if dsn.startswith("postgresql://"):
        from langgraph.checkpoint.postgres import PostgresSaver

        with PostgresSaver.from_conn_string(dsn) as saver:
            saver.setup()
            yield saver
    elif dsn.startswith("sqlite:///"):
        from langgraph.checkpoint.sqlite import SqliteSaver

        with SqliteSaver.from_conn_string(dsn.removeprefix("sqlite:///")) as saver:
            yield saver
    else:
        raise ValueError("Retort 持久流程尚未配置；请选择已有 PostgreSQL 或隔离验收数据库")


@contextmanager
def run_lock(request_id):
    """Use native database session locks; local SQLite uses the filelock package."""
    key = "retort:" + str(UUID(request_id))
    engine = get_engine()
    if engine.dialect.name == "sqlite":
        from filelock import FileLock

        with FileLock(str(engine.url.database) + "." + key.replace(":", "-") + ".lock", timeout=0):
            yield
        return
    with engine.connect() as connection:
        if engine.dialect.name == "postgresql":
            acquire, release = (
                "pg_try_advisory_lock(hashtextextended(:key, 0))",
                "pg_advisory_unlock(hashtextextended(:key, 0))",
            )
        elif engine.dialect.name in {"mysql", "mariadb"}:
            acquire, release = "GET_LOCK(:key, 0)", "RELEASE_LOCK(:key)"
        else:
            raise ValueError("该数据库尚未提供可验证的跨进程执行锁")
        if not connection.execute(text("SELECT " + acquire), {"key": key}).scalar():
            raise ValueError("该任务正在另一执行节点处理中")
        try:
            yield
        finally:
            connection.execute(text("SELECT " + release), {"key": key})


def create_run(request, actor_id, *, customer_feedback=None):
    contract = load_repository_module("retort_engine.evolution_contract")
    protocol = contract.freeze_request(request, catalog())
    from modstore_server.customer_ticket_github import configuration

    if protocol["repository"] != configuration()["repository"]:
        raise ValueError("改进任务只能使用已绑定的共享产品仓库")
    with get_session_factory()() as db:
        previous = db.get(RetortEvolutionRun, protocol["request_id"])
        if previous:
            if (
                previous.user_id != actor_id
                or json_loads(previous.protocol_json, {}) != protocol
                or json_loads(previous.effects_json, {}).get("customer_feedback")
                != customer_feedback
            ):
                raise ValueError("相同请求编号已绑定其他任务")
            return previous.id
        row = RetortEvolutionRun(
            id=protocol["request_id"],
            user_id=actor_id,
            protocol_json=json_dumps(protocol),
            effects_json=json_dumps(
                {"customer_feedback": customer_feedback} if customer_feedback else {}
            ),
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            previous = db.get(RetortEvolutionRun, protocol["request_id"])
            if (
                previous is None
                or previous.user_id != actor_id
                or json_loads(previous.protocol_json, {}) != protocol
                or json_loads(previous.effects_json, {}).get("customer_feedback")
                != customer_feedback
            ):
                raise ValueError("相同请求编号已绑定其他任务") from None
            return previous.id
        return row.id


class ComponentPorts:
    def __init__(self, request_id):
        self.request_id = request_id

    def plan(self, protocol):
        from modstore_server.retort_customer_feedback import private_approval_context

        module = load_repository_module("retort_engine.models")
        tasks = [
            module.ImprovementTask(
                f"{protocol['request_id']}:{item['id']}",
                item["requirement"],
                item["domain_id"],
                protocol["goal"],
                "优先迁移成熟组件，在原员工工作空间完成改造并提交证据。",
                item["requirement"],
                "fhd-core-maintainer",
                "P1",
            ).to_dict()
            for item in protocol["criteria"]
        ]
        sources = protocol["references"]
        feedback = private_approval_context(self.request_id)
        return {
            **({"private_customer_feedback": feedback} if feedback else {}),
            "tasks": tasks,
            "sources": sources,
            "public_title": protocol["title"],
            "public_body": protocol["goal"]
            + "\n\n验收要求：\n"
            + "\n".join(f"- {item['id']}: {item['requirement']}" for item in protocol["criteria"])
            + "\n\n参考：\n"
            + "\n".join(f"- {s['url']} @ {s['source_commit']}" for s in sources)
            + "\n\n测试协议："
            + protocol["protocol_digest"],
        }

    def optimize(self, protocol, plan):
        path = os.environ.get("MODSTORE_RETORT_RSI_PROTOCOL", "")
        if not path:
            return {
                "engine": "gepa",
                "status": "awaiting_measured_baseline",
                "automatically_applied": False,
            }
        try:
            module = load_repository_module("retort_engine.evolution_optimizer")
            return module.optimize_protocol(
                Path(path), seed={"plan": plan["public_body"]}, reflection_lm=reflect
            )
        except RECOVERABLE_ERRORS as exc:
            # RSI is auxiliary: retain the original plan and expose the failed
            # experiment at approval, without publishing an unmeasured proposal.
            return {
                "engine": "gepa",
                "status": "experiment_failed",
                "error_type": type(exc).__name__,
                "automatically_applied": False,
            }

    def dispatch(self, state):
        from modstore_server.retort_customer_feedback import check_dispatch
        from modstore_server.retort_github_workspace import begin_dispatch

        check_dispatch(self.request_id, state)
        return begin_dispatch(self.request_id, state)

    def collect(self, state):
        from modstore_server.retort_github_workspace import collect_execution

        return collect_execution(self.request_id)

    def verify(self, state):
        from modstore_server.retort_github_workspace import verify_execution

        return verify_execution(self.request_id, state)

    def delivery(self, state):
        from modstore_server.retort_delivery import collect_delivery

        return collect_delivery(state)

    def impact(self, state):
        from modstore_server.retort_customer_feedback import read_impact

        return read_impact(self.request_id, state["delivery"])

    def remember(self, state):
        knowledge = {
            "request_id": self.request_id,
            "protocol": state["protocol"],
            "verification": state["verification"],
            "delivery": state["delivery"],
            "approval": state["approval"],
            "plan": state["plan"],
            "optimization": state["optimization"],
            "evidence_verified": True,
            "scope": "accepted_shared_host_delivery",
        }
        if state.get("impact"):
            knowledge["customer_impact"] = state["impact"]
        with get_session_factory()() as db:
            row = db.get(RetortEvolutionRun, self.request_id)
            row.knowledge_json = json_dumps(knowledge)
            db.commit()
        return {"request_id": self.request_id, "recorded": True, "evidence_verified": True}


def advance_run(request_id, *, approval=None, ports=None):
    from langgraph.types import Command

    workflow = load_repository_module("retort_engine.evolution_workflow")
    with run_lock(request_id), checkpoint() as saver:
        with get_session_factory()() as db:
            row = db.get(RetortEvolutionRun, request_id)
            if row is None:
                raise ValueError("改进任务不存在")
            if row.status in TERMINAL:
                if approval is not None:
                    raise ValueError("该任务已经结束，不能重复批准")
                return json_loads(row.snapshot_json, {})
            protocol = json_loads(row.protocol_json, {})
            customer_feedback = bool(json_loads(row.effects_json, {}).get("customer_feedback"))
        graph = workflow.build_evolution_graph(ports or ComponentPorts(request_id), saver)
        config = {"configurable": {"thread_id": request_id}}
        before = graph.get_state(config)
        pauses = [i.value for task in before.tasks for i in task.interrupts]
        if approval is not None:
            if (
                len(pauses) != 1
                or pauses[0].get("kind") not in {"dispatch_approval", "acceptance"}
                or approval.get("digest") != pauses[0].get("digest")
            ):
                raise ValueError("审批内容已变化，请刷新证据后重新审阅")
            value = Command(resume=approval)
        elif pauses and pauses[0].get("kind") in {"execution", "delivery", "customer_impact"}:
            value = Command(resume={"poll": True})
        elif pauses:
            snapshot = _snapshot(before)
            _project(request_id, snapshot)
            return snapshot
        else:
            value = (
                {"protocol": protocol, "has_customer_feedback": customer_feedback}
                if not before.values
                else None
            )
        try:
            graph.invoke(value, config, durability="sync")
            snapshot = _snapshot(graph.get_state(config))
            _project(request_id, snapshot)
            return snapshot
        except RECOVERABLE_ERRORS as exc:
            snapshot = _snapshot(graph.get_state(config))
            from httpx import HTTPError

            error = (
                "连接状态未确认，保留任务等待核对"
                if isinstance(exc, HTTPError)
                else str(exc)[:1000]
            )
            _project(request_id, snapshot, error)
            raise


def _snapshot(state):
    return {**state.values, "pending": [i.value for task in state.tasks for i in task.interrupts]}


def _project(request_id, snapshot, error=""):
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, request_id)
        row.snapshot_json = json_dumps(snapshot)
        row.status, row.error = snapshot.get("status", "created"), error
        row.updated_at = datetime.now(UTC)
        db.commit()


def reflect(messages, *, max_tokens=4096):
    from modstore_server.runtime_async import run_coro_sync
    from modstore_server.services.llm import (
        chat_dispatch_via_platform_only,
        resolve_platform_bench_llm,
    )

    provider, model = resolve_platform_bench_llm()
    if not provider or not model:
        raise ValueError("RSI 辅助实验尚未绑定平台模型")
    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]
    return run_coro_sync(
        chat_dispatch_via_platform_only(provider, model, messages, max_tokens=max_tokens)
    )


def tick():
    if not os.environ.get("MODSTORE_RETORT_CHECKPOINT_DSN"):
        return {"processed": 0, "reason": "not_configured"}
    with get_session_factory()() as db:
        ids = [
            r.id
            for r in db.query(RetortEvolutionRun)
            .filter(RetortEvolutionRun.status.notin_(TERMINAL))
            .order_by(RetortEvolutionRun.updated_at)
            .limit(10)
        ]
    errors = []
    for request_id in ids:
        try:
            advance_run(request_id)
        except RECOVERABLE_ERRORS as exc:
            errors.append({"request_id": request_id, "error": type(exc).__name__})
    return {"processed": len(ids), "errors": errors}


def accepted_knowledge(limit=8):
    with get_session_factory()() as db:
        records = [
            json_loads(r.knowledge_json, {})
            for r in db.query(RetortEvolutionRun)
            .filter_by(status="completed")
            .order_by(RetortEvolutionRun.updated_at.desc())
            .limit(limit)
            if json_loads(r.knowledge_json, {}).get("evidence_verified") is True
            and json_loads(r.knowledge_json, {}).get("delivery", {}).get("status")
            == "deployment_verified"
        ]
    return [
        {
            "request_id": r["request_id"],
            "goal": r["protocol"]["goal"],
            "criteria": r["protocol"]["criterion_ids"],
            "verification": r["verification"],
            "delivery": r["delivery"],
            "sources": r["protocol"]["references"],
            "scope": r["scope"],
        }
        for r in records
    ]
