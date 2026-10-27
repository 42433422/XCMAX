"""Application facade for contract lifecycle operations."""

from __future__ import annotations

from typing import Any


def handle_esign_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    from app.domain.shared_services.contract_lifecycle import handle_esign_webhook as impl

    return impl(payload)
