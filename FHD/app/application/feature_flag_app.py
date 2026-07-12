"""Application facade for feature flags (routes must not import app.services)."""

from __future__ import annotations

from app.services.feature_flag import FeatureFlagName, is_enabled

__all__ = ["FeatureFlagName", "is_enabled"]
