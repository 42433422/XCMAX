from __future__ import annotations


def import_workflow_components():
    from app.application.workflow import (
        HybridRiskGate,
        LLMWorkflowPlanner,
        WorkflowEngine,
        get_approval_service,
    )

    return HybridRiskGate, LLMWorkflowPlanner, WorkflowEngine, get_approval_service


def import_ai_conversation_service():
    from app.services import get_ai_conversation_service as get_service

    return get_service


def get_ai_conversation_service():
    """Lazy re-export so unit tests can patch the app-service module attribute."""
    return import_ai_conversation_service()()
