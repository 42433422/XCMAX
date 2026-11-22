"""Disposable enterprise read models; original business tables remain authoritative."""

from sqlalchemy import Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.db_base import Base


class EnterpriseStateProjection(Base):
    __tablename__ = "enterprise_state_projections"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "actor_id",
            "mod_id",
            "entity_type",
            "entity_id",
            name="uq_enterprise_projection_scope",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    mod_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(160), nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    observed_at: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class EnterpriseEventCursor(Base):
    __tablename__ = "enterprise_event_cursors"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "mod_id",
            "entity_type",
            "entity_id",
            name="uq_enterprise_cursor_scope",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    mod_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(160), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    event_id: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    event_at: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(160), nullable=False, default="")
