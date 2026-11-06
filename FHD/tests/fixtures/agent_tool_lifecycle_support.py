"""Shared HTTP driver and input contracts for tool lifecycle acceptance."""

from __future__ import annotations

from datetime import datetime
from statistics import quantiles
from typing import Any
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

SHANGHAI = ZoneInfo("Asia/Shanghai")


SECRET = "sk-testfix1"


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name"],
    "properties": {
        "name": {"type": "string"},
        "qty": {"type": "integer"},
        "price": {"type": "number"},
        "ok": {"type": "boolean", "default": True},
        "tags": {"type": "array", "items": {"type": "string"}},
        "meta": {
            "type": "object",
            "additionalProperties": False,
            "required": ["sku"],
            "properties": {
                "sku": {"type": "string"},
                "note": {"type": "string", "default": "n"},
            },
        },
    },
}


def _p95(samples: list[float]) -> float:
    if len(samples) < 2:
        return samples[0] if samples else 0.0
    return quantiles(samples, n=100, method="inclusive")[94]


class Suite:
    def __init__(self, client: TestClient, holder: dict[str, int]) -> None:
        self.client = client
        self.holder = holder
        self.results: list[dict[str, Any]] = []

    def call(
        self,
        method: str,
        path: str,
        *,
        role: str = "admin",
        actor: str = "admin-1",
        body: dict | None = None,
        params: dict | None = None,
        tenant: int = 1,
    ) -> Any:
        self.holder["tenant"] = tenant
        headers = {"X-Actor-Role": role, "X-Actor-Id": actor}
        if role != "admin":
            headers["X-Employee-Id"] = actor
        response = self.client.request(method, path, json=body, params=params, headers=headers)
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text}
        return response.status_code, payload

    def record(
        self,
        case_id: str,
        request: dict,
        response: Any,
        ok: bool,
        detail: str = "",
        *,
        status: str | None = None,
    ) -> None:
        state = status or ("pass" if ok else "fail")
        self.results.append(
            {
                "id": case_id,
                "status": state,
                "request": request,
                "response": response,
                "detail": detail,
                "at_shanghai": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
            }
        )


def _data(payload: dict) -> dict:
    return payload.get("data") or {}


def _err(payload: dict) -> dict:
    return payload.get("error") or {}


def _base_body(key: str, **extra: Any) -> dict:
    body = {
        "tool_key": key,
        "name": key,
        "description": f"desc {key}",
        "input_schema": SCHEMA,
        "tenant_id": 999,
    }
    body.update(extra)
    return body
