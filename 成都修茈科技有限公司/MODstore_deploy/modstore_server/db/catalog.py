"""商城目录、评价、收藏与用户 MOD。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)

from modstore_server.db.base import Base, get_session_factory


class CatalogItem(Base):
    __tablename__ = "catalog_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pkg_id = Column(String(128), unique=True, nullable=False, index=True)
    version = Column(String(32), nullable=False)
    name = Column(String(256), nullable=False)
    description = Column(Text, default="")
    price = Column(Numeric(12, 2), default=0.0)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    artifact = Column(String(32), default="mod", index=True)
    industry = Column(String(64), default="通用")
    stored_filename = Column(String(256), default="")
    sha256 = Column(String(64), default="")
    is_public = Column(Boolean, default=False)
    security_level = Column(String(32), default="personal")
    industry_code = Column(String(16), default="")
    industry_secondary = Column(String(64), default="")
    description_embedding = Column(Text, default="")
    template_category = Column(String(32), default="", index=True)
    template_difficulty = Column(String(16), default="")
    install_count = Column(Integer, default=0)
    graph_snapshot = Column(Text, default="")
    material_category = Column(String(64), default="")
    license_scope = Column(String(32), default="personal")
    origin_type = Column(String(32), default="original")
    ip_risk_level = Column(String(16), default="low")
    compliance_status = Column(String(32), default="approved", index=True)
    rank_score = Column(Float, default=100.0)
    delist_reason = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class CatalogComplaint(Base):
    """商城素材投诉。"""

    __tablename__ = "catalog_complaints"

    id = Column(Integer, primary_key=True, autoincrement=True)
    catalog_id = Column(Integer, ForeignKey("catalog_items.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    complaint_type = Column(String(32), default="other", index=True)
    reason = Column(Text, default="")
    evidence_json = Column(Text, default="{}")
    status = Column(String(24), default="pending", index=True)
    admin_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    admin_note = Column(Text, default="")
    resolution = Column(String(32), default="", index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class Purchase(Base):
    __tablename__ = "purchases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    catalog_id = Column(Integer, ForeignKey("catalog_items.id"), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class UserMod(Base):
    """用户与本地 MOD 的关联表。"""

    __tablename__ = "user_mods"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    mod_id = Column(String(128), nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("user_id", "catalog_id", name="uq_review_user_catalog"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    catalog_id = Column(Integer, ForeignKey("catalog_items.id"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)
    content = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "catalog_id", name="uq_favorite_user_catalog"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    catalog_id = Column(Integer, ForeignKey("catalog_items.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def add_user_mod(user_id: int, mod_id: str) -> UserMod:
    """添加用户与 MOD 的关联。"""
    sf = get_session_factory()
    with sf() as session:
        existing = (
            session.query(UserMod)
            .filter(UserMod.user_id == user_id, UserMod.mod_id == mod_id)
            .first()
        )
        if existing:
            return cast(UserMod, existing)
        user_mod = UserMod(user_id=user_id, mod_id=mod_id)
        session.add(user_mod)
        session.commit()
        session.refresh(user_mod)
        return user_mod


def remove_user_mod(user_id: int, mod_id: str) -> bool:
    """删除用户与 MOD 的关联。"""
    sf = get_session_factory()
    with sf() as session:
        user_mod = (
            session.query(UserMod)
            .filter(UserMod.user_id == user_id, UserMod.mod_id == mod_id)
            .first()
        )
        if user_mod:
            session.delete(user_mod)
            session.commit()
            return True
        return False


def get_user_mod_ids(user_id: int) -> list[str]:
    """获取用户拥有的所有 MOD ID 列表。"""
    sf = get_session_factory()
    with sf() as session:
        rows = session.query(UserMod.mod_id).filter(UserMod.user_id == user_id).all()
        return [r[0] for r in rows]


def user_owns_mod(user_id: int, mod_id: str) -> bool:
    """检查用户是否拥有指定 MOD。"""
    sf = get_session_factory()
    with sf() as session:
        return (
            session.query(UserMod)
            .filter(UserMod.user_id == user_id, UserMod.mod_id == mod_id)
            .first()
            is not None
        )
