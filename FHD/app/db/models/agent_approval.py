"""Durable one-use identities for signed Agent approval grants."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AgentApprovalConsumption(Base):
    __tablename__ = "agent_approval_consumptions"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(96), nullable=False)
    step_id: Mapped[str] = mapped_column(String(96), nullable=False)
    consumed_at: Mapped[str] = mapped_column(String(48), nullable=False)
