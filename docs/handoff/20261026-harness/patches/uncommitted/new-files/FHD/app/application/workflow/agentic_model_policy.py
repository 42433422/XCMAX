"""JSON workflow decisions adapted to the existing durable model-turn driver."""

from __future__ import annotations

import copy
from dataclasses import asdict
from datetime import UTC, datetime

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.model_turn_runtime import (
    ModelTurnError,
    ModelTurnRejected,
    exact_json,
    policy_secrets,
    run_model_turn,
    safe_value,
)
from app.application.agent_orchestrator.tool_receipt import tool_receipt_outcome
from app.application.agent_orchestrator.trace_runs import (
    WorkflowExecutionLease,
    WorkflowReceiptProjection,
)
from app.application.tools.workflow_tools.dispatch import parse_arguments
from app.utils.operational_errors import RECOVERABLE_ERRORS

from .engine_decisions import build_decision_messages, decision_model_scope
from .workflow_types import NodeExecutionResult, PlanGraph, StateSchema, WorkflowRunResult

_TYPES = {
    None: None,
    bool: "bool",
    int: "int",
    float: "float",
    str: "str",
    list: "list",
    dict: "dict",
}
_INVALID = "工具决策缺少 tool_id 或真实 action_name，已跳过。"


def _schema_snapshot(schema):
    rows = []
    portable = True
    for name, field in schema.fields.items():
        token = next((token for kind, token in _TYPES.items() if field.type is kind), "ephemeral")
        portable = (
            portable and token != "ephemeral" and field.merge in {"set", "append", "merge_dict"}
        )
        rows.append({"key": name, "type": token, "merge": field.merge})
    return rows, portable


def _portable_engine(engine):
    from .engine import WorkflowEngine

    if type(engine) is not WorkflowEngine:
        return False
    for name in (
        "_llm_decide_next_step",
        "_run_single_tool",
        "_agentic_tool_allows_auto_retry",
        "_append_node_trace",
        "_merge_state_schema",
        "_emit_state_update",
        "_summarize_output",
        "_recovery_hint",
    ):
        original = getattr(WorkflowEngine, name)
        actual = getattr(engine, name)
        if getattr(actual, "__func__", actual) is not original:
            return False
    dispatch = engine._dispatch
    if getattr(dispatch, "__module__", "") == "app.legacy.workflow.legacy_engine_adapter":
        cells = getattr(dispatch, "__closure__", None) or []
        return any(
            getattr(cell.cell_contents, "__module__", "") == "app.di.registry" for cell in cells
        )
    return dispatch is registered_workflow_dispatch


def registered_workflow_dispatch(*, tool_id, action, params):
    from app.application.facades.tools_facade import execute_registered_workflow_tool

    return execute_registered_workflow_tool(tool_id, action, params)


def _limits(registry, max_retries, context):
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

    longest = 0.0
    for tool_id, meta in registry.items():
        for action in meta.get("actions") or {}:
            spec = get_tool_action_spec(tool_id, action)
            if spec is not None:
                longest = max(
                    longest,
                    float(spec.timeout_seconds) * (1 + max_retries if spec.idempotent else 1),
                )
    seconds = min(86400.0, 10 * (20.0 + longest))
    # Request options can only reduce the server-derived bound.
    if isinstance(context.get("timeout_seconds"), (int, float)) and context["timeout_seconds"] > 0:
        seconds = min(seconds, float(context["timeout_seconds"]))
    if context.get("deadline_utc"):
        try:
            deadline = datetime.fromisoformat(str(context["deadline_utc"]).replace("Z", "+00:00"))
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=UTC)
            # Preserve a stable admission fingerprint; check the absolute deadline per turn.
        except ValueError:
            raise ModelTurnError("工作流任务 deadline 无效") from None
    return {"rounds": 10, "calls": 10, "repeat": 0, "seconds": max(0.001, seconds)}


class WorkflowAgenticModelPolicy:
    kernel = "workflow_agentic"

    def __init__(
        self, engine, plan, context, registry, max_retries, schema, client, model, *, snapshot=None
    ):
        self.engine, self.plan, self.context = engine, plan, dict(context or {})
        self.registry = copy.deepcopy(registry)
        self.max_retries, self.schema = max_retries, schema
        self.client, self.model = client, model
        self.repository = None
        self.nodes = {}
        self._node_metrics = {}
        self._live = set()
        self._state = None
        self._replaying = True
        fields, portable_schema = _schema_snapshot(schema)
        self._snapshot = snapshot or {
            "version": 1,
            "protocol": "workflow-json-v1",
            "plan": asdict(plan),
            "registry_entries": [
                [
                    name,
                    {key: value for key, value in meta.items() if key != "actions"},
                    [[action, value] for action, value in (meta.get("actions") or {}).items()],
                ]
                for name, meta in registry.items()
            ],
            "schema": fields,
            "max_retries": max_retries,
            "hook_profile": "workflow-engine-v1"
            if portable_schema and _portable_engine(engine)
            else "ephemeral",
            "limits": _limits(registry, max_retries, self.context),
            "request_parameters": {"temperature": 0.1, "max_tokens": 600},
        }

    def secrets(self):
        return policy_secrets(self.context, self.client)

    def snapshot(self):
        return copy.deepcopy(self._snapshot)

    @classmethod
    def restore(cls, snapshot, context, client, model):
        from .engine import WorkflowEngine
        from .workflow_types import Branch, WorkflowNode

        if snapshot.get("hook_profile") != "workflow-engine-v1":
            raise ModelTurnError(
                "原工作流包含不可恢复的 Python hook", error_code="workflow_hook_not_restorable"
            )
        plan = dict(snapshot["plan"])
        plan["nodes"] = [
            WorkflowNode(**{**row, "branches": [Branch(**branch) for branch in row["branches"]]})
            for row in plan["nodes"]
        ]
        schema = StateSchema()
        types = {value: key for key, value in _TYPES.items()}
        for row in snapshot["schema"]:
            if row["type"] not in types:
                raise ModelTurnError("原工作流 StateSchema 不可恢复")
            schema.declare(row["key"], types[row["type"]], row["merge"])
        registry = {
            name: {**meta, "actions": dict(actions)}
            for name, meta, actions in snapshot["registry_entries"]
        }
        return cls(
            WorkflowEngine(registered_workflow_dispatch),
            PlanGraph(**plan),
            context,
            registry,
            snapshot["max_retries"],
            schema,
            client,
            model,
            snapshot=copy.deepcopy(snapshot),
        )

    def validate_saved(self, state):
        if (
            state["kernel"] != self.kernel
            or state["policy"] != self.snapshot()
            or state["limits"] != self._snapshot["limits"]
        ):
            raise ModelTurnError("原工作流策略已变化，不能替换模型决策")
        self._state = state
        run = self.repository.get(self.context["run_id"]) if self.repository else None
        self._admission_context = copy.deepcopy(
            run.metadata["runtime_context"] if run else self.context
        )
        if "_workflow_execution_lease" in self.context:
            self._admission_context["_workflow_execution_lease"] = self.context[
                "_workflow_execution_lease"
            ]
        self.context = copy.deepcopy(self._admission_context)
        self.nodes = {}
        self._node_metrics = {}
        self._live = set()
        self._replaying = True

    def complete_restore(self):
        self._replaying = False

    def bind_state(self, state):
        self._state = state

    def check_control(self):
        from app.application.agent_orchestrator.run_control import get_run_control

        if get_run_control(str(self.context.get("run_id") or "")) == "cancel":
            raise ModelTurnRejected("工作流任务已取消")
        if self.context.get("deadline_utc"):
            deadline = datetime.fromisoformat(
                str(self.context["deadline_utc"]).replace("Z", "+00:00")
            )
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=UTC)
            if datetime.now(UTC) >= deadline:
                raise ModelTurnRejected("工作流任务 deadline 已到期", error_code="wall_time_limit")

    def _history(self, messages):
        history, step = [], 0
        for message in messages:
            if message.get("role") == "assistant":
                envelope = parse_arguments(message["content"])
                step = envelope["step"]
                decision, kind = envelope["decision"], envelope["kind"]
                if kind == "done":
                    history.append({"step": step, "role": "done"})
                elif kind in {"execute", "invalid"}:
                    history.append(
                        {
                            "step": step,
                            "role": "assistant",
                            "tool_id": decision.get("tool_id", ""),
                            "action": decision.get("action_name", ""),
                            "params": decision.get("params", {}),
                            "reasoning": decision.get("reasoning", ""),
                        }
                    )
                    if kind == "invalid":
                        history.append({"step": step, "role": "system", "content": _INVALID})
            elif message.get("role") == "tool":
                output = parse_arguments(message["content"])
                output = output.get("result", output)
                node = self.nodes.get(message.get("tool_call_id"))
                text = (
                    f"结果: {self.engine._summarize_output(output)}"
                    if tool_receipt_outcome(output) == "success"
                    else f"工具执行失败: {node.error if node else output.get('message') or output.get('error') or 'unknown error'}"
                )
                history.append({"step": step, "role": "system", "content": text})
        return history

    def request(self, messages, state):
        self._state = state
        return {
            "messages": build_decision_messages(
                str(self.context.get("message") or "").strip(),
                self.registry,
                self.context,
                self._history(messages),
            ),
            "tools": None,
            "tool_choice": None,
        }

    def transport(self, request):
        from openai import APITimeoutError

        try:
            with decision_model_scope(self.client, self.model, self.check_control) as binding:
                decision = self.engine._llm_decide_next_step(
                    user_message=str(self.context.get("message") or "").strip(),
                    tool_registry=self.registry,
                    runtime_context=self.context,
                    agent_history=self._history_from_state(),
                    user_id=self.context.get("user_id"),
                )
            for completion in binding.usage:
                yield {"type": "usage", "completion": completion}
        except ModelTurnError:
            raise
        except ValueError as exc:
            raise ModelTurnRejected(str(exc), error_code="invalid_tool_arguments") from exc
        except (APITimeoutError, *RECOVERABLE_ERRORS) as exc:
            raise ModelTurnError("工作流模型请求中断，未重新请求原决策") from exc
        if decision is None:
            normalized, kind = {}, "none"
        elif not isinstance(decision, dict):
            raise ModelTurnRejected("工作流决策必须是 JSON 对象")
        elif str(decision.get("action") or "").strip() == "done":
            normalized, kind = {"action": "done"}, "done"
        else:
            action = str(
                decision.get("action_name")
                or decision.get("tool_action")
                or decision.get("action")
                or ""
            ).strip()
            params = decision.get("params", {})
            if not isinstance(params, dict):
                raise ModelTurnRejected("工作流工具参数必须是 JSON 对象")
            normalized = {
                "tool_id": str(decision.get("tool_id") or "").strip(),
                "action_name": action,
                "params": params,
                "reasoning": str(decision.get("reasoning") or "").strip(),
            }
            kind = (
                "execute" if normalized["tool_id"] and action and action != "execute" else "invalid"
            )
        step = self._state["round"]
        calls = []
        if kind == "execute":
            params = {
                "tool_id": normalized["tool_id"],
                "action": normalized["action_name"],
                "params": normalized["params"],
            }
            identity = (
                "wfa_"
                + canonical_hash(
                    [self.context.get("run_id", ""), self._state["request_id"], 0, params]
                )[:48]
            )
            calls.append(
                {"id": identity, "name": "execute_erp_capability", "arguments": exact_json(params)}
            )
        yield {
            "type": "decision",
            "decision": {
                "content": exact_json({"kind": kind, "decision": normalized, "step": step}),
                "calls": calls,
            },
        }

    def _history_from_state(self):
        messages = []
        for message in self._state["messages"]:
            if "receipt" not in message:
                messages.append(message)
            else:
                call = self._call(message["receipt"]["call_id"])
                if (
                    call is None
                    or canonical_hash(call.output) != message["receipt"]["output_digest"]
                ):
                    raise ModelTurnError("原工作流回执已变化")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.call_id,
                        "content": exact_json(call.output),
                    }
                )
        return self._history(messages)

    def meter(self, completion, state):
        pass  # Existing provider billing remains the sole model-usage owner.

    def prepare_arguments(self, name, params):
        return params

    def validate_call(self, call, *, approved):
        from app.application.agent_orchestrator.tool_spec import (
            get_tool_action_spec,
            validate_tool_call,
        )
        from app.infrastructure.auth.agent_mod_scope import authorize_agent_tool

        params = call["params"]
        tool, action = params["tool_id"], params["action"]
        if action not in (self.registry.get(tool, {}).get("actions") or {}):
            raise ModelTurnRejected("工具不在原工作流目录")
        validation = validate_tool_call(tool, action, params["params"])
        if not validation.ok:
            raise ModelTurnRejected(validation.message)
        denied = authorize_agent_tool(tool, action, params["params"], self.context)
        if denied:
            raise ModelTurnRejected(denied["message"])
        spec = get_tool_action_spec(tool, action)
        if not spec.read_only and (
            self._snapshot["hook_profile"] != "workflow-engine-v1"
            or not _portable_engine(self.engine)
        ):
            raise ModelTurnRejected(
                "不可恢复的工作流 hook 不能执行写入", error_code="workflow_hook_not_restorable"
            )

    def before_call(self, call):
        return iter(())

    def dispatch(self, call, repository):
        from app.application.agent_orchestrator.chat_trace import _run_service

        self.repository = repository
        params, holder = call["params"], {}

        def dispatch(context):
            result = self.engine._run_single_tool(
                tool_id=params["tool_id"],
                action=params["action"],
                params=params["params"],
                runtime_context=context,
                max_retries=self.max_retries,
                retryable=self.engine._agentic_tool_allows_auto_retry(
                    self.registry, params["tool_id"], params["action"]
                ),
            )
            holder.update(asdict(result))
            return {"success": result.success, "result": result.output}

        return _run_service(repository).dispatch_tool(
            self.context["run_id"],
            call_id=call["id"],
            tool_name=call["name"],
            params=params,
            runtime_context=self.context,
            dispatch=dispatch,
            projection=WorkflowReceiptProjection(lambda: holder),
        )

    def _call(self, identity):
        run = self.repository.get(self.context["run_id"]) if self.repository else None
        return (
            next((call for call in run.tool_calls if call.call_id == identity), None)
            if run
            else None
        )

    def observe(self, call, output):
        saved = self._call(call["id"])
        if saved is None:
            raise ModelTurnError("工作流原调用回执不存在")
        projection = saved.metadata.get("workflow_projection")
        if saved.metadata.get("workflow_projection_error") or not isinstance(projection, dict):
            raise ModelTurnError("工作流回执投影缺失，原回执已保留")
        if projection.get("node_digest") != canonical_hash(projection.get("node_result")):
            raise ModelTurnError("工作流回执投影已损坏，原回执已保留")
        if projection["output_digest"] != canonical_hash(output):
            step = next(
                row
                for row in self.repository.get(self.context["run_id"]).steps
                if row.step_id == saved.step_id
            )
            old = projection["node_result"]["output"]
            if (
                tool_receipt_outcome(old) != "waiting_approval"
                or step.attempt_count < 1
                or tool_receipt_outcome(output)
                not in {"success", "failure", "unknown", "cancelled"}
            ):
                raise ModelTurnError("工作流原回执投影摘要已变化")
            projection = copy.deepcopy(projection)
            projection["node_result"].update(
                output=copy.deepcopy(output),
                success=tool_receipt_outcome(output) == "success",
                error=step.error,
                started_at=step.started_at,
                finished_at=step.finished_at,
                duration_ms=step.duration_ms,
            )
            metrics = projection["node_result"]
            metrics["recovery_hint"] = (
                ""
                if metrics["success"]
                else self.engine._recovery_hint(
                    tool_id=metrics["tool_id"],
                    action=metrics["action"],
                    error=step.error,
                    output=output,
                    retryable=metrics["retryable"],
                )
            )
            metrics["attempts"] = [
                {
                    "attempt": step.attempt_count,
                    "success": metrics["success"],
                    "error": str(step.error or "")[:240],
                    "duration_ms": step.duration_ms,
                }
            ]
            projection["output_digest"] = canonical_hash(output)
            projection["node_digest"] = canonical_hash(projection["node_result"])
            run = self.repository.get(self.context["run_id"])
            next(row for row in run.tool_calls if row.call_id == saved.call_id).metadata[
                "workflow_projection"
            ] = projection
            self.repository.save(run)
        result = NodeExecutionResult(**projection["node_result"])
        if (
            result.output != output and result.output != output.get("result")
        ) or result.success != (tool_receipt_outcome(output) == "success"):
            raise ModelTurnError("工作流投影与真实工具回执不一致")
        self._node_metrics[call["id"]] = copy.deepcopy(projection["node_result"])
        self.nodes[call["id"]] = result
        marker = (call["id"], projection["output_digest"])
        if marker not in self._live:
            revised = any(identity == call["id"] for identity, _digest in self._live)
            self._live.add(marker)
            if revised:
                self.context = copy.deepcopy(self._admission_context)
                for identity, metrics in self._node_metrics.items():
                    self.nodes[identity] = NodeExecutionResult(**copy.deepcopy(metrics))
                    self._project_node(identity, self.nodes[identity])
                result = self.nodes[call["id"]]
            else:
                self._project_node(call["id"], result)
            if not self._replaying:
                self.engine._emit_state_update(result)

    def _project_node(self, identity, result):
        self.engine._append_node_trace(self.context, result)
        self.engine._merge_state_schema(self.context, result, self.schema)
        self.context.setdefault("node_outputs", {})[
            f"agent_step_{self._step_for_call(identity)}"
        ] = result.output

    def _step_for_call(self, identity):
        for message in self._state["messages"]:
            if any(row["id"] == identity for row in message.get("tool_calls") or []):
                return parse_arguments(message["content"])["step"]
        raise ModelTurnError("工作流调用不属于原决策")

    def after_batch(self, state):
        return None

    def validate_text(self, text):
        parse_arguments(text)

    def no_call_transition(self, decision, state):
        current = parse_arguments(decision["content"])
        if current["kind"] == "invalid":
            return {"phase": "ready_model"}
        invalid = sum(
            parse_arguments(row["content"])["kind"] == "invalid"
            for row in state["messages"]
            if row.get("role") == "assistant"
        )
        failed = sum(not row.success for row in self.nodes.values())
        success = current["kind"] == "done" and not invalid and not failed
        text = (
            "AgenticLoop 执行完成"
            if success
            else (
                f"{failed} 个工具步骤失败"
                if failed
                else f"{invalid} 个模型工具决策无效"
                if invalid
                else "模型未返回可执行决策"
            )
        )
        return {
            "phase": "terminal",
            "outcome": "success" if success else "failure",
            "final_text": text,
        }

    def result(self, state, outcome, receipt):
        success = outcome == "success"
        status = (
            "completed"
            if success
            else "waiting_user"
            if outcome == "waiting_approval"
            else "cancelled"
            if outcome == "cancelled"
            else "blocked"
            if outcome in {"pending", "unknown"}
            else "failed"
        )
        invalid = sum(
            parse_arguments(row["content"])["kind"] == "invalid"
            for row in state["messages"]
            if row.get("role") == "assistant"
        )
        context = {
            key: copy.deepcopy(value)
            for key, value in self.context.items()
            if not key.startswith("_") and key not in {"db_read_token", "db_write_token"}
        }
        reason = str(
            receipt.get("message")
            or state.get("notice")
            or state.get("final_text")
            or "模型未声明完成"
        )
        context["workflow_status"] = {
            "state": status,
            "completed_by_model": any(
                parse_arguments(row["content"])["kind"] == "done"
                for row in state["messages"]
                if row.get("role") == "assistant"
            ),
            "steps": state["round"],
            "failed_tool_steps": sum(not row.success for row in self.nodes.values()),
            "invalid_decisions": invalid,
            "message": reason,
        }
        result = WorkflowRunResult(
            self.plan.plan_id,
            success,
            list(self.nodes.values()),
            context,
            f"AgenticLoop 完成（{state['round']} 步）"
            if success
            else f"AgenticLoop 未完成（{state['round']} 步）：{reason}",
        )
        return {"success": success, "workflow_result": asdict(result), "outcome": outcome}


def create_policy(engine, plan, context, registry, max_retries=1, schema=None):
    from app.infrastructure.llm.client import get_openai_compatible_client, resolve_chat_model

    schema = schema or engine._default_state_schema
    client, model = (
        (get_openai_compatible_client(), resolve_chat_model())
        if context.get("_actor_authorization")
        else (None, "")
    )
    safe_value(
        {
            key: value
            for key, value in context.items()
            if not key.startswith("_") and key not in {"db_read_token", "db_write_token"}
        },
        secrets=policy_secrets(context, client),
    )
    return WorkflowAgenticModelPolicy(
        engine, plan, context, registry, max_retries, schema, client, model
    )


def admit_policy(policy):
    from app.application.agent_orchestrator.chat_trace import _run_service

    service = _run_service()
    run = service.claim_workflow_run(
        message=str(policy.context.get("message") or ""),
        runtime_context=policy.context,
        plan=policy.plan,
        policy_snapshot=policy.snapshot(),
    )
    policy.context = {
        **run.metadata["runtime_context"],
        "_workflow_execution_lease": WorkflowExecutionLease(run.run_id),
    }
    policy.admission_replayed = bool(run.metadata.get("admission_replayed"))
    policy.repository = service.repository
    return run


def project_terminal_workflow(run, state):
    """Recover the terminal-checkpoint boundary without publishing old callbacks."""
    from types import SimpleNamespace

    policy = WorkflowAgenticModelPolicy.restore(
        state["policy"], run.metadata["runtime_context"], None, state["model_reference"]["model"]
    )
    policy.repository = SimpleNamespace(
        get=lambda identity: run if identity == run.run_id else None
    )
    policy.validate_saved(state)
    for call in run.tool_calls:
        if call.metadata.get("workflow_projection", {}).get("output_digest") != canonical_hash(
            call.output
        ):
            raise ModelTurnError("原终态工具回执已变化，不能重建完成结果")
        policy.observe({"id": call.call_id}, copy.deepcopy(call.output))
    return policy.result(state, state["outcome"], {})


def block_workflow_restore(repository, run, state):
    """Retain the original evidence when actor/model/Python hooks cannot restore."""
    from app.application.agent_orchestrator.model_turn_runtime import STATE_KEY

    notice = "原工作流身份、模型配置或 Python hook 无法恢复，已停止执行，请核对原任务"
    state.update(
        phase="reconciliation",
        outcome="unknown",
        blocked_model_recovery=True,
        notice=notice,
        exit_status="workflow_restore_blocked",
    )
    run.metadata[STATE_KEY] = state
    run.status, run.error = "blocked", notice
    payload = run.final_output.get("workflow_result")
    if isinstance(payload, dict):
        payload.update(success=False, outcome="unknown")
        if isinstance(payload.get("workflow_result"), dict):
            result = payload["workflow_result"]
            result.update(success=False, message=notice)
            result.setdefault("final_context", {}).setdefault("workflow_status", {}).update(
                state="blocked", message=notice
            )
    run.add_event("model_turn.reconciliation", notice, {"error_code": "workflow_restore_blocked"})
    return repository.save(run)


def run_workflow_policy(engine, plan, context, max_retries, registry, user_id, schema):
    context = dict(context or {})
    if user_id is not None and "user_id" not in context:
        context["user_id"] = user_id
    policy = context.get("_workflow_model_policy")
    if isinstance(policy, WorkflowAgenticModelPolicy):
        if policy.engine is not engine or policy.plan != plan or policy.registry != registry:
            raise ModelTurnError("原工作流 admission 与执行策略不一致")
        run = policy.repository.get(policy.context["run_id"])
    else:
        policy = create_policy(engine, plan, context, registry, max_retries, schema)
        run = admit_policy(policy) if policy.context.get("_actor_authorization") else None
    if run and policy.admission_replayed:
        stored = run.final_output.get("workflow_result")
        if not isinstance(stored, dict):
            from app.application.agent_orchestrator.model_turn_runtime import (
                STATE_KEY,
                terminal_model_payload,
            )

            if run.metadata.get(STATE_KEY, {}).get("phase") == "terminal":
                stored = terminal_model_payload(run)
        if not isinstance(stored, dict):
            raise ModelTurnError("原工作流正在执行或等待核对，不能重新请求模型")
        payload = stored
    else:
        for event in run_model_turn(
            policy,
            context=policy.context,
            messages=[],
            limits=policy.snapshot()["limits"],
            repository=policy.repository,
            run_id=run.run_id if run else "",
        ):
            if event["type"] == "result":
                payload = event["result"]
    projected = dict(payload["workflow_result"])
    projected["node_results"] = [NodeExecutionResult(**row) for row in projected["node_results"]]
    return WorkflowRunResult(**projected)
