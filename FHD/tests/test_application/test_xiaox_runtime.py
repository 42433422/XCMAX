"""Runtime/ledger boundary tests: model events cannot forge business outcomes."""

from __future__ import annotations

import asyncio
import copy
import json
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
from tests.test_application.test_xiaox_goal_verifier import goal, response, review
from tests.test_application.test_xiaox_goal_verifier import verifier as verifier


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
        return copy.deepcopy(self.rows)

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

    def review(binding, _config, *, rows, output, consume_format_retry, plan_delivery=None):
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
        accepted = not errors and not any(goal["status"] == "unmet" for goal in reviewed["goals"])
        report = {
            "protocol": GOAL_PROTOCOL,
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


@pytest.mark.parametrize("history_revision", [3, 2])
def test_native_history_requires_frozen_sql_snapshot(setup_runtime, history_revision):
    invoke, _ = setup_runtime
    store = Store()
    summary = {"role": "user", "content": "retained summary evidence"}
    prior = [
        {"role": "user", "content": "prior user preference"},
        {"role": "assistant", "content": "previous published reply"},
    ]
    history = [summary, *prior]
    store.run.metadata.update(
        _xiaox_history=history,
        runtime_context={
            "session_id": "tenant-owned-session",
            "_conversation_revision": 3,
            "_chat_history_revision": history_revision,
            "_chat_history_source": "sql",
            "_chat_history_ids": [None, 17, 18],
            "_chat_history_messages": history,
        },
    )
    contract = build_goal_contract(store.run)
    store.run.metadata.update(
        runtime_goal_contract=contract, runtime_goal_digest=contract["digest"]
    )
    transport = Transport(store)
    result = asyncio.run(invoke(store, transport, completion_mode="reply"))
    assert result["ok"] is True
    native = history_revision == 3
    assert transport.initial_history == (prior if native else [])
    assert summary["content"] in transport.inputs[0]
    assert all((row["content"] in transport.inputs[0]) is not native for row in prior)


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


def test_missing_runtime_component_is_identified_before_model_start(setup_runtime, monkeypatch):
    from app.application.agent_runtime import goal_admission

    def unavailable(*args, **kwargs):
        raise ImportError("private installation path", name="internal_component")

    monkeypatch.setattr(goal_admission, "prepare_runtime_goal", unavailable)
    invoke, _ = setup_runtime
    store = Store(rows=[])
    del store.run.metadata["runtime_goal_contract"], store.run.metadata["runtime_goal_digest"]
    transport = Transport(store)
    result = asyncio.run(invoke(store, transport, completion_mode="reply"))
    assert result["failure_kind"] == "runtime_component_unavailable"
    assert "private installation path" not in result["failure_reason"]
    assert not transport.started and not result["ok"]


def test_model_call_budget_exhaustion_is_a_distinguishable_stop_reason(setup_runtime):
    invoke, _ = setup_runtime
    store = Store(
        rows=[receipt()],
        metadata={
            "model_call_limit": {
                "reason": "model_call_budget_exhausted",
                "max_model_calls": 24,
                "used_model_calls": 24,
            }
        },
    )
    result = asyncio.run(invoke(store, Transport(store, completed("已全部完成"))))
    assert result["exit_status"] == "model_call_budget_exhausted"
    assert result["execution_state"] == "failed"
    assert result["failure_kind"] == "model_call_budget_exhausted"
    assert result["failure_stage"] == "model"
    assert result["business_completed"] is False
    # A spent budget is not a business fact: confirmed receipts stay queryable.
    assert result["verified_operations"] is True


def test_reply_is_completed_without_claiming_business_success(setup_runtime):
    invoke, _ = setup_runtime
    store = Store()
    transport = Transport(store, completed("收到"))
    result = asyncio.run(invoke(store, transport, completion_mode="reply"))
    assert result["ok"] is True and result["business_completed"] is False
    assert result["output"] == "收到"
    assert store.run.status == "completed"
    assert result["tool_calls"] == [] and store.run.tool_calls == []
    assert transport.config.scope_id != "must-be-replaced"
    assert transport.config.provider_token == "model-token"
    assert transport.config.mcp_token == "mcp-token"
    assert result["legacy_fallback_allowed"] is False
    assert [event.event_type for event in store.run.events].count("runtime.xiaox.finished") == 1
    assert "xiaox_result" in store.run.final_output
    assert "codex_result" not in store.run.final_output
    assert store.run.metadata["xiaox_runtime"]["coordinator_active"] is False


def test_reply_delivers_final_answer_without_commentary(setup_runtime):
    invoke, _ = setup_runtime
    store = Store()
    events = completed("第一天游故宫，第二天游颐和园。")
    events[1]["payload"]["item"]["phase"] = "final_answer"
    events[1:1] = [
        event("item/agentMessage/delta", {"delta": "我先检索"}, item_id="progress"),
        event(
            "item/completed",
            {
                "item": {
                    "id": "progress",
                    "type": "agentMessage",
                    "phase": "commentary",
                    "text": "我先检索当前账号能力。",
                }
            },
        ),
    ]
    public_events = []
    result = asyncio.run(
        invoke(
            store, Transport(store, events), completion_mode="reply", on_event=public_events.append
        )
    )
    assert "我先检索" not in repr(public_events)
    assert "第一天游故宫" not in repr(public_events)
    assert any(event["method"] == "turn/completed" for event in public_events)
    assert result["ok"] is True
    assert result["output"] == "第一天游故宫，第二天游颐和园。"
    assert result["session_messages"][-1]["content"] == result["output"]


def test_email_revision_delivers_only_the_reviewed_english_draft(setup_runtime):
    invoke, _ = setup_runtime
    store = Store()
    request = "再正式一些，并补充工作交接安排。"
    previous = (
        "Subject: Annual Leave Request\n\nDear Manager, I would like to request annual leave."
    )
    approved = (
        "Subject: Annual Leave Request\n\nDear Manager,\n\n"
        "I am writing to formally request annual leave. Before my departure, I will brief "
        "my deputy on open items and share the handover checklist.\n\nKind regards"
    )
    private = "邮件修订已完成，核验意见确认无需工具调用。"
    feedback = "沿用英文并删除内部核验说明。"
    store.run.message = request
    store.run.metadata["_xiaox_history"] = [
        {"role": "user", "content": "请用英文重写请假邮件。"},
        {"role": "assistant", "content": previous},
    ]
    contract = build_goal_contract(store.run)
    store.run.metadata.update(
        runtime_goal_contract=contract, runtime_goal_digest=contract["digest"]
    )
    store.reviews = [
        review(
            goal(request, kind="reply", status="unmet", evidence_ids=["response"]),
            feedback=feedback,
        ),
        review(goal(request, kind="reply", evidence_ids=["response"])),
    ]

    class RevisionTransport(Transport):
        async def stream_turn(self, text, *, goal_feedback=None, output_schema=None):
            if goal_feedback is None:
                assert "Subject: Annual Leave Request" in text and request in text
            else:
                assert text is None and goal_feedback == feedback
                self.events = completed(approved)
            async for item in super().stream_turn(text, goal_feedback=goal_feedback):
                yield item

    public_events = []
    transport = RevisionTransport(store, completed(private))
    result = asyncio.run(
        invoke(store, transport, completion_mode="reply", on_event=public_events.append)
    )
    assert len(transport.started) == 1 and len(transport.inputs) == 2
    assert private not in repr(public_events) and feedback not in repr(public_events)
    assert result["reply_completed"] and result["output"] == approved
    assert result["session_messages"] == [
        {"role": "user", "content": request},
        {"role": "assistant", "content": approved},
    ]


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


def test_write_goal_without_any_action_requires_business_action(setup_runtime):
    invoke, _ = setup_runtime
    store = Store()
    store.review_kind = "write"
    feedback = "原任务要求的写入尚无任何业务回执。"
    store.reviews = [
        review(
            goal(store.run.message, kind="write", status="unmet", evidence_ids=[]),
            feedback=feedback,
        )
    ] * 3
    transport = Transport(store, completed("已按要求改好工作簿。"))
    public_events = []
    result = asyncio.run(
        invoke(
            store,
            transport,
            completion_mode="business",
            on_event=public_events.append,
            tool_bridge=Bridge(),
        )
    )
    assert len(transport.inputs) == 3
    assert transport.inputs[1:] == [feedback, feedback]
    assert transport.schemas[0] is None and all(schema for schema in transport.schemas[1:])
    assert transport.schemas[1]["properties"]["capability"]["enum"] == ["employee.execute"]
    assert result["ok"] is False and result["business_completed"] is False
    assert result["failure_kind"] == "business_action_required"
    assert store.run.status == "blocked"
    assert "已完成" not in repr(public_events)


@pytest.mark.parametrize("previous_read", [False, True])
def test_write_goal_proposal_is_submitted_once_through_mcp_entry(setup_runtime, previous_read):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt()] if previous_read else [])
    store.review_kind = "write"
    store.reviews = [
        review(
            goal(store.run.message, kind="write", status="unmet", evidence_ids=[]),
            feedback="需要实际写入。",
        )
    ] * 3
    bridge = Bridge()
    proposal = '{"capability": "employee.execute", "params": {"employee_id": "x"}}'
    transport = Transport(store, completed(proposal))
    result = asyncio.run(invoke(store, transport, completion_mode="business", tool_bridge=bridge))
    names = [name for _, name, _ in bridge.calls]
    assert names == [
        "capability_search",
        "capability_search",
        "capability_describe",
        "execute_action",
    ]
    assert bridge.calls[1][2]["offset"] == 30
    _, _, execute_args = bridge.calls[-1]
    assert (execute_args["tool_id"], execute_args["action"]) == ("employee", "execute")
    assert execute_args["schema_digest"] == "digest-live"
    assert execute_args["call_id"].startswith("host-")
    assert execute_args["params"] == {"employee_id": "x"}
    events = [event.event_type for event in store.run.events]
    assert events.count("runtime.action.proposed") == 1
    assert result["ok"] is False
    # Proposals are internal: they must never become the public reply.
    assert "tool_id" not in str(result.get("output") or "")


@pytest.mark.parametrize(
    ("state", "read_only", "verified"),
    [
        ("completed", False, True),
        ("completed", None, True),
        ("completed", True, False),
        ("unknown", True, False),
        ("waiting_approval", False, False),
        ("failed", True, False),
        ("blocked", False, False),
    ],
)
def test_write_recovery_stays_blocked_without_a_verified_read(state, read_only, verified):
    row = receipt(status=state, verified=verified, success=state == "completed")
    assert runtime._has_blocking_receipt([{**row, "read_only": read_only}])


@pytest.mark.parametrize(
    "schema_violation",
    [None, {"path": "$.params.input", "validator": "required", "missing": ["plan"]}],
)
def test_denied_proposal_returns_error_and_real_write_capabilities(setup_runtime, schema_violation):
    invoke, _ = setup_runtime
    store = Store()
    store.review_kind = "write"
    store.reviews = [
        review(
            goal(store.run.message, kind="write", status="unmet", evidence_ids=[]),
            feedback="需要实际写入。",
        )
    ] * 3

    class DenialBridge(Bridge):
        def invoke(self, token, name, arguments):
            result = super().invoke(token, name, arguments)
            if name == "execute_action":
                return {
                    "status": "not_started",
                    "error_code": "schema_validation_failed",
                    "schema_violation": schema_violation,
                }
            return result

    bridge = DenialBridge()
    capability = "employee.execute" if schema_violation else "employee.execute.run_excel_job"
    proposal = json.dumps({"capability": capability, "params": {}})
    transport = Transport(store, completed(proposal))
    result = asyncio.run(invoke(store, transport, completion_mode="business", tool_bridge=bridge))
    methods = {name for _, name, _ in bridge.calls}
    error = {"status": "not_started", "error_code": "proposal_capability_unavailable"}
    if schema_violation:
        assert methods == {"capability_search", "capability_describe", "execute_action"}
        error.update(error_code="schema_validation_failed", schema_violation=schema_violation)
    else:
        assert methods == {"capability_search"}
    assert transport.inputs[1] == "需要实际写入。"
    assert json.loads(transport.inputs[2]) == {
        "feedback": "需要实际写入。",
        "proposal_error": error,
    }
    capabilities = transport.schemas[2]["properties"]["capability"]["enum"]
    assert "employee.execute" in capabilities and "excel_analysis.structure" not in capabilities
    # 被拒绝的提案不得被当作已提交，也不得据此发布“已完成”。
    assert "tool_id" not in str(result.get("output") or "")
    assert result["ok"] is False and store.run.status == "blocked"


@pytest.mark.parametrize("mode", ["execute", "plan"])
def test_proposal_preserves_registered_action_arguments(setup_runtime, mode):
    invoke, _ = setup_runtime
    store = Store()
    store.run.metadata["runtime_execution_mode"] = mode
    store.review_kind = "write"
    store.reviews = [
        review(goal(store.run.message, kind="write", status="unmet", evidence_ids=[]))
    ] * 3
    bridge = Bridge()
    params = {
        "employee_id": "registered-employee",
        "task": store.run.message,
        "input": {"upload_id": "owned-upload"},
    }
    transport = Transport(
        store, completed(json.dumps({"capability": "employee.execute", "params": params}))
    )
    asyncio.run(invoke(store, transport, completion_mode="business", tool_bridge=bridge))
    if mode == "plan":
        assert not bridge.calls and transport.schemas == [None] * 3
        return
    searches = [args for _, name, args in bridge.calls if name == "capability_search"]
    assert [(args["query"], args["offset"]) for args in searches] == [("", 0), ("", 30)]
    assert transport.schemas[1]["required"] == ["capability", "params"]
    (execute,) = [args for _, name, args in bridge.calls if name == "execute_action"]
    assert (execute["tool_id"], execute["action"], execute["schema_digest"]) == (
        "employee",
        "execute",
        "digest-live",
    )
    assert execute["params"] == params


def test_proposal_repair_uses_only_the_selected_catalog_contract():
    from jsonschema import Draft202012Validator

    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

    assert (spec := get_tool_action_spec("employee", "execute")) is not None
    options = {
        "employee.execute": ("employee", "execute"),
        "products.create": ("products", "create"),
    }
    calls = []

    def invoke(token, method, params):
        calls.append((token, method, params))
        return {"capability": {"input_schema": spec.input_schema}}

    bridge = SimpleNamespace(invoke=invoke)
    denial = {"tool_id": "employee", "action": "execute", "schema_violation": {"path": "$"}}
    schema = runtime._proposal_contract(bridge, "token", options, denial)
    assert calls == [("token", "capability_describe", {"tool_id": "employee", "action": "execute"})]
    assert schema["then"]["properties"]["params"] == spec.input_schema
    validate = Draft202012Validator(schema).is_valid
    assert not validate({"capability": "employee.execute", "params": {"input": {}}})
    assert validate({"capability": "products.create", "params": {}})
    assert not validate({"capability": "employee.execute", "workbook": {}})
    assert not validate({"capability": "products.delete", "params": {}})


def test_write_goal_feedback_surfaces_definite_write_failure(setup_runtime):
    invoke, _ = setup_runtime
    operation = {"tool_id": "employee", "action": "execute", "params": {}}
    failed = receipt(status="failed", verified=False, success=False)
    failed.update(**operation, read_only=False, fingerprint=canonical_digest(operation))
    failed["receipt"].update(retryable=True, message="非法 Excel 表格名称：'销售明细表'")
    store = Store(rows=[failed])
    store.review_kind = "write"
    store.reviews = [
        review(
            goal(store.run.message, kind="write", status="unmet", evidence_ids=[]),
            feedback="需要写入。",
        )
    ] * 2
    transport = Transport(store, completed("已改好。"))
    result = asyncio.run(invoke(store, transport, completion_mode="business", tool_bridge=Bridge()))
    assert "非法 Excel 表格名称" in transport.inputs[1]
    assert "上次业务动作明确失败" in transport.inputs[1]
    assert transport.schemas[1] is None
    assert result["ok"] is False


def test_model_completion_without_receipt_cannot_complete_business(setup_runtime):
    invoke, _ = setup_runtime
    store = Store()
    result = asyncio.run(invoke(store, Transport(store, completed("已出库并记账成功"))))
    assert result["ok"] is False and result["business_completed"] is False
    assert result["exit_status"] == "goal_verification_required"
    assert store.run.status == "blocked"
    assert result["failure_stage"] == "goal_verification"
    assert result["failure_kind"] == "goal_verification_required"
    assert result["failure_reason"] == "继续核对原始目标"
    assert store.run.metadata["runtime_failure_kind"] == result["failure_kind"]


@pytest.mark.parametrize("text", ["", "   \n"])
def test_empty_model_turn_is_not_a_completed_reply(setup_runtime, text):
    invoke, _ = setup_runtime
    store = Store()
    result = asyncio.run(invoke(store, Transport(store, completed(text)), completion_mode="reply"))
    assert result["ok"] is False and result["reply_completed"] is False
    assert result["exit_status"] == "goal_verification_required"
    assert store.run.status == "blocked"


@pytest.mark.parametrize("state", ["waiting_user", "waiting_approval", "pending_approval"])
def test_approval_wait_survives_turn_completion(setup_runtime, state):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt(status=state, verified=False, success=False)])
    result = asyncio.run(invoke(store, Transport(store)))
    assert result["ok"] is False and result["pending_approval"] is True
    assert store.run.status == "waiting_user"
    assert store.run.metadata["xiaox_runtime"]["coordinator_active"] is False


def test_verified_child_receipts_are_projected_not_fabricated(setup_runtime):
    invoke, _ = setup_runtime
    row = receipt()
    digest = "a" * 64
    file = {
        "artifact_id": "workbook",
        "artifact_type": "file",
        "name": "明细.xlsx",
        "uri": "/api/agent/runs/run-child/artifacts/workbook",
        "metadata": {"sha256": digest},
    }
    row["receipt"].update(
        artifacts=[
            file,
            {**file, "artifact_id": "unverified"},
            {**file, "artifact_type": "file_analysis"},
            {**file, "metadata": {"sha256": "b" * 64}},
        ],
        verification={
            "accepted": True,
            "steps": [
                {
                    "checks": [
                        {
                            "source": "run_artifact",
                            "status": "passed",
                            "evidence": {
                                "run_id": "run-child",
                                "artifact_id": "workbook",
                                "sha256": digest,
                            },
                        }
                    ]
                }
            ],
        },
    )
    store = Store(rows=[row, {**copy.deepcopy(row), "call_id": "duplicate-model-call"}])
    result = asyncio.run(invoke(store, Transport(store)))
    assert result["ok"] is True and result["business_completed"] is True
    assert len(store.run.tool_calls) == 1
    projected = store.run.tool_calls[0]
    assert projected.output == {"success": True, "row_count": 3}
    assert projected.metadata["child_run_id"] == "run-child"
    assert projected.metadata["child_call_id"] == "call-child"
    assert result["output_artifacts"] == result["artifacts"] == [{**file, "run_id": "run-child"}]
    assert store.run.final_output["xiaox_result"]["output_artifacts"] == result["output_artifacts"]
    assert not store.run.artifacts  # The file is owned by the original child only.
    assert result["run_events"][-1]["event_type"] == "runtime.xiaox.finished"


@pytest.mark.parametrize("same_provenance", [True, False])
def test_legacy_child_receipt_projection_preserves_original_record(same_provenance):
    run = Store().run
    rows = [receipt()]
    runtime._project_child_calls(run, rows)
    previous = run.tool_calls[0]
    previous.call_id = previous.call_id.replace("xiaox_", "codex_", 1)
    previous.metadata["source"] = "codex_child_receipt"
    if not same_provenance:
        previous.metadata["child_run_id"] = "another-child"
    original = copy.deepcopy(previous.to_dict())

    runtime._project_child_calls(run, rows)
    runtime._project_child_calls(run, rows)

    assert run.tool_calls[0].to_dict() == original
    assert len(run.tool_calls) == (1 if same_provenance else 2)
    if not same_provenance:
        assert run.tool_calls[1].metadata["child_run_id"] == "run-child"


def test_verified_operations_do_not_satisfy_a_missing_original_goal(setup_runtime):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt()])
    store.review_missing = True
    store.run.metadata.update(
        runtime_failure_kind="rate_limit", runtime_failure_reason="已恢复的先前限流"
    )
    result = asyncio.run(invoke(store, Transport(store, completed("已全部完成"))))
    assert result["verified_operations"] is True and result["business_completed"] is False
    assert result["exit_status"] == "goal_verification_required"
    assert result["output"] == (
        "本轮未通过完整性核验，原任务与回执已保留，请核对后重试。整体目标尚未核验完成。"
    )
    assert all(message["role"] == "user" for message in result["session_messages"])
    assert store.run.status == "blocked"


def test_verifier_feedback_completes_missing_work_in_same_thread(setup_runtime):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt()])
    store.review_missing = True
    store.run.metadata.update(
        runtime_failure_kind="rate_limit", runtime_failure_reason="已恢复的先前限流"
    )
    original = copy.deepcopy(store.run.metadata["runtime_goal_contract"])

    class CorrectingTransport(Transport):
        async def stream_turn(self, text, *, goal_feedback=None, output_schema=None):
            if not self.inputs:
                assert text and goal_feedback is None
                assert "继续核对原始目标" not in text
            else:
                assert text is None
                assert "继续核对原始目标" in goal_feedback
                # The second SDK turn supplies only the missing read; the first
                # call keeps its original persisted receipt and identity.
                missing = receipt(child_run_id="second-child", child_task_id="second-task")
                missing["call_id"] = "missing-read"
                missing["receipt"]["tool_calls"][0]["call_id"] = "second-child-call"
                store.rows.append(missing)
                store.review_missing = False
            async for item in super().stream_turn(text, goal_feedback=goal_feedback):
                yield item

    transport = CorrectingTransport(store)
    result = asyncio.run(invoke(store, transport))
    assert result["business_completed"] is True and result["ok"] is True, result
    assert len(transport.inputs) == 2 and len(transport.started) == 1
    assert transport.resumed == []
    assert store.run.metadata["runtime_goal_contract"] == original
    assert store.run.metadata["xiaox_runtime"]["generation"] == 1
    assert result["failure_kind"] == ""
    assert "runtime_failure_kind" not in store.run.metadata
    assert [row["call_id"] for row in store.rows] == ["model-call", "missing-read"]
    assert [
        item.data["status"]
        for item in store.run.events
        if item.event_type == "runtime.goal.verified"
    ] == ["needs_work", "verified"]


def test_format_retry_is_shared_across_three_turns_and_sql_restart(
    verifier, trusted_actor, tmp_path
):
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.infrastructure.xiaox.binding import XiaoxBindingStore

    actor = trusted_actor(user_id=71)
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    parent = AgentRun(str(actor.user_id), "请写一段总结", status="running")
    parent.metadata["runtime_context"] = actor.context
    contract = build_goal_contract(parent)
    parent.metadata.update(runtime_goal_contract=contract, runtime_goal_digest=contract["digest"])
    repository.save(parent)
    config = XiaoxTransportConfig(
        runtime_root=tmp_path.resolve(),
        scope_id="fixture",
        model=verifier.config.model,
        provider_url=verifier.config.provider_url,
        provider_token="synthetic-placeholder",
        mcp_url="http://127.0.0.1:41111/mcp",
        mcp_token="synthetic-placeholder",
        context_window=32000,
        auto_compact_token_limit=24000,
        turn_timeout_seconds=30,
    )

    class CandidateTransport(Transport):
        async def stream_turn(self, text, *, goal_feedback=None, output_schema=None):
            assert (text is None) == (goal_feedback is not None)
            self.events = completed(f"候选回复{len(self.inputs) + 1}：尚未完成")
            async for item in super().stream_turn(text, goal_feedback=goal_feedback):
                yield item

    def invoke(store, transport):
        return runtime.run_xiaox_agent(
            run_id=parent.run_id,
            task=parent.message,
            system_prompt="Synthetic test authority",
            config=config,
            binding_store=store,
            transport_factory=transport.factory,
            completion_mode="reply",
            runtime_config={"provider_id": "synthetic", "route_identity": "synthetic-route"},
        )

    unmet = review(goal(parent.message, kind="reply", status="unmet", evidence_ids=["response"]))
    positive = response(review(goal(parent.message, kind="reply", evidence_ids=["response"])))
    verifier.replies = [
        response({}, text="{"),
        response(unmet),
        response(unmet),
        response({}, text="{"),
        positive,
    ]
    reserved = []

    def observe(_request):
        saved = repository.get(parent.run_id)
        reserved.append(saved.metadata["xiaox_runtime"].get("goal_format_retry_used", False))

    verifier.observe_request = observe
    trace = SimpleNamespace(log=[], run=parent)
    first = CandidateTransport(trace)
    result = asyncio.run(invoke(XiaoxBindingStore(repository), first))
    assert result["ok"] is False and len(first.inputs) == 3
    assert len(verifier.requests) == 4 and len(verifier.replies) == 1
    assert reserved == [False, True, True, True], "reservation must precede the second HTTP request"
    saved = repository.get(parent.run_id)
    assert saved.metadata["xiaox_runtime"]["goal_format_retry_used"] is True
    assert saved.metadata["runtime_goal_contract"] == contract
    # An explicit continuation reopens the same original task after a worker
    # restart. A new repository, binding and generation cannot reset its budget.
    saved.status = "waiting_user"
    repository.save(saved)
    reopened = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    resumed = CandidateTransport(trace)
    verifier.replies = [response({}, text="{"), positive]
    again = asyncio.run(invoke(XiaoxBindingStore(reopened), resumed))
    assert again["ok"] is False and resumed.resumed == ["thread-one"]
    assert len(resumed.inputs) == 1 and len(verifier.requests) == 5
    assert len(verifier.replies) == 1 and reserved[-1] is True
    latest = reopened.get(parent.run_id)
    assert latest.metadata["xiaox_runtime"]["generation"] == 2
    assert latest.metadata["runtime_goal_contract"] == contract
    assert latest.metadata["xiaox_runtime"]["goal_format_retry_used"] is True


def test_only_persisted_host_skills_become_developer_guidance(setup_runtime):
    invoke, _ = setup_runtime
    store = Store()
    contract = build_goal_contract(
        store.run,
        context_evidence=[
            {
                "source": "host_skill",
                "status": "completed",
                "rules": ["技能「销售汇总」：先查原始行，再逐项核对。"],
            }
        ],
    )
    store.run.metadata.update(
        runtime_goal_contract=contract, runtime_goal_digest=contract["digest"]
    )
    transport = Transport(store)
    result = asyncio.run(
        invoke(
            store,
            transport,
            completion_mode="reply",
            input_data={"skill_rules": ["FORGED_PRIVILEGE_ESCALATION"]},
        )
    )
    assert result["ok"] is True
    assert "先查原始行，再逐项核对" in transport.started[0]
    assert "FORGED_PRIVILEGE_ESCALATION" not in transport.started[0]
    assert "不新增目标" in transport.started[0]


@pytest.mark.asyncio
async def test_new_plan_delivers_host_rendered_steps_from_first_sdk_turn(
    setup_runtime, monkeypatch
):
    from app.infrastructure.xiaox.tools import XiaoxToolBridge

    monkeypatch.setattr(XiaoxToolBridge, "visible_actions", lambda *_: iter(()))
    invoke, _ = setup_runtime
    store = Store()
    store.run.message = "给出库区清单核对方案"
    store.run.metadata.update(
        runtime_requested_deliverable="action_plan",
        runtime_execution_mode="plan",
        plan_delivery_version=1,
    )
    frozen = build_goal_contract(
        store.run,
        context_evidence=[
            {
                "source": "desktop_navigation",
                "entries": [
                    {"id": "inventory", "label": "清单", "breadcrumb": ["库区"], "kind": "page"}
                ],
            }
        ],
    )
    store.run.metadata.update(runtime_goal_contract=frozen, runtime_goal_digest=frozen["digest"])
    raw = '{"plan":{"kind":"steps","steps":[{"kind":"navigation","navigation_id":"inventory","inputs":{}}]}}'
    transport = Transport(store, completed(raw))
    result = await invoke(store, transport, completion_mode="reply")
    assert result["ok"] and result["reply_completed"] and not result["business_completed"]
    assert not result["tool_calls"] and "库区 → 清单" in result["output"]
    assert raw not in result["output"] and len(transport.schemas) == 1
    assert transport.schemas[0]["properties"]["plan"]
    assert '"requested_deliverable": "action_plan"' in transport.inputs[0]


@pytest.mark.asyncio
async def test_unavailable_plan_delivers_safe_observation_without_model_review(
    setup_runtime,
    monkeypatch,
):
    from app.application.agent_runtime.goal_verifier import verify_runtime_goal
    from app.infrastructure.xiaox.tools import XiaoxToolBridge

    # Restore the real early verdict, which must never call a second model on this branch.
    from tests.test_application.test_xiaox_goal_verifier import verify_runtime_goal as actual_review

    assert verify_runtime_goal is not actual_review
    monkeypatch.setattr(
        "app.application.agent_runtime.goal_verifier.verify_runtime_goal", actual_review
    )
    monkeypatch.setattr(XiaoxToolBridge, "visible_actions", lambda *_: iter(()))
    invoke, _ = setup_runtime
    store = Store()
    store.run.message = "给出核对方案"
    store.run.metadata.update(
        runtime_requested_deliverable="action_plan",
        runtime_execution_mode="plan",
        plan_delivery_version=1,
    )
    frozen = build_goal_contract(store.run)
    store.run.metadata.update(runtime_goal_contract=frozen, runtime_goal_digest=frozen["digest"])
    transport = Transport(
        store, completed('{"plan":{"kind":"unavailable","reason":"missing_input"}}')
    )
    result = await invoke(store, transport)
    assert result["execution_state"] == "blocked" and not result["ok"]
    assert "现有资料不足" in result["output"] and not result["tool_calls"]
    assert len(transport.schemas) == 1
