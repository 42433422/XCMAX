"""Internal handlers for the legacy system-admin LLM endpoints."""

from __future__ import annotations

import os


def reload_llm_registry_payload() -> dict[str, str | bool]:
    from app.infrastructure.llm.providers import registry as reg_mod

    reg_mod._registry = None
    return {
        "success": True,
        "LLM_PROVIDER": (os.environ.get("LLM_PROVIDER") or "").strip(),
        "LLM_ROUTING_ORDER": (os.environ.get("LLM_ROUTING_ORDER") or "").strip(),
    }
