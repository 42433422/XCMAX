"""Tenant-owned business goal bindings; business records remain in their source stores."""

from sqlalchemy import Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.db_base import Base


class EnterpriseGoalBinding(Base):
    __tablename__ = "enterprise_goal_bindings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "actor_id", "mod_id", "goal_id", name="uq_enterprise_goal_scope"
        ),
        Index(
            "ix_enterprise_goal_entity",
            "tenant_id",
            "actor_id",
            "mod_id",
            "entity_type",
            "entity_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    mod_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    goal_id: Mapped[str] = mapped_column(String(96), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(160), nullable=False)
    definition_json: Mapped[str] = mapped_column(Text, nullable=False)
    binding_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[str] = mapped_column(String(48), nullable=False)
