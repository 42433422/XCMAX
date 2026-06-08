"""Analytics application service."""

from __future__ import annotations

from modstore_server.domain.analytics import AnalyticsDashboard, AnalyticsRepository


class AnalyticsApplicationService:
    def __init__(self, repository: AnalyticsRepository):
        self._repository = repository

    def dashboard_for_user(self, user_id: int) -> AnalyticsDashboard:
        return self._repository.dashboard_for_user(user_id)
