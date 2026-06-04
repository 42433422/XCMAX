"""平台横切（特性开关等）。"""

from __future__ import annotations

from app.services.feature_flag import FeatureFlagName, is_enabled  # noqa: F401

__all__ = ["FeatureFlagName", "is_enabled"]
