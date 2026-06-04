"""平台横切能力（特性开关等）。"""

from __future__ import annotations

from app.infrastructure.gateways.platform import FeatureFlagName, is_enabled

__all__ = ["FeatureFlagName", "is_enabled", "PlatformApplicationService", "get_platform_app_service"]


class PlatformApplicationService:
    def is_feature_enabled(self, name: FeatureFlagName) -> bool:
        return is_enabled(name)


_platform_app_service: PlatformApplicationService | None = None


def get_platform_app_service() -> PlatformApplicationService:
    global _platform_app_service
    if _platform_app_service is None:
        _platform_app_service = PlatformApplicationService()
    return _platform_app_service
