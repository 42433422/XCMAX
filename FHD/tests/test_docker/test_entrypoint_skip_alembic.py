"""Entrypoint must refuse FHD_SKIP_ALEMBIC=1 without emergency override."""

from __future__ import annotations

from pathlib import Path

ENTRYPOINT = Path(__file__).resolve().parents[2] / "docker" / "docker-entrypoint-fhd-api.sh"


def test_entrypoint_blocks_skip_alembic_without_emergency() -> None:
    text = ENTRYPOINT.read_text(encoding="utf-8")
    assert "FHD_SKIP_ALEMBIC" in text
    assert "FHD_ALLOW_SKIP_ALEMBIC_EMERGENCY" in text
    assert "FATAL" in text
    assert "alembic -c alembic.ini upgrade head" in text
