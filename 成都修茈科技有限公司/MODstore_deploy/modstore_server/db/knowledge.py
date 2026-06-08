"""知识库集合元数据（物理向量在 Chroma）。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from modstore_server.db.base import Base


class KnowledgeCollection(Base):
    __tablename__ = "knowledge_collections"
    __table_args__ = (UniqueConstraint("owner_kind", "owner_id", "name", name="uq_kb_owner_name"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_kind = Column(String(16), nullable=False, index=True)
    owner_id = Column(String(64), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    visibility = Column(String(16), default="private", index=True)
    embedding_model = Column(String(64), default="")
    embedding_dim = Column(Integer, default=1536)
    chunk_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class KnowledgeMembership(Base):
    __tablename__ = "knowledge_memberships"
    __table_args__ = (
        UniqueConstraint(
            "collection_id",
            "grantee_kind",
            "grantee_id",
            name="uq_kb_membership_unique",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    collection_id = Column(
        Integer, ForeignKey("knowledge_collections.id"), nullable=False, index=True
    )
    grantee_kind = Column(String(16), nullable=False)
    grantee_id = Column(String(64), nullable=False, index=True)
    permission = Column(String(8), default="read")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (UniqueConstraint("collection_id", "doc_id", name="uq_kb_doc_unique"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    collection_id = Column(
        Integer, ForeignKey("knowledge_collections.id"), nullable=False, index=True
    )
    doc_id = Column(String(64), nullable=False, index=True)
    filename = Column(String(256), default="")
    size_bytes = Column(Integer, default=0)
    chunk_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
