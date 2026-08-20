# mypy: disable-error-code="attr-defined, misc, no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.mod_employee_agent_runner")


class EmployeeAgentRunner(_facade()._EmployeeAgentRunnerPart01Mixin):
    """ReAct agent loop for employee_pack employees.

    Usage in a generated employee file::

        async def run(payload, ctx):
            runner = ctx.get("agent_runner")  # injected by blueprints.py
            if runner is None:
                from modstore_server.mod_employee_agent_runner import EmployeeAgentRunner
                runner = EmployeeAgentRunner(ctx)
            task = payload.get("task") or payload.get("message") or json.dumps(payload)
            return await runner.run(task, system_prompt=SYSTEM_PROMPT)
    """


def _try_parse_json(
    text: str,
) -> _facade().Optional[_facade().Dict[str, _facade().Any]]:
    """Lenient JSON parser: strip fences and try multiple extract strategies."""
    t = (text or "").strip()
    t = (
        _facade()
        .re.sub("<think\\b[^>]*>.*?</think>", "", t, flags=_facade().re.I | _facade().re.S)
        .strip()
    )
    if t.startswith("```"):
        t = _facade().re.sub("^```(?:json)?\\s*", "", t, flags=_facade().re.I)
        t = _facade().re.sub("\\s*```\\s*$", "", t).strip()
    try:
        data = _facade().json.loads(t)
        return data if isinstance(data, dict) else None
    except (_facade().json.JSONDecodeError, ValueError):
        pass
    decoder = _facade().json.JSONDecoder()
    candidates: _facade().List[tuple[int, int, _facade().Dict[str, _facade().Any]]] = []
    for index, char in enumerate(t):
        if char != "{":
            continue
        try:
            data, _end = decoder.raw_decode(t[index:])
        except (_facade().json.JSONDecodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        score = 4 if "tool" in data else 4 if "answer" in data else 2 if "status" in data else 1
        candidates.append((score, index, data))
    if candidates:
        return max(candidates, key=lambda item: (item[0], item[1]))[2]
    return None


def build_agent_runner(
    ctx: _facade().Dict[str, _facade().Any],
    *,
    max_rounds: _facade().Optional[int] = None,
) -> EmployeeAgentRunner:
    """Convenience factory; used by generated blueprints.py."""
    workspace_root = str(ctx.get("workspace_root") or ".")
    return _facade().EmployeeAgentRunner(ctx, max_rounds=max_rounds, workspace_root=workspace_root)
