"""Application-wide reusable HTTP client shutdown."""

from __future__ import annotations


async def close_llm_http_clients() -> None:
    """Release every process-wide LLM/planner HTTP connection."""
    from app.domain.shared_services.conversation.manager import close_ai_conversation_service
    from app.infrastructure.llm.client import dispose_llm_client

    await close_ai_conversation_service()
    dispose_llm_client()
