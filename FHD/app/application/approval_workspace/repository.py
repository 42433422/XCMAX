"""Session-scoped approval lookups; no tenant or active-Mod context is cached."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from sqlalchemy.orm import Session

from app.db.models.approval import ApprovalFlow, ApprovalFlowNode, ApprovalRequest

from .ports import SessionFactory


@dataclass(frozen=True)
class ApprovalRepository:
    session: SessionFactory

    @staticmethod
    def request(db: Session, request_id: int) -> ApprovalRequest | None:
        return cast(
            ApprovalRequest | None,
            db.query(ApprovalRequest).filter(ApprovalRequest.id == request_id).first(),
        )

    @staticmethod
    def flow(db: Session, flow_id: int, *, include_deleted: bool = False) -> ApprovalFlow | None:
        query = db.query(ApprovalFlow).filter(ApprovalFlow.id == flow_id)
        if not include_deleted:
            query = query.filter(ApprovalFlow.is_deleted == False)
        return cast(ApprovalFlow | None, query.first())


def ordered_nodes(db: Session, flow_id: int) -> list[ApprovalFlowNode]:
    return cast(
        list[ApprovalFlowNode],
        db.query(ApprovalFlowNode)
        .filter(ApprovalFlowNode.flow_id == flow_id, ApprovalFlowNode.is_active == True)
        .order_by(ApprovalFlowNode.node_order.asc())
        .all(),
    )


def workflow_audit_node(db: Session, req: ApprovalRequest) -> ApprovalFlowNode | None:
    return cast(
        ApprovalFlowNode | None,
        db.query(ApprovalFlowNode)
        .filter(ApprovalFlowNode.flow_id == req.flow_id, ApprovalFlowNode.is_active == True)
        .order_by(ApprovalFlowNode.node_order.asc())
        .first(),
    )
