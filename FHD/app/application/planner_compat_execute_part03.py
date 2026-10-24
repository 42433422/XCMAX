# mypy: disable-error-code="valid-type"
"""Batch compatibility chat uses the same routing and persistence as a single turn."""

from __future__ import annotations

import importlib
import uuid


def _facade():
    return importlib.import_module("app.application.planner_compat_execute")._facade()


async def execute_compat_chat_batch(
    request: _facade().Request, body: _facade().XcagiCompatChatBatchBody
) -> dict[str, _facade().Any]:
    msgs = [str(x).strip() for x in body.messages or [] if str(x).strip()]
    if not msgs:
        raise _facade().HTTPException(status_code=400, detail="messages 须为非空字符串数组")
    _facade().assert_p2_elevated_claim_or_raise(request)
    values = body.model_dump(exclude={"messages", "context"})
    rolling_ctx = dict(body.context or {})
    batch_turn = str(rolling_ctx.get("turn_id") or uuid.uuid4().hex)
    results = []
    for index, text in enumerate(msgs):
        context = {
            **rolling_ctx,
            "turn_id": uuid.uuid5(uuid.NAMESPACE_URL, f"{batch_turn}:{index}").hex,
        }
        single = _facade().XcagiCompatChatBody(message=text, context=context, **values)
        try:
            payload = await _facade().execute_compat_chat(request, single)
        except (_facade().HTTPException, *_facade().RECOVERABLE_ERRORS) as exc:
            err = (
                exc
                if isinstance(exc, _facade().HTTPException)
                else _facade()._xcagi_chat_http_exc(exc)
            )
            payload = {"success": False, "message": str(err.detail), "response": str(err.detail)}
        update = (payload.get("data") or {}).get("runtime_context")
        if isinstance(update, dict):
            rolling_ctx = update
        results.append(payload)
    return {
        "success": all(item.get("success") for item in results),
        "batch": True,
        "results": results,
        "count": len(results),
    }
