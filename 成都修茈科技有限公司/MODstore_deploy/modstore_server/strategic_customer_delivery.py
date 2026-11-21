"""Serve completed native output bytes to the customer named in the approved goal.

The original SQL decisions, customer agreements and payment ownership authorize
the transfer. FastAPI/Starlette provides the HTTP response; a successful download
does not create customer acceptance or a measured business outcome.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import HTTPException
from fastapi.responses import Response
from sqlalchemy import select

from modstore_server.db.db_base import get_session_factory
from modstore_server.db.strategic import StrategicDecision
from modstore_server.integrations.vibe_adapter import VibePathError, ensure_within_workspace
from modstore_server.strategic_customer_outcomes import load_customer_goal_bindings
from modstore_server.strategic_portfolio import PortfolioError, portfolio_status

_MAX_ARTIFACT_BYTES = 64_000_000


def _customer_agreement(user: Any, order_no: str, goal_id: str) -> dict[str, str]:
    from modstore_server.customer_value_lifecycle_api import _authoritative_order

    if user.is_admin or not user.is_enterprise:
        raise HTTPException(403, "仅原企业客户可读取交付文件")
    _authoritative_order(order_no, int(user.id))
    try:
        return load_customer_goal_bindings(int(user.id), order_no, [goal_id])[0]
    except PortfolioError as exc:
        raise HTTPException(409, "客户目标已改变或缺少有效协议") from exc


def _artifacts(
    status: dict[str, Any], agreement: dict[str, str]
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    authorization = status.get("authorization") or {}
    if authorization.get("proposal_sha256") != status.get("proposal_sha256") or authorization.get(
        "user_id"
    ) != status.get("owner_user_id"):
        return []
    matched = []
    for opportunity in status["opportunities"]:
        if agreement not in (opportunity.get("customer_goal_bindings") or []):
            continue
        task = status.get("tasks", {}).get(opportunity["opportunity_id"], {})
        if task.get("status") != "completed" or not task.get("completed_at"):
            continue
        receipt = task.get("execution_receipt") or {}
        for artifact in receipt.get("delivered_artifacts") or []:
            if (
                isinstance(artifact, dict)
                and artifact.get("source") == "native_direct_python_tenant_output"
                and artifact.get("artifact_id")
                and artifact.get("artifact_sha256")
                and artifact.get("output_path")
            ):
                matched.append((opportunity, artifact))
    return matched


def list_customer_deliveries(
    user: Any, *, order_no: str, goal_id: str, after: int = 0
) -> dict[str, Any]:
    agreement = _customer_agreement(user, order_no, goal_id)
    # Text prefilters reduce the SQL page; exact persisted bindings below remain
    # authoritative. A continuation cursor prevents the first page hiding work.
    with get_session_factory()() as session:
        ids = session.execute(
            select(StrategicDecision.id, StrategicDecision.decision_id)
            .where(
                StrategicDecision.scope == "strategy_portfolio",
                StrategicDecision.id > after,
                StrategicDecision.decision_payload_json.contains(
                    json.dumps(agreement["customer_ref"]), autoescape=True
                ),
            )
            .order_by(StrategicDecision.id)
            .limit(101)
        ).all()
    items = []
    query = urlencode({"order_no": order_no, "customer_goal_id": goal_id})
    for _row_id, decision_id in ids[:100]:
        try:
            status = portfolio_status(decision_id)
        except PortfolioError:
            continue
        for opportunity, artifact in _artifacts(status, agreement):
            components = (decision_id, opportunity["opportunity_id"], artifact["artifact_id"])
            route = "/".join(quote(str(value), safe="") for value in components)
            items.append(
                {
                    "artifact_id": artifact["artifact_id"],
                    "artifact_sha256": artifact["artifact_sha256"],
                    "filename": Path(artifact["output_path"]).name,
                    "download_url": f"/api/customer-value/deliveries/{route}?{query}",
                    "completed_at": status["tasks"][opportunity["opportunity_id"]]["completed_at"],
                }
            )
    return {"items": items, "next_cursor": int(ids[99][0]) if len(ids) > 100 else None}


def download_customer_delivery(
    user: Any,
    *,
    decision_id: str,
    opportunity_id: str,
    artifact_id: str,
    order_no: str,
    goal_id: str,
) -> Response:
    agreement = _customer_agreement(user, order_no, goal_id)
    try:
        status = portfolio_status(decision_id)
    except PortfolioError as exc:
        raise HTTPException(404, "交付文件不存在") from exc
    selected = [
        (opportunity, artifact)
        for opportunity, artifact in _artifacts(status, agreement)
        if opportunity["opportunity_id"] == opportunity_id
        and artifact["artifact_id"] == artifact_id
    ]
    if len(selected) != 1:
        raise HTTPException(404, "交付文件不存在")
    opportunity, artifact = selected[0]
    try:
        root = ensure_within_workspace(
            opportunity["input_data"]["workspace_root"], user_id=status["owner_user_id"]
        )
        relative = Path(artifact["output_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("invalid relative artifact path")
        path = ensure_within_workspace(root / relative, user_id=status["owner_user_id"])
        path.relative_to(root)
        if not path.is_file() or path.stat().st_size > _MAX_ARTIFACT_BYTES:
            raise ValueError("artifact unavailable")
        with path.open("rb") as source:
            content = source.read(_MAX_ARTIFACT_BYTES + 1)
        if (
            len(content) > _MAX_ARTIFACT_BYTES
            or hashlib.sha256(content).hexdigest() != artifact["artifact_sha256"]
        ):
            raise ValueError("artifact bytes changed")
    except (KeyError, OSError, ValueError, VibePathError) as exc:
        raise HTTPException(409, "交付文件不可读取或与已完成制品不一致") from exc
    # Send the verified byte snapshot, never reopen a mutable path after hashing.
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=utf-8''{quote(path.name, safe='')}",
            "ETag": f'"{artifact["artifact_sha256"]}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
