from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from modstore_server.db.base import Base


class CustomerServiceSession(Base):
    """独立 AI 客服会话，不与工作台本地对话混用。"""

    __tablename__ = "customer_service_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    channel = Column(String(32), default="web", index=True)
    status = Column(String(24), default="open", index=True)
    title = Column(String(256), default="")
    intent = Column(String(64), default="", index=True)
    context_json = Column(Text, default="{}")
    last_message = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class CustomerServiceTicket(Base):
    """客服工单：承载业务对象、状态机、自动化决策和审计关联。"""

    __tablename__ = "customer_service_tickets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(
        Integer, ForeignKey("customer_service_sessions.id"), nullable=False, index=True
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    ticket_no = Column(String(64), unique=True, nullable=False, index=True)
    title = Column(String(256), default="")
    intent = Column(String(64), default="", index=True)
    subject_type = Column(String(64), default="", index=True)
    subject_id = Column(String(128), default="", index=True)
    status = Column(String(24), default="open", index=True)
    priority = Column(String(16), default="normal", index=True)
    evidence_json = Column(Text, default="{}")
    summary = Column(Text, default="")
    decision_status = Column(String(24), default="pending", index=True)
    automation_level = Column(String(24), default="auto", index=True)
    assigned_admin_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    closed_at = Column(DateTime, nullable=True)


class CustomerServiceMessage(Base):
    __tablename__ = "customer_service_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(
        Integer, ForeignKey("customer_service_sessions.id"), nullable=False, index=True
    )
    ticket_id = Column(
        Integer, ForeignKey("customer_service_tickets.id"), nullable=True, index=True
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String(32), nullable=False, index=True)
    content = Column(Text, default="")
    payload_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class CustomerServiceStandard(Base):
    """可配置审核标准，用于自动审批、拒绝或升级处理。"""

    __tablename__ = "customer_service_standards"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False, index=True)
    scenario = Column(String(64), default="general", index=True)
    description = Column(Text, default="")
    rules_json = Column(Text, default="{}")
    action_policy_json = Column(Text, default="{}")
    auto_enabled = Column(Boolean, default=True, index=True)
    risk_level = Column(String(16), default="low", index=True)
    priority = Column(Integer, default=100, index=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class CustomerServiceDecision(Base):
    __tablename__ = "customer_service_decisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(
        Integer, ForeignKey("customer_service_tickets.id"), nullable=False, index=True
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    standard_id = Column(
        Integer, ForeignKey("customer_service_standards.id"), nullable=True, index=True
    )
    intent = Column(String(64), default="", index=True)
    decision = Column(String(32), default="needs_more_info", index=True)
    risk_level = Column(String(16), default="low", index=True)
    confidence = Column(Float, default=0.0)
    rationale = Column(Text, default="")
    extracted_json = Column(Text, default="{}")
    criteria_json = Column(Text, default="[]")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class CustomerServiceAction(Base):
    __tablename__ = "customer_service_actions"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_customer_service_action_idempotency"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(
        Integer, ForeignKey("customer_service_tickets.id"), nullable=False, index=True
    )
    decision_id = Column(
        Integer, ForeignKey("customer_service_decisions.id"), nullable=True, index=True
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    action_type = Column(String(64), nullable=False, index=True)
    target_type = Column(String(64), default="", index=True)
    target_id = Column(String(128), default="", index=True)
    status = Column(String(24), default="pending", index=True)
    request_json = Column(Text, default="{}")
    result_json = Column(Text, default="{}")
    error = Column(Text, default="")
    idempotency_key = Column(String(128), nullable=False, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class CustomerServiceIntegration(Base):
    __tablename__ = "customer_service_integrations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False, index=True)
    integration_type = Column(String(32), default="openapi", index=True)
    connector_id = Column(Integer, ForeignKey("openapi_connectors.id"), nullable=True, index=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=True, index=True)
    scenario = Column(String(64), default="general", index=True)
    config_json = Column(Text, default="{}")
    enabled = Column(Boolean, default=True, index=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class CustomerServiceAuditLog(Base):
    __tablename__ = "customer_service_audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(
        Integer, ForeignKey("customer_service_tickets.id"), nullable=True, index=True
    )
    session_id = Column(
        Integer, ForeignKey("customer_service_sessions.id"), nullable=True, index=True
    )
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    actor_type = Column(String(32), default="system", index=True)
    event_type = Column(String(64), nullable=False, index=True)
    detail_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
