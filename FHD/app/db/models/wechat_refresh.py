"""Host-owned requests for the Windows WeChat collection agent."""

from sqlalchemy import Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WechatRefreshRequest(Base):
    __tablename__ = "wechat_refresh_requests"
    __table_args__ = (Index("ix_wechat_refresh_due", "tenant_id", "state", "created_at"),)

    request_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)
    lease_token: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    lease_until: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    receipt_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
