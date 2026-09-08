"""Authenticated Para adapter. No guest login, automatic merge or workspace reuse."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from urllib.parse import quote

import httpx


class ParaUnavailable(RuntimeError):
    pass


class ParaClient:
    def __init__(self):
        self.base = os.environ.get("MODSTORE_PARA_API_BASE", "").rstrip("/")
        token = os.environ.get("MODSTORE_PARA_AUTH_TOKEN", "")
        if not self.base or not token:
            raise ParaUnavailable("service_identity_not_configured")
        self.client = httpx.Client(
            base_url=self.base,
            timeout=10,
            trust_env=False,
            headers={"Authorization": f"Bearer {token}"},
        )

    def close(self):
        self.client.close()

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        try:
            response = self.client.request(method, path, json=body)
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise ParaUnavailable("invalid_para_response")
            return result
        except (httpx.HTTPError, ValueError) as exc:
            # Never persist exception bodies, URLs, headers, or raw executor logs.
            raise ParaUnavailable(type(exc).__name__) from None

    def devices(self) -> list[dict]:
        return self.request("GET", "/api/devices").get("devices", [])

    def tasks(self) -> list[dict]:
        return self.request("GET", "/api/tasks").get("tasks", [])

    def task(self, task_id: str) -> dict:
        task = self.request("GET", "/api/tasks/" + quote(task_id, safe="")).get(
            "task", {}
        )
        if not task.get("id") or not task.get("status"):
            raise ParaUnavailable("task_status_missing")
        return task

    def submit(self, body: dict) -> dict:
        return self.request("POST", "/api/tasks", body).get("task", {})


def age_seconds(value: str, now: float) -> float:
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return max(0, now - date.replace(tzinfo=date.tzinfo or UTC).timestamp())
    except (ValueError, TypeError, AttributeError):
        return float("inf")


def device_view(raw: dict, now: float) -> dict:
    caps = raw.get("capabilities") or {}
    stale = age_seconds(raw.get("lastSeen", ""), now) > 90
    tools = [
        {k: t.get(k) for k in ("toolName", "status", "currentTask")}
        for t in raw.get("tools", [])
        if isinstance(t, dict)
    ]
    return {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "status": "stale" if stale else raw.get("status", "unknown"),
        "last_seen": raw.get("lastSeen"),
        "tools": tools,
        "platform": caps.get("platform", "unknown"),
        "server_bridge": caps.get("server_bridge") is True,
        "preflight": caps.get("tool_preflight", {}),
        "source": "para:/api/devices",
        "observed_at": now,
    }


def choose_device(
    devices: list[dict], request: dict, now: float
) -> tuple[dict | None, str]:
    preferred = os.environ.get("MODSTORE_PARA_DEVICE_ID", "")
    target = request.get("target", "mac")
    tool = request.get("tool", "codex")
    for raw in devices:
        caps = raw.get("capabilities") or {}
        if target == "mac" and raw.get("id") != preferred:
            continue
        if target == "windows" and caps.get("platform") != "windows":
            continue
        if caps.get("server_bridge") or raw.get("status") != "online":
            continue
        if age_seconds(raw.get("lastSeen", ""), now) > 90:
            continue
        tools = raw.get("tools", [])
        if any(t.get("status") == "running" for t in tools):
            continue
        if not any(
            t.get("toolName") == tool and t.get("status") == "idle" for t in tools
        ):
            continue
        probe = (caps.get("tool_preflight") or {}).get(tool, {})
        if not (
            probe.get("ok") is True
            and age_seconds(probe.get("checked_at", ""), now) <= 90
        ):
            continue
        return raw, ""
    return None, "waiting_for_device_or_verified_tool"


def execution_view(raw: dict) -> dict:
    return {
        "id": raw.get("id"),
        "status": raw.get("status", "unknown"),
        "source": "para:/api/tasks",
        "merge_commit_sha": raw.get("merge_commit_sha"),
        "subtasks": [
            {
                k: s.get(k)
                for k in (
                    "id",
                    "device_id",
                    "device_name",
                    "tool_name",
                    "status",
                    "branch_name",
                    "progress",
                )
            }
            for s in raw.get("subTasks", [])
            if isinstance(s, dict)
        ],
    }
