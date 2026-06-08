"""使用统计仪表盘（员工执行、消费概览）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from modstore_server.api.deps import _get_current_user
from modstore_server.application.analytics import AnalyticsApplicationService
from modstore_server.infrastructure.analytics_repository import SqlAnalyticsRepository
from modstore_server.infrastructure.db import get_db
from modstore_server.models import User

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/dashboard")
async def dashboard(db: Session = Depends(get_db), user: User = Depends(_get_current_user)):
    return (
        AnalyticsApplicationService(SqlAnalyticsRepository(db))
        .dashboard_for_user(user.id)
        .to_dict()
    )
