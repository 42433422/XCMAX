"""Process-level MODstore application profile configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    profile: str = "full"  # full | llm-only


def load_default_config() -> AppConfig:
    raw = (os.environ.get("MODSTORE_APP_PROFILE") or "").strip().lower()
    if raw in ("llm-only", "llm_only"):
        return AppConfig(profile="llm-only")
    return AppConfig(profile="full")
