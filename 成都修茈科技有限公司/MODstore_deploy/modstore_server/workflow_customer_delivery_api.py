"""Customer-only reads of native workflow files and exact receipt attribution."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import HTTPException
from fastapi.responses import Response
from sqlalchemy import select

from modstore_server.customer_service_tools import json_loads
from modstore_server.integrations.vibe_adapter import VibePathError
from modstore_server.models import (
    CustomerValueReceipt,
    User,
    WorkflowExecution,
    get_session_factory,
)
from modstore_server.strategic_customer_delivery import _customer_agreement
from modstore_server.strategic_portfolio import digest
from modstore_server.workflow_customer_delivery import (
    ARTIFACT_SOURCE,
    load_completed_delivery,
    read_artifact_bytes,
)

_ARTIFACT = re.compile(r"^workflow-file-([1-9][0-9]*)-([1-9][0-9]*)-([0-9a-f]{24})$")


def _delivery(
    db: Any, user: Any, execution_id: int, artifact_id: str, agreement: dict[str, str]
) -> tuple[dict[str, Any], dict[str, Any], datetime]:
    try:
        binding, produced = load_completed_delivery(db, execution_id)
        contract = binding["customer_delivery"]
        if contract["user_id"] != user.id or contract["goal"] != agreement:
            raise ValueError("customer or original agreement differs")
        rows = [row for row in produced["artifacts"] if row.get("artifact_id") == artifact_id]
        if len(rows) != 1:
            raise ValueError("artifact does not identify one original output")
        artifact = rows[0]
        expected = (
            f"workflow-file-{execution_id}-{contract['node_id']}-"
            + digest(artifact["output_path"])[:24]
        )
        if artifact_id != expected or artifact.get("source") != ARTIFACT_SOURCE:
            raise ValueError("artifact was not produced by the original native workflow")
        execution = db.get(WorkflowExecution, execution_id)
        completed = execution.completed_at.replace(tzinfo=UTC)
        produced_at = datetime.fromisoformat(produced["completed_at"]).astimezone(UTC)
        if produced_at > completed:
            raise ValueError("native delivery occurred after the workflow terminal")
        return contract, artifact, completed
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(404, "原工作流交付文件不存在或身份已改变") from exc


def list_workflow_deliveries(
    user: Any, *, order_no: str, goal_id: str, after: int = 0
) -> dict[str, Any]:
    agreement = _customer_agreement(user, order_no, goal_id)
    items = []
    query = urlencode({"order_no": order_no, "customer_goal_id": goal_id})
    with get_session_factory()() as db:
        ids = list(
            db.scalars(
                select(WorkflowExecution.id)
                .where(
                    WorkflowExecution.user_id == user.id,
                    WorkflowExecution.status == "completed",
                    WorkflowExecution.id > after,
                )
                .order_by(WorkflowExecution.id)
                .limit(101)
            )
        )
        for execution_id in ids[:100]:
            try:
                _binding, produced = load_completed_delivery(db, execution_id)
                for row in produced["artifacts"]:
                    _contract, artifact, completed = _delivery(
                        db, user, execution_id, row["artifact_id"], agreement
                    )
                    route = f"/api/customer-value/workflow-deliveries/{execution_id}/{quote(artifact['artifact_id'], safe='')}"
                    items.append(
                        {
                            "artifact_id": artifact["artifact_id"],
                            "artifact_sha256": artifact["artifact_sha256"],
                            "filename": Path(artifact["output_path"]).name,
                            "download_url": f"{route}?{query}",
                            "completed_at": completed.isoformat(),
                        }
                    )
            except (ValueError, HTTPException):
                continue
    return {"items": items, "next_cursor": int(ids[99]) if len(ids) > 100 else None}


def download_workflow_delivery(
    user: Any, *, execution_id: int, artifact_id: str, order_no: str, goal_id: str
) -> Response:
    agreement = _customer_agreement(user, order_no, goal_id)
    with get_session_factory()() as db:
        contract, artifact, _completed = _delivery(db, user, execution_id, artifact_id, agreement)
        try:
            content, filename = read_artifact_bytes(contract, artifact)
        except (OSError, ValueError, VibePathError) as exc:
            raise HTTPException(409, "工作流制品不可读取或与原执行字节不一致") from exc
    return Response(
        content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=utf-8''{quote(filename, safe='')}",
            "ETag": f'"{artifact["artifact_sha256"]}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def validate_workflow_receipt(
    *,
    order: dict[str, Any],
    goal_id: str,
    artifact_id: str,
    artifact_sha256: str,
    occurred_at: datetime,
    outcome: dict[str, Any] | None = None,
) -> None:
    """Workflow-prefixed receipts must resolve the original customer and actual bytes."""
    if not artifact_id.startswith("workflow-file-"):
        return
    match = _ARTIFACT.fullmatch(artifact_id)
    if match is None:
        raise HTTPException(409, "工作流制品身份格式无效")
    with get_session_factory()() as db:
        user = db.get(User, int(order.get("user_id") or 0))
        if user is None:
            raise HTTPException(403, "订单原客户不存在")
        agreement = _customer_agreement(
            user, str(order.get("out_trade_no") or order.get("order_no") or ""), goal_id
        )
        contract, artifact, completed = _delivery(db, user, int(match[1]), artifact_id, agreement)
        if artifact["artifact_sha256"] != artifact_sha256.lower() or occurred_at < completed:
            raise HTTPException(409, "凭证必须对应原工作流完成后的相同制品")
        try:
            read_artifact_bytes(contract, artifact)
        except (OSError, ValueError, VibePathError) as exc:
            raise HTTPException(409, "工作流制品字节已改变或不可读取") from exc
        if outcome is not None:
            goal = db.scalar(
                select(CustomerValueReceipt).where(
                    CustomerValueReceipt.receipt_id == agreement["receipt_id"]
                )
            )
            evidence = json_loads(str(goal.evidence_json), {}) if goal is not None else {}
            fields = ("baseline", "target", "comparison", "unit", "measurement_window")
            if any(outcome.get(field) != evidence.get(field) for field in fields):
                raise HTTPException(409, "业务测量必须对应原客户确认的 KPI 协议")
