"""Task-bound model transport and control receipts for the existing hosted worker."""

from __future__ import annotations

import json
from typing import Any

import anyio
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from modstore_server import strategic_remote_bridge as bridge
from modstore_server.strategic_portfolio import PortfolioError

router = APIRouter(prefix="/strategic-runs", tags=["strategic-remote-report"])


class _OwnedModelStream(StreamingResponse):
    """Also close a prefetched upstream when the client leaves before ASGI starts."""

    def __init__(self, content: Any, close_source: Any):
        super().__init__(
            content,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store"},
        )
        self.close_source = close_source

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self.close_source()


def require_dispatch_service(authorization: str = Header(default="")) -> str:
    from modstore_server.mac_control_dispatch_api import require_dispatch_service as require

    return require(authorization)


def _failure(exc: PortfolioError) -> HTTPException:
    return HTTPException(409, str(exc))


@router.post("/{request_id}/claim")
def claim(
    request_id: str,
    body: dict[str, Any],
    actor: str = Depends(require_dispatch_service),
):
    try:
        if bridge.read_request(request_id)[0]["kind"] == "github_opencode_workspace":
            from modstore_server.strategic_workspace_grants import claim_phase

            return claim_phase(request_id, body)
        return bridge.claim_report(request_id, body)
    except PortfolioError as exc:
        raise _failure(exc) from exc


@router.post("/{request_id}/result")
def result(
    request_id: str,
    body: dict[str, Any],
    actor: str = Depends(require_dispatch_service),
):
    try:
        return bridge.report_result(request_id, body)
    except PortfolioError as exc:
        raise _failure(exc) from exc


def _token(authorization: str) -> str:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token or token.strip() != token:
        raise HTTPException(401, "task-bound model grant required")
    return token


@router.post("/{request_id}/task-grant")
def task_grant(request_id: str, body: dict[str, Any], authorization: str = Header(default="")):
    from modstore_server.strategic_workspace_grants import bind_task

    try:
        return bind_task(request_id, _token(authorization), body)
    except PortfolioError as exc:
        raise _failure(exc) from exc


@router.post("/{request_id}/close-grant")
def close_grant(request_id: str, body: dict[str, Any], authorization: str = Header(default="")):
    from modstore_server.strategic_workspace_grants import close_grant as close

    try:
        return close(request_id, _token(authorization), body)
    except PortfolioError as exc:
        raise _failure(exc) from exc


@router.get("/{request_id}/v1/models")
def models(request_id: str, authorization: str = Header(default="")):
    try:
        with bridge.model_scope(request_id, _token(authorization)) as binding:
            return {
                "object": "list",
                "data": [{"object": "model", "id": binding["model"], "owned_by": "xcmax"}],
            }
    except PortfolioError as exc:
        raise _failure(exc) from exc


@router.post("/{request_id}/v1/responses")
async def responses(request_id: str, request: Request, authorization: str = Header(default="")):
    from modstore_server import strategic_responses
    from modstore_server.platform_llm_scope import platform_llm_scope
    from modstore_server.strategic_portfolio_usage import portfolio_usage_scope

    token = _token(authorization)
    raw = await request.body()
    if len(raw) > 2_000_000:
        raise HTTPException(413, "remote model request exceeds 2000000 bytes")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(400, "invalid Responses JSON") from exc
    source = None
    try:
        with bridge.model_scope(request_id, token) as approved:
            if not isinstance(payload, dict) or payload.get("model") != approved["model"]:
                raise PortfolioError("remote model differs from the approved route")
            if payload.get("stream") not in (None, False, True):
                raise PortfolioError("invalid Responses stream field")
            if payload.get("stream") is not True:
                return await strategic_responses.budgeted_responses(
                    payload,
                    provider=approved["provider"],
                    caller_binding=approved.get("caller_binding"),
                )
            source = strategic_responses.budgeted_responses_stream(
                payload,
                provider=approved["provider"],
                caller_binding=approved.get("caller_binding"),
            )
            first = await anext(source)
    except StopAsyncIteration:
        raise HTTPException(502, "upstream stream completed without events") from None
    except PortfolioError as exc:
        raise _failure(exc) from exc

    binding = approved["binding"]
    closed = False

    async def close_source():
        nonlocal closed
        if closed:
            return
        # Cleanup survives Starlette's ordinary disconnect cancellation. Root
        # SDK cleanup keeps unresolved usage reserved if close cannot complete.
        with (
            anyio.move_on_after(5, shield=True),
            platform_llm_scope(),
            portfolio_usage_scope(
                binding["decision_id"],
                binding["opportunity_id"],
                binding["lease_token"],
            ),
        ):
            await source.aclose()
        closed = True

    async def events():
        event = first
        try:
            while True:
                # These are SDK-decoded events, not a second upstream SSE parser.
                yield (
                    "data: " + json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n\n"
                ).encode()
                try:
                    with bridge.model_scope(request_id, token):
                        event = await anext(source)
                except StopAsyncIteration:
                    return
        except PortfolioError as exc:
            yield (
                "data: "
                + json.dumps(
                    {
                        "type": "error",
                        "code": "strategic_budget_stopped",
                        "message": str(exc),
                    }
                )
                + "\n\n"
            ).encode()
        finally:
            # Re-enter only for cleanup, even after revocation. No ContextVar
            # token spans yield or crosses Starlette's iterator/close tasks.
            await close_source()

    return _OwnedModelStream(events(), close_source)
