"""Legacy helper name, bound to the authenticated Mod workspace."""

from pathlib import Path

from app.mod_sdk.owner_workspace import owner_workspace


def attendance_workspace_root(base: Path | None = None) -> Path:
    root = owner_workspace("sunbird-attendance-custom").root
    root.mkdir(parents=True, exist_ok=True)
    return root
