"""Infrastructure auth (Phase 5 facades over legacy-layer.db_*_auth)."""

from app.infrastructure.auth.dependencies import (  # noqa: F401
    CurrentUser,
    get_current_user,
    require_identified_user,
)

__all__ = ["CurrentUser", "get_current_user", "require_identified_user"]
