"""Shared boundary conversions, without transport or permission policy."""

from typing import Protocol, cast

from fastapi import Request

from .port_contracts import ErrorPolicy, JsonObject


async def read_json_object(request: Request, errors: ErrorPolicy) -> JsonObject | None:
    try:
        payload = await request.json()
    except errors.recoverable():
        return None
    return payload if isinstance(payload, dict) else None


class ModelDump(Protocol):
    def model_dump(self) -> JsonObject: ...


def installation_payload(result: object) -> JsonObject:
    if hasattr(result, "model_dump"):
        return cast(ModelDump, result).model_dump()
    if isinstance(result, dict):
        return result
    return {"result": str(result)}
