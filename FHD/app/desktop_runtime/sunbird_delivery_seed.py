"""Deprecated pre-login seed entry points; ownerless data is never applied."""

from pathlib import Path


def sync_sunbird_delivery_files(data_root: Path | None = None) -> int:
    """Retained import contract only. Use authenticated private delivery installation."""
    return 0


def apply_sunbird_roster_seed_if_needed(data_root: Path | None = None) -> bool:
    """No username inference, global file copying, or writes to host Product tables."""
    return False
