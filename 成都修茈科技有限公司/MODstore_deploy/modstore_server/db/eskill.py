"""可进化 ESkill 注册表与运行记录。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint

from modstore_server.db.base import Base


class ESkill(Base):
    __tablename__ = "eskills"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_eskill_user_name"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    domain = Column(Text, default="")
    description = Column(Text, default="")
    active_version = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ESkillVersion(Base):
    __tablename__ = "eskill_versions"
    __table_args__ = (UniqueConstraint("eskill_id", "version", name="uq_eskill_version"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    eskill_id = Column(Integer, ForeignKey("eskills.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    static_logic_json = Column(Text, default="{}")
    trigger_policy_json = Column(Text, default="{}")
    quality_gate_json = Column(Text, default="{}")
    source_run_id = Column(Integer, nullable=True, index=True)
    note = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ESkillRun(Base):
    __tablename__ = "eskill_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    eskill_id = Column(Integer, ForeignKey("eskills.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    workflow_id = Column(Integer, nullable=True, index=True)
    workflow_node_id = Column(Integer, nullable=True, index=True)
    stage = Column(String(32), default="static", index=True)
    input_json = Column(Text, default="{}")
    output_json = Column(Text, default="{}")
    patch_json = Column(Text, default="{}")
    error_message = Column(Text, default="")
    duration_ms = Column(Float, default=0.0)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)
