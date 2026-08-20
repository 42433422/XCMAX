# mypy: disable-error-code="index, union-attr"
"""Authentication, parsing, mentions, and workforce snapshot helpers."""

from __future__ import annotations

import json
import os
import re
import secrets
from typing import Any, Dict, List, Optional

from fastapi import Header, Request

from modstore_server.api.deps import get_current_user, require_admin
from modstore_server.models import User
from modstore_server.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

_MENTION_RE = re.compile(r"@([a-zA-Z0-9][a-zA-Z0-9_-]{0,127})")
_HOLLOW_DUTY_HANDLERS = frozenset({"echo", "llm_md"})


def _jloads(text: str, default: Any) -> Any:
    raw = (text or "").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except RECOVERABLE_ERRORS:
        return default


def _extract_mentions_from_text(text: str) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for m in _MENTION_RE.findall(text or ""):
        s = str(m or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _internal_api_key() -> str:
    return (
        os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY")
        or os.environ.get("MODSTORE_INTERNAL_API_KEY")
        or os.environ.get("XCAGI_CS_INTAKE_LINK_SECRET")
        or ""
    ).strip()


def _has_valid_internal_api_key(request: Request) -> bool:
    expected = _internal_api_key()
    got = (request.headers.get("x-internal-api-key") or "").strip()
    return bool(expected and got and secrets.compare_digest(got, expected))


def _require_admin_or_internal(
    request: Request,
    authorization: Optional[str] = Header(None),
) -> Optional[User]:
    """Read-only service bridge for FHD mobile sync; writes still require admin JWT."""

    if _has_valid_internal_api_key(request):
        return None
    return require_admin(get_current_user(authorization))


def _workforce_assignment_snapshot(planned: set[str]) -> Dict[str, Any]:
    """Derive real assignment and shell counts from reviewed duty SSOTs."""

    from modstore_server.duty_workforce_contracts import (
        load_reviewed_duty_manifest,
        workforce_contract_map,
    )
    from modstore_server.employee_runtime import parse_employee_config_v2

    contracts = workforce_contract_map()
    assigned_ids: list[str] = []
    shell_ids: list[str] = []
    for employee_id in sorted(planned):
        contract = (
            contracts.get(employee_id) if isinstance(contracts.get(employee_id), dict) else {}
        )
        trigger = contract.get("trigger") if isinstance(contract.get("trigger"), dict) else {}
        acceptance = (
            contract.get("acceptance") if isinstance(contract.get("acceptance"), list) else []
        )
        assigned = all(
            (
                str(contract.get("mission") or "").strip(),
                str(contract.get("mode") or "").strip(),
                str(contract.get("risk_level") or "").strip(),
                bool(str(trigger.get("cron") or "").strip() or trigger.get("events")),
                bool([item for item in acceptance if str(item or "").strip()]),
            )
        )
        if assigned:
            assigned_ids.append(employee_id)

        try:
            manifest = load_reviewed_duty_manifest(employee_id)
            config = parse_employee_config_v2(manifest)
            actions = config.get("actions") if isinstance(config.get("actions"), dict) else {}
            if isinstance(actions.get("actions"), dict):
                actions = actions["actions"]
            handlers = {
                str(item).strip() for item in actions.get("handlers") or [] if str(item).strip()
            }
        except BOUNDARY_ERRORS:  # noqa: BLE001 - missing/invalid reviewed runtime is a shell
            handlers = set()
        if not handlers or handlers.issubset(_HOLLOW_DUTY_HANDLERS):
            shell_ids.append(employee_id)

    return {
        "assigned_count": len(assigned_ids),
        "assigned_employee_ids": assigned_ids,
        "shell_count": len(shell_ids),
        "shell_employee_ids": shell_ids,
    }
