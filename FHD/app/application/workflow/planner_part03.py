# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.workflow.planner")


def _get_planner_http_client() -> _facade().httpx.Client:
    global _planner_http_client
    if _facade()._planner_http_client is None:
        _facade()._planner_http_client = _facade().httpx.Client(
            timeout=_facade().httpx.Timeout(20.0, connect=10.0),
            limits=_facade().httpx.Limits(max_keepalive_connections=10, max_connections=20),
            trust_env=False,
        )
    return _facade()._planner_http_client


def _filter_tool_registry_for_profile(
    tool_registry: dict[str, _facade().Any], profile: str
) -> dict[str, _facade().Any]:
    """
    - normal：剔除 pro_only 工具与动作（普通界面走槽位/共享工具）。
    - pro_default：剔除 normal_only 工具与动作（全专业链路不暴露纯普通槽位工具）。
    """
    filtered: dict[str, _facade().Any] = {}
    for tool_id, spec in tool_registry.items():
        if not isinstance(spec, dict):
            continue
        tool_av = str(spec.get("availability") or "shared").strip().lower()
        if profile == "normal" and tool_av == "pro_only":
            continue
        if profile == "pro_default" and tool_av == "normal_only":
            continue
        actions = spec.get("actions") or {}
        if not isinstance(actions, dict):
            continue
        kept_actions: dict[str, _facade().Any] = {}
        for aname, ameta in actions.items():
            if not isinstance(ameta, dict):
                continue
            av = str(ameta.get("availability") or "shared").strip().lower()
            if profile == "normal" and av == "pro_only":
                continue
            if profile == "pro_default" and av == "normal_only":
                continue
            kept_actions[aname] = ameta
        if not kept_actions:
            continue
        new_spec = dict(spec)
        new_spec["actions"] = kept_actions
        filtered[tool_id] = new_spec
    return filtered
