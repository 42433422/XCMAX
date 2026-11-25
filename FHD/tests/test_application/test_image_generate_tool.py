"""Real session ownership and adapter HTTP receipts for the native image tool."""

import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest

from app.application.agent_runtime.chat import runtime_chat_payload
from app.application.market_llm import authentication
from app.application.market_llm.multimodal import safe_image_result_urls
from app.application.tools.workflow_tools.dispatch import (
    execute_registered_workflow_tool,
)
from app.db.models.user import Session, User
from app.domain.shared_services.conversation import modstore_adapter
from app.fastapi_routes.market_bridge.session_tokens import SQLSessionTokens
from app.infrastructure.auth.agent_mod_scope import bind_agent_actor_scope
from app.infrastructure.llm.model_admission import (
    _MODEL_IDENTITY,
    model_rate_limit_scope,
)
from app.utils.time import utc_now_naive

IMAGE = "data:image/png;base64,AA=="


@pytest.fixture
def image_runtime(dialogue_db, monkeypatch):
    factory = dialogue_db
    monkeypatch.setattr("app.db.HostSessionLocal", factory)
    Session.__table__.create(factory.kw["bind"])
    with factory.begin() as db:
        for owner in (1, 2):
            db.get(User, owner).tenant_id = owner + 6
            db.add(
                Session(
                    session_id=f"login-{owner}",
                    user_id=owner,
                    expires_at=utc_now_naive() + timedelta(hours=1),
                    market_access_token=f"synthetic-owner-{owner}",
                )
            )
    repository = SQLSessionTokens(factory, lambda: Session)
    monkeypatch.setattr(
        authentication,
        "load_session_ports",
        lambda: authentication.SessionPorts(
            lambda request: "",
            lambda sid: repository.read(sid, "access"),
            repository.owner,
            lambda user_id=None: repository.latest("access", user_id),
        ),
    )
    monkeypatch.setenv("MODSTORE_AUTH_TOKEN", "synthetic-process-owner")
    monkeypatch.setenv("MODSTORE_PLATFORM_URL", "https://market.invalid")
    monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
    remote = SimpleNamespace(
        requests=[],
        transports=[],
        status=200,
        payload={
            "ok": True,
            "images": [IMAGE],
            "provider": "openai",
            "model": "gpt-image-test",
            "billed": True,
            "charge_amount": "0.12",
            "usage": {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10},
            "request_id": "market-request-1",
            "operation": "image_generation",
        },
        timeout=False,
    )

    class ControlledTransport(httpx.AsyncBaseTransport):
        def __init__(self):
            self.loop = None
            self.closed = False
            remote.transports.append(self)

        async def handle_async_request(self, request):
            self.loop = asyncio.get_running_loop()
            remote.requests.append(
                {
                    "auth": request.headers["authorization"],
                    "body": json.loads(request.content),
                    "identity": _MODEL_IDENTITY.get(),
                }
            )
            if remote.timeout:
                raise httpx.ReadTimeout("synthetic timeout", request=request)
            return httpx.Response(remote.status, json=remote.payload)

        async def aclose(self):
            assert asyncio.get_running_loop() is self.loop
            self.closed = True

    monkeypatch.setattr(
        modstore_adapter._transport,
        "httpx_async_client",
        lambda **kwargs: httpx.AsyncClient(transport=ControlledTransport(), **kwargs),
    )
    context = {
        "user_id": "1",
        "actor_id": "1",
        "local_user_id": 1,
        "tenant_id": "7",
        "session_id": "chat-conversation-1",
        "_actor_authorization": bind_agent_actor_scope(session_id="login-1", user_id="1"),
        "idempotency_key": "agent:run-one:step-one",
    }
    return factory, context, remote


def execute(context, **params):
    return execute_registered_workflow_tool(
        "image_generate",
        "generate",
        {"prompt": "a blue bird", **params, "_runtime_context": context},
    )


@pytest.mark.parametrize("chat_session", ["", "login-2", "chat-conversation-1"])
def test_tool_uses_sealed_login_owner_and_preserves_billing_receipt(image_runtime, chat_session):
    _, context, remote = image_runtime
    context["session_id"] = chat_session
    result = execute(context)
    assert result["success"], result
    assert remote.requests[0]["auth"] == "Bearer synthetic-owner-1"
    assert result["request_id"] == remote.payload["request_id"]
    assert result["usage"] == remote.payload["usage"]
    assert result["billed"] is True and result["charge_amount"] == "0.12"
    assert result["client_request_id"] == remote.requests[0]["body"]["client_request_id"]


@pytest.mark.parametrize(
    "mutation", ["missing", "actor", "local_user", "tenant", "expired", "inactive"]
)
def test_tool_denies_unbound_or_revoked_identity_before_any_model_request(image_runtime, mutation):
    factory, context, remote = image_runtime
    if mutation == "missing":
        context.pop("_actor_authorization")
        context["session_id"] = ""
    elif mutation == "actor":
        context["actor_id"] = "2"
    elif mutation == "local_user":
        context["local_user_id"] = 2
    elif mutation == "tenant":
        context["tenant_id"] = "8"
    else:
        with factory.begin() as db:
            if mutation == "expired":
                db.query(Session).filter_by(session_id="login-1").one().expires_at = (
                    utc_now_naive() - timedelta(seconds=1)
                )
            else:
                db.get(User, 1).is_active = False
    with pytest.raises(PermissionError):
        authentication.authenticated_agent_session_id(context)
    assert execute(context)["success"] is False
    assert remote.requests == []


def test_tool_never_borrows_other_accounts_or_process_market_token(image_runtime):
    factory, context, remote = image_runtime
    context["session_id"] = ""
    with factory.begin() as db:
        db.query(Session).filter_by(session_id="login-1").one().market_access_token = ""
    assert execute(context)["success"] is False
    assert remote.requests == []


@pytest.mark.parametrize("running_loop", [False, True])
def test_generate_and_close_share_one_loop_and_keep_model_scope(image_runtime, running_loop):
    _, context, remote = image_runtime
    context["session_id"] = "login-1"

    async def invoke():
        return execute(context)

    with model_rate_limit_scope(context):
        result = asyncio.run(invoke()) if running_loop else execute(context)
    assert result["success"], result
    assert remote.requests[0]["identity"] == "tenant:7:actor:1"
    assert all(transport.closed for transport in remote.transports)


@pytest.mark.parametrize("failure", ["timeout", "pending", "gateway"])
def test_unknown_image_outcome_keeps_same_client_key_and_reconciliation_receipt(
    image_runtime, failure
):
    _, context, remote = image_runtime
    context["session_id"] = "login-1"
    remote.timeout = failure == "timeout"
    remote.status = 409 if failure == "pending" else 502
    remote.payload = {"detail": {"message": "pending", "request_id": "market-pending-1"}}
    results = [execute(context) for _ in range(2)]
    keys = [request["body"]["client_request_id"] for request in remote.requests]
    assert len(keys) == 2 and keys[0] == keys[1]
    for result in results:
        assert result["success"] is False
        assert result["outcome"] == "unknown" and result["reconciliation_required"] is True
        assert result["retryable"] is False and result["client_request_id"] == keys[0]
    if failure == "pending":
        assert results[0]["request_id"] == "market-pending-1"


@pytest.mark.parametrize("status", [401, 402, 403, 422, 429])
def test_confirmed_image_rejection_remains_definitive(image_runtime, status):
    _, context, remote = image_runtime
    context["session_id"] = "login-1"
    remote.status, remote.payload = status, {"detail": "not authorized"}
    result = execute(context)
    assert result["success"] is False and result["status_code"] == status
    assert not result.get("reconciliation_required")
    assert result["client_request_id"] == remote.requests[0]["body"]["client_request_id"]


@pytest.mark.parametrize("prompt", [17, "x" * 4001])
def test_tool_keeps_original_prompt_validation_before_paid_dispatch(image_runtime, prompt):
    _, context, remote = image_runtime
    context["session_id"] = "login-1"
    assert execute(context, prompt=prompt)["success"] is False
    assert not remote.requests


@pytest.mark.parametrize("pending", [False, True])
def test_native_executor_keeps_owner_receipt_durable_and_never_reissues_paid_request(
    image_runtime, monkeypatch, tmp_path, pending
):
    from app.application.agent_orchestrator import tool_permission
    from app.application.agent_orchestrator.run_models import AgentStep
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor

    _, context, remote = image_runtime
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "claims.sqlite"))
    tool_permission.drop_process_idempotency_memory()
    if pending:
        remote.status = 409
        remote.payload = {"detail": {"message": "pending", "request_id": "market-pending-1"}}
    step = AgentStep(
        node_id="image",
        tool_id="image_generate",
        action="generate",
        params={"prompt": "a bird"},
    )
    executor = AgentToolExecutor()
    first = executor.execute(step, runtime_context=context)
    assert first["success"] is not pending, first
    assert first["client_request_id"] == remote.requests[0]["body"]["client_request_id"]
    assert bool(first.get("reconciliation_required")) is pending
    tool_permission.drop_process_idempotency_memory()
    second = executor.execute(step, runtime_context=context)
    assert second == first
    assert len(remote.requests) == 1
    tool_permission.drop_process_idempotency_memory()


def test_unrenderable_paid_receipt_is_retained_as_unknown(image_runtime):
    _, context, remote = image_runtime
    remote.payload["images"] = ["data:image/svg+xml;base64,PHN2Zz4="]
    result = execute(context)
    assert result["success"] is False and result["reconciliation_required"] is True
    assert result["billed"] is True and result["request_id"] == "market-request-1"
    assert result["usage"] == remote.payload["usage"]


@pytest.mark.parametrize("key", [None, "short", "bad key", "x" * 129])
def test_unrecoverable_request_key_is_rejected_before_dispatch(image_runtime, key):
    _, context, remote = image_runtime
    context.pop("idempotency_key")
    result = execute(context, **({"client_request_id": key} if key is not None else {}))
    assert result["success"] is False and not remote.requests


@pytest.mark.parametrize(
    "url",
    [
        "data:image/svg+xml;base64,PHN2Zz4=",
        "data:image/gif;base64,R0lG",
        "data:image/png,unencoded",
        "data:image/png;base64,AA==\n[leaked](https://other.test)",
        "https://",
        "https://user:secret@example.test/a.png",
        "https://example.test/a.png)\n[leaked](https://other.test)",
    ],
)
def test_unsafe_image_results_are_not_rendered(url):
    assert safe_image_result_urls([url]) == []


def test_image_markdown_targets_are_encoded_by_the_active_adapter():
    assert safe_image_result_urls(["https://example.test/image(1).png"]) == [
        "https://example.test/image%281%29.png"
    ]


def _image_receipt(name, **output):
    return {
        "call_id": name,
        "child_run_id": f"image-child-{name}",
        "child_task_id": f"image-task-{name}",
        "tool_id": "image_generate",
        "action": "generate",
        "params": {"prompt": f"Generate {name}"},
        "state": "completed",
        "read_only": False,
        "receipt": {
            "status": "completed",
            "success": True,
            "verified": True,
            "result": {
                "success": True,
                "images": [f"https://example.test/{name}.png"],
                "request_id": f"market-{name}",
                "billed": True,
                **output,
            },
        },
    }


def _image_runtime_response(rows, *, reviewed=False):
    from app.application.agent_orchestrator.run_models import AgentRun
    from app.domain.task_lifecycle.agent_runtime_contract import (
        GOAL_PROTOCOL,
        build_goal_contract,
        canonical_digest,
        goal_evidence_snapshot,
        validate_goal_review,
    )
    from app.domain.task_lifecycle.agent_runtime_results import (
        base_runtime_result,
        classify_runtime_result,
    )

    run = AgentRun(user_id="1", message="生成图片", run_id="image-run")
    contract = build_goal_contract(run)
    result = base_runtime_result(run.run_id)
    result["output"] = "已核对图片生成回执。"
    result["artifacts"] = [{"artifact_type": "image", "uri": "https://example.test/saved.png"}]
    metadata = {"goal_contract": contract}
    if reviewed:
        snapshot = goal_evidence_snapshot(contract, rows, result["output"])
        review, errors = validate_goal_review(
            {
                "goals": [
                    {
                        "goal_id": "images",
                        "source_id": "request",
                        "source": "生成图片",
                        "kind": "write",
                        "status": "satisfied",
                        "evidence_ids": [row["child_run_id"] for row in rows],
                        "reason": "Each supplied business receipt is independently verified.",
                    }
                ],
                "violations": [],
                "uncovered_sources": [],
                "feedback": "",
            },
            contract,
            snapshot,
            result["output"],
        )
        assert errors == []
        report = {
            "protocol": GOAL_PROTOCOL,
            "goal_digest": contract["digest"],
            "evidence_digest": snapshot["digest"],
            "response_digest": canonical_digest(result["output"]),
            "review": review,
            "status": "verified",
            "accepted": True,
            "feedback": "",
        }
        metadata["goal_verification"] = {
            **report,
            "report_digest": canonical_digest(report),
        }
    classify_runtime_result(result, rows, metadata, "business", "completed")
    return runtime_chat_payload(result, conversation_id="image-conversation")


def test_runtime_response_preserves_every_verified_image_receipt_and_artifact():
    rows = [_image_receipt("first"), _image_receipt("second")]
    result = _image_runtime_response(rows, reviewed=True)
    assert result["success"] is True and result["business_completed"] is True
    assert result["data"]["text"] == result["response"]
    assert result["data"]["business_receipts"] == rows
    assert result["data"]["artifacts"] == [
        {"artifact_type": "image", "uri": "https://example.test/saved.png"}
    ]
    assert all(call["success"] and call["verified"] for call in result["data"]["tool_calls"])


@pytest.mark.parametrize("failure", ["failed", "unknown", "false_receipt"])
def test_runtime_image_receipts_never_promote_mixed_or_unconfirmed_results(failure):
    unconfirmed = _image_receipt("unconfirmed")
    if failure == "failed":
        unconfirmed["state"] = "failed"
        unconfirmed["receipt"].update(status="failed", success=False, verified=False)
    elif failure == "unknown":
        # A stale completed receipt cannot override an explicit uncertain effect.
        unconfirmed["receipt"]["result"].update(outcome="unknown", reconciliation_required=True)
    else:
        unconfirmed["receipt"].update(success=False, verified=False)
    rows = [_image_receipt("confirmed"), unconfirmed]
    result = _image_runtime_response(rows)
    assert result["success"] is False and result["business_completed"] is False
    assert result["data"]["text"] == result["response"]
    assert result["data"]["business_receipts"] == rows
    assert "https://example.test/unconfirmed.png" not in result["response"]
    assert result["retryable"] is False
    if failure in {"failed", "unknown"}:
        assert result["requires_reconciliation"] is True
        assert result["execution_state"] == ("partial" if failure == "failed" else "unknown")


def test_unknown_image_keeps_billing_evidence_without_claiming_completion():
    row = _image_receipt("unconfirmed", outcome="unknown", reconciliation_required=True)
    result = _image_runtime_response([row])
    assert result["success"] is False and result["requires_reconciliation"] is True
    assert result["business_completed"] is False and result["execution_state"] == "unknown"
    assert result["data"]["business_receipts"][0]["receipt"]["result"]["billed"] is True
    assert result["runtime_context_update"]["agent_runtime_run_id"] == "image-run"
    assert "https://example.test/unconfirmed.png" not in result["response"]


def test_single_verified_image_still_requires_the_original_goal_review():
    rows = [_image_receipt("single")]
    unreviewed = _image_runtime_response(rows)
    assert unreviewed["success"] is False and unreviewed["business_completed"] is False
    assert unreviewed["data"]["error_code"] == "goal_verification_required"
    reviewed = _image_runtime_response(rows, reviewed=True)
    assert reviewed["success"] is True and reviewed["business_completed"] is True
    assert reviewed["data"]["business_receipts"] == rows
