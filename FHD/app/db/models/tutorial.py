"""Persistent state for the V2 hands-on tutorial.

Tutorial control-plane rows intentionally do not inherit ``TenantScopedMixin``:
the source tenant owns the learning record while all business writes are routed
to the separate ``tutorial_tenant_id`` stored on the workspace.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base


class TutorialWorkspace(Base):
    __tablename__ = "tutorial_workspaces"
    __table_args__ = (
        Index(
            "ix_tutorial_workspace_owner_status",
            "source_tenant_id",
            "user_id",
            "status",
        ),
        UniqueConstraint(
            "source_tenant_id",
            "user_id",
            "generation",
            name="uq_tutorial_workspace_generation",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    tutorial_tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=False, unique=True, index=True
    )
    active_key: Mapped[Optional[str]] = mapped_column(String(96), unique=True, index=True)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active", index=True)
    retired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    purge_after: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    runs: Mapped[list[TutorialRun]] = relationship(
        "TutorialRun", back_populates="workspace", cascade="all, delete-orphan"
    )


class TutorialRun(Base):
    __tablename__ = "tutorial_runs"
    __table_args__ = (
        Index("ix_tutorial_run_owner_status", "source_tenant_id", "user_id", "status"),
        Index("ix_tutorial_run_workspace_course", "workspace_id", "course_id", "version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tutorial_workspaces.id"), nullable=False, index=True
    )
    source_tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    course_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active", index=True)
    active_key: Mapped[Optional[str]] = mapped_column(String(96), unique=True, index=True)
    current_step_id: Mapped[str] = mapped_column(String(96), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_entered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_left_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    workspace: Mapped[TutorialWorkspace] = relationship("TutorialWorkspace", back_populates="runs")
    evidence: Mapped[list[TutorialStepEvidence]] = relationship(
        "TutorialStepEvidence", back_populates="run", cascade="all, delete-orphan"
    )


class TutorialStepEvidence(Base):
    __tablename__ = "tutorial_step_evidence"
    __table_args__ = (
        UniqueConstraint("run_id", "step_id", name="uq_tutorial_evidence_run_step"),
        Index("ix_tutorial_evidence_run_status", "run_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tutorial_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_id: Mapped[str] = mapped_column(String(96), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    result_code: Mapped[str] = mapped_column(String(64), nullable=False, default="not_verified")
    entity_refs_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    counts_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    run: Mapped[TutorialRun] = relationship("TutorialRun", back_populates="evidence")
