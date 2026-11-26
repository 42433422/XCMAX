"""In-process fakes shared by the Codex runtime boundary tests."""

from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace

from app.application.agent_orchestrator.run_models import AgentRun
from app.domain.task_lifecycle.agent_runtime_contract import (
    build_goal_contract,
    validate_runtime_goal,
)
from app.infrastructure.codex.binding import CodexBinding, CodexBindingError, CodexGrant

__all__ = ["Store", "Transport", "completed", "event"]


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
            self.run.metadata["codex_runtime"] = copy.deepcopy(metadata)

    def get_run(self, run_id):
        return copy.deepcopy(self.run if run_id == self.run.run_id else self.child)

    def get(self, run_id):
        assert run_id == self.run.run_id
        if "codex_runtime" not in self.run.metadata:
            raise CodexBindingError("binding_missing", "no binding yet")
        return CodexBinding(copy.deepcopy(self.run))

    def create(self, run_id, *, runtime_config, **_options):
        self.log.append("create")
        if self.auth_error:
            raise CodexBindingError(self.auth_error, "authority unavailable")
        old = self.run.metadata.get("codex_runtime", {})
        if old.get("coordinator_active"):
            raise CodexBindingError("binding_conflict", "another coordinator owns the run")
        if old.get("runtime_config") and old["runtime_config"] != runtime_config:
            raise CodexBindingError("runtime_changed", "pinned route changed")
        self.run.metadata["codex_runtime"] = {
            **old,
            "generation": old.get("generation", 0) + 1,
            "coordinator_active": True,
            "runtime_config": runtime_config,
            "revoked": False,
        }
        return CodexGrant(self.get(run_id), "mcp-token", "model-token")

    def authenticate(self, token, audience="mcp"):
        assert (token, audience) == ("model-token", "model")
        if self.auth_error:
            raise CodexBindingError(self.auth_error, "authority revoked")
        return self.get(self.run.run_id)

    def record_thread(self, run_id, thread_id, *, generation=None):
        assert generation == self.run.metadata["codex_runtime"]["generation"]
        self.run.metadata["codex_runtime"]["thread_id"] = thread_id
        return self.get(run_id)

    def _validate_current(self, run, metadata, generation):
        assert metadata["generation"] == generation
        validate_runtime_goal(run)
        if self.auth_error:
            raise CodexBindingError(self.auth_error, "authority revoked")

    def update(self, run_id, fn):
        current = copy.deepcopy(self.run)
        fn(current, current.metadata["codex_runtime"])
        self.run = current
        return self.get(run_id)

    def receipt_snapshot(self, _run_id):
        return copy.deepcopy(self.rows)

    def close(self, run_id, reason="cancelled", *, generation=None, release_coordinator=True):
        self.log.append("revoke")
        metadata = self.run.metadata["codex_runtime"]
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
        self.started = []
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

    async def start_thread(self, *, developer_instructions):
        self.started.append(developer_instructions)
        return "thread-one"

    async def resume_thread(self, thread_id, *, developer_instructions):
        self.resumed.append(thread_id)
        return thread_id

    async def stream_turn(self, text, *, goal_feedback=None):
        self.inputs.append(text if goal_feedback is None else goal_feedback)
        self.active.set()
        for item in self.events:
            yield item
        if self.error:
            raise self.error
        if self.hang:
            await asyncio.Event().wait()

    async def interrupt(self):
        self.store.log.append("interrupt")
        assert self.store.run.metadata["codex_runtime"]["revoked"] is True
