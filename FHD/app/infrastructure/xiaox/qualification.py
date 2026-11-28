"""Bounded, isolated qualification through the production Xiaox/Responses stack.

Only the configuration lifecycle calls this runner. It never admits a business
run or creates a temporary PASS. MCP's official SDK owns the protocol; SQLite
is a disposable probe, with no production capability dispatcher attached.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from httpx_sse import EventSource
from jsonschema import Draft202012Validator

from app.build_identity import build_identity
from app.infrastructure.xiaox.launcher import verify_installation
from app.infrastructure.xiaox.local_server import LocalRuntimeServer
from app.infrastructure.xiaox.policy import (
    CODEX_VERSION,
    QUALIFICATION_CHECKS,
    ModelRoute,
    RuntimePolicyError,
    RuntimeSettings,
    independent_gateway_url,
    qualification_host_identity,
)
from app.infrastructure.xiaox.transport import (
    XiaoxTransport,
    XiaoxTransportConfig,
    _write_private,
)
from app.utils.operational_errors import BOUNDARY_ERRORS

_MAX_PROBE_CALLS = 64


class ModelEgressDenied(httpx.RequestError):
    """Rejected before HTTPX opens a connection; contains no destination/secret."""


class IndependentModelTransport(httpx.AsyncBaseTransport):
    """Pin the host model egress, using HTTPX's maintained HTTP implementation.

    This is an application boundary, not an operating-system firewall. Xiaox
    itself receives only the private loopback model/MCP endpoints.
    """

    def __init__(self, route: ModelRoute) -> None:
        self._endpoint = httpx.URL(route.base_url + "/responses")
        self._http = httpx.AsyncHTTPTransport(retries=0, trust_env=False)
        self.connections_attempted = 0
        self.denied = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        try:
            independent_gateway_url(str(request.url))
            allowed = request.url == self._endpoint and request.method == "POST"
        except RuntimePolicyError:
            allowed = False
        if not allowed:
            self.denied += 1
            raise ModelEgressDenied("Independent model egress denied", request=request)
        self.connections_attempted += 1
        return await self._http.handle_async_request(request)

    async def aclose(self) -> None:
        await self._http.aclose()


class _QualificationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class _Probe:
    directory: Path
    nonce: str = field(default_factory=lambda: uuid.uuid4().hex)
    phase: str = "initial"
    models: list[dict[str, Any]] = field(default_factory=list)
    network: dict[str, Any] = field(default_factory=dict)
    recovery: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""

    @property
    def database(self) -> Path:
        return self.directory / "probe.sqlite3"

    def initialize(self) -> None:
        with sqlite3.connect(self.database) as db:
            db.execute("CREATE TABLE receipt (nonce TEXT, step INTEGER PRIMARY KEY)")
            db.execute("CREATE TABLE calls (tool TEXT, phase TEXT, step INTEGER, accepted INTEGER)")
        self.database.chmod(0o600)

    def invoke(self, name: str, arguments: dict) -> dict:
        # No SQL, file paths, capability names or production identifiers are
        # accepted from the model. Even a repeated rejected write is audited.
        step = arguments.get("step")
        valid = (
            type(step) is int
            and step in (1, 2)
            and arguments == {"nonce": self.nonce, "step": step}
        )
        with sqlite3.connect(self.database) as db:
            # Serialize the observation and commit so concurrent rejected calls
            # remain in the audit instead of rolling back on a duplicate insert.
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT nonce, step FROM receipt ORDER BY step LIMIT 3").fetchmany(3)
            existing = rows in ([], [(self.nonce, 1)], [(self.nonce, 1), (self.nonce, 2)])
            observed_first = db.execute(
                "SELECT 1 FROM calls WHERE tool = 'task_evidence' AND phase = 'resumed' "
                "AND step = 1 AND accepted = 1 LIMIT 1"
            ).fetchone()
            accepted = valid and (
                name == "task_evidence"
                and existing
                and (self.nonce, step) in rows
                or name == "execute_action"
                and (
                    step == 1
                    and self.phase == "initial"
                    and not rows
                    or step == 2
                    and self.phase == "resumed"
                    and rows == [(self.nonce, 1)]
                    and observed_first is not None
                )
            )
            db.execute(
                "INSERT INTO calls VALUES (?, ?, ?, ?)",
                (
                    name,
                    self.phase,
                    step if type(step) is int and step in (1, 2) else 0,
                    int(accepted),
                ),
            )
            if accepted and name == "execute_action":
                db.execute("INSERT INTO receipt VALUES (?, ?)", (self.nonce, step))
        return {
            "success": accepted,
            "verified": accepted,
            "nonce": self.nonce if accepted else "",
            "step": step if accepted else None,
        }

    def snapshot(self) -> dict:
        # Independent, read-only connection; an MCP success string is not proof.
        with sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True) as db:
            rows = db.execute("SELECT nonce, step FROM receipt ORDER BY step LIMIT 3").fetchmany(3)
            calls = db.execute(
                "SELECT tool, phase, step, accepted FROM calls ORDER BY rowid LIMIT ?",
                (_MAX_PROBE_CALLS + 1,),
            ).fetchmany(_MAX_PROBE_CALLS + 1)
        # The extra row detects overflow; a truncated ledger is never proof that
        # no replay or rejected action occurred after the visible prefix.
        return {
            "row_verified": rows == [(self.nonce, 1), (self.nonce, 2)],
            "first_step_verified": rows == [(self.nonce, 1)],
            "calls": calls,
            "calls_complete": len(calls) <= _MAX_PROBE_CALLS,
        }


class _ProbeMcpResponse(Response):
    def __init__(self, probe: _Probe) -> None:
        super().__init__(content=None)
        self.probe = probe

    async def __call__(self, scope, receive, send) -> None:
        from mcp.server.lowlevel import Server
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

        async def list_tools(_ctx, _params):
            return ListToolsResult(
                tools=[
                    Tool(
                        name=name,
                        description=description,
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "nonce": {"type": "string"},
                                "step": {"type": "integer", "enum": [1, 2]},
                            },
                            "required": ["nonce", "step"],
                            "additionalProperties": False,
                        },
                    )
                    for name, description in (
                        (
                            "execute_action",
                            "Commit the requested isolated qualification step exactly once.",
                        ),
                        ("task_evidence", "Read the already committed qualification step."),
                    )
                ]
            )

        async def call_tool(_ctx, params):
            result = await asyncio.to_thread(self.probe.invoke, params.name, params.arguments or {})
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result))],
                structured_content=result,
                is_error=not result["success"],
            )

        server = Server(
            "xcmax-isolated-qualification",
            version="1",
            on_list_tools=list_tools,
            on_call_tool=call_tool,
        )
        manager = StreamableHTTPSessionManager(server, stateless=True, json_response=True)
        async with manager.run():
            await manager.handle_request(scope, receive, send)


def _market_receipt(response: dict, route: ModelRoute, request_id: str) -> dict:
    proof = response.get("xcagi")
    if not isinstance(proof, dict) or any(
        proof.get(key) != value
        for key, value in {
            "schema": "xcmax.responses-billing.v1",
            "provider": route.provider_id,
            "model": route.model.removeprefix(route.provider_id + "/"),
            "key_source": route.key_source,
            "config_revision": route.config_revision,
            "client_request_id": request_id,
            "usage": response.get("usage"),
        }.items()
    ):
        raise _QualificationError("runtime_billing_evidence_missing")
    byok = route.key_source in {"byok", "user", "user_override"}
    if (
        proof.get("billing_status") != ("byok" if byok else "settled")
        or type(proof.get("billed")) is not bool
        or byok
        and proof.get("billed") is not False
        or not isinstance(proof.get("request_id"), str)
        or not proof["request_id"]
        or not byok
        and (not isinstance(proof.get("hold_no"), str) or not proof["hold_no"])
    ):
        raise _QualificationError("runtime_billing_evidence_missing")
    try:
        amount = Decimal(proof["charge_amount"])
        if (
            not amount.is_finite()
            or amount < 0
            or byok
            and amount != 0
            or amount > 0
            and proof.get("billed") is not True
        ):
            raise InvalidOperation
    except (KeyError, ValueError, TypeError, InvalidOperation):
        raise _QualificationError("runtime_billing_evidence_missing") from None
    return {key: proof.get(key) for key in ("request_id", "hold_no", "billing_status", "billed")}


async def _forward_model(request: Request, route: ModelRoute, probe: _Probe) -> Response:
    from app.application.agent_runtime.verification_budget import review_output_floor

    # Deferred import lets the production gateway reuse IndependentModelTransport.
    from app.infrastructure.xiaox.model_gateway import (
        _prepare_body,
        _validate_model_output,
        _validate_output_item,
        response_usage,
    )

    raw = await request.body()
    if len(raw) > route.max_request_bytes or len(probe.models) >= min(route.max_model_calls, 12):
        raise _QualificationError("runtime_qualification_limit")
    payload = json.loads(raw)
    review_probe = probe.phase == "attachment_review"
    if isinstance(payload, dict):
        # This disposable probe needs a small receipt/compaction summary, not
        # the deployment's maximum generation allowance or wallet hold.
        maximum = (
            review_output_floor(route.upstream_vendor, route.response_model)
            if review_probe
            else 2048
        )
        payload["max_output_tokens"] = min(route.max_output_tokens, maximum)
    body = _prepare_body(payload, route)
    if bool(body.get("stream")) == review_probe:
        raise _QualificationError("runtime_stream_evidence_missing")
    request_id = uuid.uuid4().hex
    observation: dict[str, Any] = {
        "request_id": request_id,
        "phase": probe.phase,
        "completed": False,
    }
    probe.models.append(observation)

    def accept_terminal(response: Any) -> None:
        if not isinstance(response, dict) or response.get("status") != "completed":
            raise _QualificationError("runtime_model_response_failed")
        if response.get("model") != route.response_model or any(
            response.get(key) for key in ("fallback_used", "_fallback_used")
        ):
            raise _QualificationError("runtime_model_identity_mismatch")
        _validate_model_output(response)
        usage = response_usage(response)
        if usage is None:
            raise _QualificationError("runtime_usage_evidence_missing")
        observation.update(model=response["model"], usage=usage)
        if route.gateway_kind == "market":
            observation["billing"] = _market_receipt(response, route, request_id)

    transport = IndependentModelTransport(route)
    async with httpx.AsyncClient(
        transport=transport,
        trust_env=False,
        follow_redirects=False,
        timeout=httpx.Timeout(60, connect=15),
    ) as client:
        if not probe.network:
            # Exercise the exact outbound transport before spending model tokens.
            # No authentication or user data accompanies this negative control.
            try:
                await client.post("https://api.openai.com/v1/responses", json={})
            except ModelEgressDenied:
                if transport.denied == 1 and transport.connections_attempted == 0:
                    probe.network = {"scope": "host_model_egress", "denied_before_connect": True}
            if not probe.network:
                raise _QualificationError("runtime_network_denial_unverified")
        async with client.stream(
            "POST",
            route.base_url + "/responses",
            json=body,
            headers={
                "Accept": "application/json" if review_probe else "text/event-stream",
                **route.headers(request_id),
            },
        ) as upstream:
            upstream.raise_for_status()
            names = ("x-litellm-attempted-retries", "x-litellm-attempted-fallbacks")
            if (route.gateway_kind != "market" or route.provider_id == "litellm") and any(
                upstream.headers.get_list(name) != ["0"] for name in names
            ):
                raise _QualificationError("runtime_upstream_attempts_unverified")
            if route.gateway_kind == "market" and (
                upstream.headers.get_list("x-xcmax-upstream-attempts") != ["1"]
                or upstream.headers.get_list("x-xcmax-upstream-fallbacks") != ["0"]
            ):
                raise _QualificationError("runtime_upstream_attempts_unverified")
            observation["single_attempt"] = True
            if review_probe:
                raw_terminal = bytearray()
                async for chunk in upstream.aiter_bytes():
                    raw_terminal.extend(chunk)
                    if len(raw_terminal) > 8_388_608:
                        raise _QualificationError("runtime_qualification_limit")
                terminal = json.loads(raw_terminal)
                accept_terminal(terminal)
                observation["completed"] = True
                return JSONResponse(terminal)
            output, size, deltas, terminal = [], 0, 0, None
            async for event in EventSource(upstream).aiter_sse():
                if event.data == "[DONE]":
                    continue
                value = json.loads(event.data)
                if not isinstance(value, dict) or terminal is not None:
                    raise _QualificationError("runtime_stream_evidence_missing")
                response = value.get("response")
                if isinstance(response, dict):
                    if (
                        response.get("model") != route.response_model
                        or response.get("fallback_used")
                        or response.get("_fallback_used")
                    ):
                        raise _QualificationError("runtime_model_identity_mismatch")
                    observation["model"] = response["model"]
                if "item" in value:
                    _validate_output_item(value["item"])
                kind = value.get("type", "")
                if kind.endswith(".delta"):
                    deltas += 1
                if kind in {"response.failed", "response.incomplete", "error"}:
                    raise _QualificationError("runtime_model_response_failed")
                if kind == "response.completed":
                    accept_terminal(response)
                    terminal = response
                line = "data: " + json.dumps(value, ensure_ascii=False) + "\n\n"
                size += len(line.encode())
                if size > 8_388_608:
                    raise _QualificationError("runtime_qualification_limit")
                output.append(line)
            if terminal is None or not deltas:
                raise _QualificationError("runtime_stream_evidence_missing")
            observation.update(completed=True, stream_deltas=deltas)
    # Never release a proposed tool before exact identity, usage and (on the
    # market route) durable settlement have been observed at the end of the SSE.
    return Response("".join(output), media_type="text/event-stream")


def _probe_app(route: ModelRoute, probe: _Probe, model_token: str, mcp_token: str) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def authenticated(request: Request, token: str) -> bool:
        return secrets.compare_digest(request.headers.get("authorization", ""), "Bearer " + token)

    @app.api_route("/mcp", methods=["GET", "POST", "DELETE"])
    async def mcp(request: Request):
        if not authenticated(request, mcp_token):
            return Response(status_code=401)
        return _ProbeMcpResponse(probe)

    @app.post("/v1/responses")
    async def model(request: Request):
        if not authenticated(request, model_token):
            return Response(status_code=401)
        try:
            return await _forward_model(request, route, probe)
        except BOUNDARY_ERRORS as exc:
            if isinstance(exc, _QualificationError):
                probe.error_code = exc.code
            elif isinstance(exc, httpx.HTTPStatusError):
                status = exc.response.status_code
                if probe.models:
                    probe.models[-1]["http_status"] = status
                probe.error_code = (
                    "runtime_model_auth_failed"
                    if status in {401, 403}
                    else "runtime_model_rate_limited"
                    if status == 429
                    else "runtime_model_gateway_unavailable"
                    if status >= 500
                    else "runtime_model_request_rejected"
                )
            elif isinstance(exc, (httpx.TimeoutException, TimeoutError)):
                probe.error_code = "runtime_model_timeout"
            elif isinstance(exc, httpx.RequestError):
                probe.error_code = "runtime_model_connection_failed"
            else:
                probe.error_code = "runtime_model_probe_failed"
            return JSONResponse(
                {"error": {"message": "Qualification model request failed"}}, status_code=502
            )

    return app


async def _completed_turn(runtime: XiaoxTransport, text: str) -> None:
    completed = False
    async for event in runtime.stream_turn(text):
        if event["method"] == "turn/completed":
            completed = event["payload"].get("turn", {}).get("status") == "completed"
    if not completed:
        raise _QualificationError("runtime_probe_turn_failed")


async def _probe_attachment_review(config: XiaoxTransportConfig, probe: _Probe) -> None:
    from app.application.agent_orchestrator.run_models import AgentRun
    from app.domain.task_lifecycle.agent_runtime_contract import build_goal_contract, review_schema

    task = "Report the worksheet name in the fixture."
    contract = build_goal_contract(AgentRun(user_id="qualification", message=task))
    schema = review_schema(
        contract, file_evidence={}, source_block_ids=("s1",), response_block_ids=("r1",)
    )
    probe.phase = "attachment_review"
    async with httpx.AsyncClient(trust_env=False, timeout=65.0) as client:
        reply = await client.post(
            config.provider_url + "/responses",
            headers={"Authorization": "Bearer " + config.provider_token},
            json={
                "model": config.model,
                "input": f"Assess this reply using the attachment evidence. Request: {task} "
                "s1: the worksheet is Inventory. r1: the worksheet is Inventory. "
                "Return one satisfied reply goal from request with file_basis=passages, "
                "evidence_ids=[response], and a citation from s1 to r1. Use feedback_disposition=none.",
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "runtime_goal_review",
                        "schema": schema,
                        "strict": False,
                    }
                },
            },
        )
    reply.raise_for_status()
    text = "".join(
        part["text"]
        for item in reply.json()["output"]
        if item.get("type") == "message"
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    )
    result = json.loads(text)
    if not Draft202012Validator(schema).is_valid(result) or not any(
        goal.get("file_basis") == "passages" and goal.get("file_citations")
        for goal in result["goals"]
    ):
        raise _QualificationError("runtime_attachment_review_schema_failed")
    probe.recovery["attachment_review_schema"] = True


async def _run_probe(settings: RuntimeSettings, owner_scope: str, probe: _Probe) -> None:
    route = settings.route
    assert route is not None and settings.runtime_root is not None
    model_token, mcp_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with LocalRuntimeServer(_probe_app(route, probe, model_token, mcp_token)) as server:
        config = XiaoxTransportConfig(
            runtime_root=probe.directory,
            scope_id="qualification:" + owner_scope,
            model=route.model,
            provider_url=server.url + "/v1",
            provider_token=model_token,
            mcp_url=server.url + "/mcp",
            mcp_token=mcp_token,
            context_window=route.effective_context_window,
            auto_compact_token_limit=route.input_token_budget,
            mcp_tools=("execute_action", "task_evidence"),
            codex_bin=settings.codex_bin,
            turn_timeout_seconds=settings.turn_timeout_seconds,
        )
        instructions = (
            "You are checking an isolated runtime. Only the two qualification MCP tools are "
            "available. Never request other tools. Follow the supplied probe steps exactly."
        )
        async with XiaoxTransport(config) as runtime:
            thread_id = await runtime.start_thread(developer_instructions=instructions)
            first_pid = runtime.process_id
            await _completed_turn(
                runtime,
                f"This task has two dependent steps using nonce {probe.nonce}. "
                "In this turn, call execute_action exactly once with step 1, then call "
                "task_evidence with the same nonce and step 1. Finish this turn only after "
                "its receipt is verified. Step 2 must wait for the next turn. "
                "Do not repeat execute_action for step 1.",
            )
            first = probe.snapshot()
            if not first["calls_complete"]:
                raise _QualificationError("runtime_qualification_limit")
            if (
                not first["first_step_verified"]
                or ("task_evidence", "initial", 1, 1) not in first["calls"]
                or any(call[3] != 1 for call in first["calls"])
            ):
                raise _QualificationError("runtime_probe_receipt_missing")
            probe.phase = "compact"
            compact = await runtime.compact_thread()
        # A new SDK-owned process must resume the persisted thread, not replay
        # the original user instruction into a new conversation.
        probe.phase = "resumed"
        async with XiaoxTransport(config) as resumed:
            resumed_id = await resumed.resume_thread(
                thread_id,
                developer_instructions=(
                    instructions + " The restart checkpoint is now complete. Step 2 is pending. "
                    "Only fresh tool results in the current turn count toward verification."
                ),
            )
            second_pid = resumed.process_id
            await _completed_turn(
                resumed,
                "Run the pending step 2 of the same task now. Use the original nonce from "
                "the resumed context in each of these tool calls, in this order:\n"
                "1. Call task_evidence with step=1 now. Prior text about step 1 is not a "
                "receipt for this turn. Never call execute_action with step=1 again.\n"
                "2. On a verified step 1 receipt, call execute_action with step=2 exactly once.\n"
                "3. On its success, call task_evidence with step=2. Finish only after that "
                "tool verifies the step 2 receipt. Do not stop after acknowledging step 1.",
            )
        probe.recovery = {
            "thread_id": thread_id,
            "resumed_thread_id": resumed_id,
            "compaction": compact,
            "first_process_id": first_pid,
            "second_process_id": second_pid,
        }
        await _probe_attachment_review(config, probe)


def _checks(probe: _Probe, route: ModelRoute) -> dict[str, str]:
    snapshot, recovery = probe.snapshot(), probe.recovery
    calls = snapshot["calls"]
    writes = [call for call in calls if call[0] == "execute_action"]
    reads = {(call[1], call[2]) for call in calls if call[0] == "task_evidence" and call[3] == 1}
    continued = (
        snapshot["calls_complete"]
        and snapshot["row_verified"]
        and writes == [("execute_action", "initial", 1, 1), ("execute_action", "resumed", 2, 1)]
        and {("initial", 1), ("resumed", 1), ("resumed", 2)} <= reads
        and all(call[3] == 1 for call in calls)
    )
    models_complete = bool(probe.models) and all(item.get("completed") for item in probe.models)
    facts = {
        "responses_stream": models_complete
        and any(item.get("stream_deltas", 0) > 0 for item in probe.models)
        and all(
            item.get("phase") == "attachment_review" or item.get("stream_deltas", 0) > 0
            for item in probe.models
        ),
        "multi_turn_tools": continued,
        "openai_network_denied": probe.network.get("denied_before_connect") is True,
        "business_receipt_verified": snapshot["calls_complete"]
        and snapshot["row_verified"]
        and all(call[3] == 1 for call in calls),
        "upstream_failover_disabled": models_complete
        and all(item.get("single_attempt") for item in probe.models),
        "response_model_identity": models_complete
        and all(item.get("model") == route.response_model for item in probe.models),
        "attachment_review_schema": recovery.get("attachment_review_schema") is True,
        "forced_compaction_restart_same_task_no_replay": (
            continued
            and bool(recovery.get("thread_id"))
            and recovery.get("thread_id") == recovery.get("resumed_thread_id")
            and recovery.get("compaction", {}).get("thread_id") == recovery.get("thread_id")
            and bool(recovery.get("compaction", {}).get("turn_id"))
            and type(recovery.get("first_process_id")) is int
            and type(recovery.get("second_process_id")) is int
            and recovery["first_process_id"] != recovery["second_process_id"]
        ),
    }
    facts["multi_step_restart_continuation"] = facts[
        "forced_compaction_restart_same_task_no_replay"
    ]
    return {name: "PASS" if facts[name] else "FAIL" for name in QUALIFICATION_CHECKS}


def qualify_runtime(
    settings: RuntimeSettings, *, owner_scope: str, upstream_evidence: dict | None = None
) -> dict[str, Any]:
    """Run once under the setup service's account/route lock; never auto-retry.

    Upstream metadata describes the expected route; declarations in that dict
    cannot substitute for observed stream, model, billing or network evidence.
    Only a fully successful run publishes an admissible qualification receipt.
    """
    del upstream_evidence
    route, root, destination = settings.route, settings.runtime_root, settings.qualification_file
    result: dict[str, Any] = {
        "ok": False,
        "checks": dict.fromkeys(QUALIFICATION_CHECKS, "FAIL"),
        "evidence_refs": [],
        "route_identity": route.identity if route else "",
        "error_code": "runtime_qualification_failed",
        "message": "运行环境资格验证未通过，请检查模型配置与验收证据后重试。",
    }
    probe = None
    host_identity: dict[str, str] = {}
    try:
        if (
            not owner_scope
            or route is None
            or root is None
            or destination is None
            or not root.is_absolute()
            or not destination.is_absolute()
            or root.is_symlink()
            or destination.is_symlink()
            or not destination.resolve().is_relative_to(root.resolve())
        ):
            raise _QualificationError("runtime_qualification_config_invalid")
        host_identity = qualification_host_identity()
        verify_installation()
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory = destination.parent / ("attempt-" + uuid.uuid4().hex)
        directory.mkdir(mode=0o700)
        candidate = _Probe(directory)
        candidate.initialize()
        probe = candidate
        owner_hash = hashlib.sha256(owner_scope.encode()).hexdigest()
        asyncio.run(_run_probe(settings, owner_hash, probe))
        if qualification_host_identity() != host_identity:
            raise _QualificationError("runtime_host_changed")
        result["checks"] = _checks(probe, route)
        if any(status != "PASS" for status in result["checks"].values()):
            raise _QualificationError("runtime_qualification_evidence_missing")
        result.update(ok=True, message="独立模型与本地执行器资格验证已通过。")
        result.pop("error_code")
    except BOUNDARY_ERRORS as exc:
        if probe is not None:
            assert route is not None
            result["checks"] = _checks(probe, route)
        result["error_code"] = (
            probe.error_code
            if probe is not None and probe.error_code
            else exc.code
            if isinstance(exc, _QualificationError)
            else "runtime_qualification_unavailable"
        )
    if probe is not None:
        assert route is not None and destination is not None
        evidence = {
            "schema": "xcmax.runtime-qualification-evidence.v1",
            "scenario": "two_step_compaction_restart_continuation",
            "created_at": datetime.now(UTC).isoformat(),
            "host_build": build_identity(),
            "codex_version": CODEX_VERSION,
            "host_identity": host_identity,
            "route_identity": route.identity,
            "route": route.runtime_identity(),
            "limits": {
                "model_calls": min(route.max_model_calls, 12),
                "max_output_tokens": min(route.max_output_tokens, 2048),
            },
            "ok": result["ok"],
            "checks": result["checks"],
            "models": probe.models,
            "network": probe.network,
            "recovery": probe.recovery,
            "probe": probe.snapshot(),
            "error_code": result.get("error_code"),
        }
        evidence_path = probe.directory / "evidence.json"
        evidence_text = json.dumps(evidence, ensure_ascii=False, indent=2)
        _write_private(evidence_path, evidence_text)
        result["evidence_refs"] = [str(evidence_path)]
        if result["ok"]:
            _write_private(
                destination,
                json.dumps(
                    {
                        "schema": "xcmax.runtime-qualification.v1",
                        "model_kind": "real",
                        "codex_version": CODEX_VERSION,
                        "host_identity": host_identity,
                        "route_identity": route.identity,
                        "checks": result["checks"],
                        "evidence_refs": result["evidence_refs"],
                        "evidence_sha256": {
                            str(evidence_path): hashlib.sha256(evidence_text.encode()).hexdigest()
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
    # A missing probe proves the preflight stopped before any upstream call.
    # Once a probe starts, even a lost response must never trigger silent retries.
    result["model_attempted"] = probe is not None
    return result
