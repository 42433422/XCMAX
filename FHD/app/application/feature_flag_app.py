"""Small environment-backed feature-flag facade used by HTTP routes."""

from __future__ import annotations

import os
from enum import Enum


class FeatureFlagName(str, Enum):
    EXPERIMENTAL_GDPR_API = "experimental.gdpr_api"


def is_enabled(name: FeatureFlagName | str, *, default: bool = False) -> bool:
    """Read ``XCAGI_FEATURE_<FLAG>`` without depending on a removed service module."""
    value = name.value if isinstance(name, FeatureFlagName) else str(name)
    env_key = "XCAGI_FEATURE_" + "".join(ch if ch.isalnum() else "_" for ch in value).upper()
    raw = os.environ.get(env_key)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in {"1", "true", "yes", "on", "enabled"}

__all__ = ["FeatureFlagName", "is_enabled"]
