"""微信聊天记录同步模型（本机 → 服务器 AI 智慧基建 V1）。

数据流：本机采集端（wechat_cv）增量拉取微信聊天 → POST /api/ops/wechat/ingest
上行入库 → 服务器侧身份解析（联系人 ↔ customers 绑定）→ context 接口回流本机。
服务器为 AI 第一载体，本机为第二载体。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import IntegerPrimaryKeyMixin, TenantScopedMixin, TimestampMixin


class WechatContact(IntegerPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """微信联系人（本机采集侧的身份锚点，可绑定到 customers）。"""

    __tablename__ = "wechat_contacts"
    __table_args__ = (UniqueConstraint("tenant_id", "contact_key", name="uq_wechat_contact_key"),)

    contact_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    wxid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 绑定的 customers.id（逻辑外键，避免级联耦合；0/None 表示未绑定）
    customer_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # unlinked / auto_linked / manual_linked
    match_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unlinked")
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WechatMessage(IntegerPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """微信聊天消息（以 dedupe_hash 幂等入库，允许本机重复上行）。"""

    __tablename__ = "wechat_messages"
    __table_args__ = (UniqueConstraint("dedupe_hash", name="uq_wechat_msg_hash"),)

    contact_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("wechat_contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # self = 机主发送 / other = 对方发送
    role: Mapped[str] = mapped_column(String(8), nullable=False, default="other")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 客户端提供的消息时间（V1 采集端无原始时间戳时为采集时刻，近似有序）
    msg_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    # db = 本地数据库 / cv = 窗口 OCR / api = 其他通道
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="db")
    dedupe_hash: Mapped[str] = mapped_column(String(64), nullable=False)
