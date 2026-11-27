"""Controlled SDK transport and ledger doubles shared by runtime boundary scenarios."""

from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator import run_lifecycle
from app.application.agent_orchestrator.run_models import AgentRun, ToolCall
from app.application.agent_runtime import xiaox_runtime as runtime
from app.domain.task_lifecycle.agent_runtime_contract import (
    GOAL_PROTOCOL,
    build_goal_contract,
    canonical_digest,
    goal_answers,
    goal_evidence_snapshot,
    validate_goal_review,
    validate_runtime_goal,
)
from app.infrastructure.xiaox import XiaoxTransportConfig
from app.infrastructure.xiaox.binding import (
    XiaoxBinding,
    XiaoxBindingError,
    XiaoxGrant,
)
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.xiaox_goal_review import verifier as verifier


class Store:
    """In-process substitute only for the durable, separately tested bridge API."""

    def __init__(self, *, rows=None, metadata=None):
        self.run = AgentRun(user_id="71", message="整理销售数据", run_id="run-runtime")
        self.rows = copy.deepcopy(rows or [])
        self.log = []
        self.auth_error = None
        self.child = None
        self.review_kind = "read"
        self.review_missing = False
        self.reviews = []
        contract = build_goal_contract(self.run)
        self.run.metadata.update(
            runtime_goal_contract=contract, runtime_goal_digest=contract["digest"]
        )
        self.repository = SimpleNamespace(get=self.get_run)
        if metadata is not None:
            self.run.metadata["xiaox_runtime"] = copy.deepcopy(metadata)

    def get_run(self, run_id):
        return copy.deepcopy(self.run if run_id == self.run.run_id else self.child)

    def get(self, run_id):
        assert run_id == self.run.run_id
        if "xiaox_runtime" not in self.run.metadata:
            raise XiaoxBindingError("binding_missing", "no binding yet")
        return XiaoxBinding(copy.deepcopy(self.run))

    def create(self, run_id, *, runtime_config, **_options):
        self.log.append("create")
        if self.auth_error:
            raise XiaoxBindingError(self.auth_error, "authority unavailable")
        old = self.run.metadata.get("xiaox_runtime", {})
        if old.get("coordinator_active"):
            raise XiaoxBindingError("binding_conflict", "another coordinator owns the run")
        if old.get("runtime_config") and old["runtime_config"] != runtime_config:
            raise XiaoxBindingError("runtime_changed", "pinned route changed")
        self.run.metadata["xiaox_runtime"] = {
            **old,
            "generation": old.get("generation", 0) + 1,
            "coordinator_active": True,
            "runtime_config": runtime_config,
            "revoked": False,
        }
        return XiaoxGrant(self.get(run_id), "mcp-token", "model-token")

    def authenticate(self, token, audience="mcp"):
        assert (token, audience) == ("model-token", "model")
        if self.auth_error:
            raise XiaoxBindingError(self.auth_error, "authority revoked")
        return self.get(self.run.run_id)

    def record_thread(self, run_id, thread_id, *, generation=None):
        assert generation == self.run.metadata["xiaox_runtime"]["generation"]
        self.run.metadata["xiaox_runtime"]["thread_id"] = thread_id
        return self.get(run_id)

    def _validate_current(self, run, metadata, generation):
        assert metadata["generation"] == generation
        validate_runtime_goal(run)
        if self.auth_error:
            raise XiaoxBindingError(self.auth_error, "authority revoked")

    def update(self, run_id, fn):
        current = copy.deepcopy(self.run)
        fn(current, current.metadata["xiaox_runtime"])
        self.run = current
        return self.get(run_id)

    def receipt_snapshot(self, _run_id):
        rows = copy.deepcopy(self.rows)
        if "xiaox_runtime" in self.run.metadata:
            self.run.metadata["xiaox_runtime"]["calls"] = {
                row["call_id"]: {key: value for key, value in row.items() if key != "call_id"}
                for row in rows
            }
        return rows

    def close(self, run_id, reason="cancelled", *, generation=None, release_coordinator=True):
        self.log.append("revoke")
        metadata = self.run.metadata["xiaox_runtime"]
        if generation == metadata["generation"]:
            metadata.update(revoked=True, close_reason=reason)
            if release_coordinator:
                metadata["coordinator_active"] = False
        return self.get(run_id)


def event(method, payload=None, *, thread_id="thread-one", turn_id="turn-one", item_id=None):
    return {
        "method": method,
        "payload": payload or {},
        "thread_id": thread_id,
        "turn_id": turn_id,
        "item_id": item_id,
    }


def completed(text="已整理"):
    return [
        event("turn/started", {"turn": {"id": "turn-one", "status": "inProgress"}}),
        event(
            "item/completed", {"item": {"id": "message-one", "type": "agentMessage", "text": text}}
        ),
        event("turn/completed", {"turn": {"id": "turn-one", "status": "completed"}}),
    ]


class Transport:
    def __init__(self, store, events=None, *, hang=False, error=None):
        self.store = store
        self.events = completed() if events is None else events
        self.hang = hang
        self.error = error
        self.inputs = []
        self.schemas = []
        self.started = []
        self.initial_history = []
        self.resumed = []
        self.active = asyncio.Event()
        self.config = None

    def factory(self, config):
        self.config = config
        return self

    async def __aenter__(self):
        self.store.log.append("enter")
        return self

    async def __aexit__(self, *_exc):
        self.store.log.append("exit")

    async def start_thread(self, *, developer_instructions, history=None):
        self.started.append(developer_instructions)
        self.initial_history.extend(history or [])
        return "thread-one"

    async def resume_thread(self, thread_id, *, developer_instructions):
        self.resumed.append(thread_id)
        return thread_id

    async def stream_turn(self, text, *, goal_feedback=None, output_schema=None):
        self.inputs.append(text if goal_feedback is None else goal_feedback)
        self.schemas.append(output_schema)
        self.active.set()
        for item in self.events:
            yield item
        if self.error:
            raise self.error
        if self.hang:
            await asyncio.Event().wait()

    async def interrupt(self):
        self.store.log.append("interrupt")
        assert self.store.run.metadata["xiaox_runtime"]["revoked"] is True


@pytest.fixture
def setup_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(run_lifecycle, "continuation_conversation_error", lambda *_args: "")
    config = XiaoxTransportConfig(
        runtime_root=tmp_path.resolve(),
        scope_id="must-be-replaced",
        model="qualified-model",
        provider_url="http://127.0.0.1:41111/v1",
        provider_token="unused-placeholder",
        mcp_url="http://127.0.0.1:41111/mcp",
        mcp_token="unused-placeholder",
        context_window=32000,
        turn_timeout_seconds=30,
    )

    def review(
        binding,
        _config,
        *,
        rows,
        output,
        consume_format_retry,
        plan_delivery=None,
        on_progress=None,
        replay_response=None,
    ):
        store = stores[binding.run_id]
        if plan_delivery is not None:
            output = plan_delivery.output
        contract = binding.run.metadata["runtime_goal_contract"]
        snapshot = goal_evidence_snapshot(contract, rows, output, goal_answers(binding.run))
        ids = [
            row["evidence_id"]
            for row in snapshot["evidence"]
            if row["state"] == "completed"
            and row["receipt"].get("verified")
            and row["receipt"].get("success")
        ]
        raw = (
            store.reviews.pop(0)
            if store.reviews
            else {
                "goals": [
                    {
                        "goal_id": "original",
                        "source_id": "request",
                        "source": binding.run.message,
                        "kind": store.review_kind,
                        "status": "unmet" if store.review_missing else "satisfied",
                        "evidence_ids": ["response"] if store.review_kind == "reply" else ids,
                        "reason": "Controlled semantic fixture; host validates original receipts",
                    }
                ],
                "violations": [],
                "uncovered_sources": [],
                "feedback": "继续核对原始目标",
            }
        )
        if plan_delivery and plan_delivery.proof:
            raw["plan_content"] = plan_delivery.proof["kind"]
        reviewed, errors = validate_goal_review(raw, contract, snapshot, output)
        accepted = not (
            errors
            or reviewed["violations"]
            or reviewed["uncovered_sources"]
            or any(goal["status"] == "unmet" for goal in reviewed["goals"])
        )
        report = {
            "protocol": GOAL_PROTOCOL,
            "verifier_version": 1,
            "goal_digest": contract["digest"],
            "evidence_digest": snapshot["digest"],
            "response_digest": canonical_digest(output),
            "review": reviewed,
            "status": "verified" if accepted else "needs_work",
            "accepted": accepted,
            "feedback": raw["feedback"],
            **({"plan_delivery": plan_delivery.proof} if plan_delivery else {}),
        }
        return {**report, "report_digest": canonical_digest(report)}

    stores = {}
    monkeypatch.setattr("app.application.agent_runtime.goal_verifier.verify_runtime_goal", review)

    def invoke(store, transport, **kwargs):
        stores[store.run.run_id] = store
        if kwargs.get("completion_mode") == "reply":
            store.review_kind = "reply"
        return runtime.run_xiaox_agent(
            run_id=store.run.run_id,
            task=store.run.message,
            system_prompt="可信员工说明",
            config=config,
            binding_store=store,
            transport_factory=transport.factory,
            runtime_config={"provider_id": "qualified-provider", "route_identity": "route-v1"},
            **kwargs,
        )

    return invoke, config


def receipt(
    *,
    status="completed",
    verified=True,
    success=True,
    child_run_id="run-child",
    child_task_id="task-child",
):
    call = ToolCall(
        step_id="step-child",
        node_id="node-child",
        tool_id="sales",
        action="query",
        status="completed",
        output={"success": True, "row_count": 3},
        call_id="call-child",
    )
    return {
        "call_id": "model-call",
        "tool_id": "sales",
        "action": "query",
        "params": {},
        "state": status,
        "read_only": True,
        "fingerprint": canonical_digest({"tool_id": "sales", "action": "query", "params": {}}),
        "child_task_id": child_task_id,
        "child_run_id": child_run_id,
        "receipt": {
            "run_id": child_run_id,
            "task_id": child_task_id,
            "status": status,
            "verified": verified,
            "success": success,
            "tool_calls": [call.to_dict()] if status == "completed" else [],
        },
    }


class Bridge:
    """Records only the public MCP entry calls; no authority is simulated."""

    def __init__(self):
        self.calls = []

    def invoke(self, token, name, arguments):
        self.calls.append((token, name, copy.deepcopy(arguments)))
        if name == "capability_search":
            if not arguments["query"] and arguments["offset"] == 0:
                return {
                    "capabilities": [
                        {"tool_id": "excel_analysis", "action": "structure", "read_only": True}
                    ],
                    "next_offset": 30,
                }
            return {
                "capabilities": [{"tool_id": "employee", "action": "execute", "read_only": False}]
            }
        if name == "capability_describe":
            return {"capability": {"schema_digest": "digest-live"}}
        return {"success": True, "verified": False, "status": "pending_approval"}
