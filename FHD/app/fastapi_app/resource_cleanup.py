"""Application-wide reusable HTTP client shutdown."""

from __future__ import annotations


async def close_llm_http_clients() -> None:
    """Release every process-wide LLM/planner HTTP connection."""
    from app.application.workflow.engine import close_sync_http_client
    from app.infrastructure.llm.client import dispose_llm_client
    from app.domain.conversation.legacy_services.manager import close_ai_conversation_service

    await close_ai_conversation_service()
    close_sync_http_client()
    dispose_llm_client()
