"""AI 员工虚拟用户表：让员工在 IM 系统里有 Int user_id。

仿 `enterprise-cs` 范式（im_app_service._ensure_enterprise_dedicated_cs_user），
为每个员工建一条 User 行（username=`ai-employee:{employee_id}`，role=`ai_employee`），
并把元数据（mod_id/avatar_url/owner_user_id）缓存在本表，避免每次查 User 行重新解析。

`owner_user_id` 是该员工的专属老板（per-employee owner），MODstore 推送时优先用它，
未配则回退 env `FHD_BOSS_USER_ID`（全局老板）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AiEmployeeProfile(Base):
    __tablename__ = "ai_employee_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    mod_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    avatar_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    owner_user_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )
