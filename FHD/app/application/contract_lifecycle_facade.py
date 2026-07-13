"""Application boundary for contract lifecycle routes."""

from __future__ import annotations

from typing import Any


def load_pipeline(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from app.services.user_cs_pipeline import load_pipeline as implementation

    return implementation(*args, **kwargs)


def save_pipeline(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from app.services.user_cs_pipeline import save_pipeline as implementation

    return implementation(*args, **kwargs)


def get_contract_block(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from app.services.contract_lifecycle import get_contract_block as implementation

    return implementation(*args, **kwargs)


def transition_contract(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from app.services.contract_lifecycle import transition_contract as implementation

    return implementation(*args, **kwargs)


def apply_contract_to_crm_meta(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from app.services.contract_lifecycle import apply_contract_to_crm_meta as implementation

    return implementation(*args, **kwargs)


def start_esign_flow(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from app.services.contract_lifecycle import start_esign_flow as implementation

    return implementation(*args, **kwargs)


__all__ = [
    "apply_contract_to_crm_meta",
    "get_contract_block",
    "load_pipeline",
    "save_pipeline",
    "start_esign_flow",
    "transition_contract",
]
