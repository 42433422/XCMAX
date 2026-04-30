"""
NeuroBus 集成模块

提供与现有系统的集成：
- 意图识别系统
- 对话协调器
- FastAPI 生命周期
"""

from app.neuro_bus.integrations.intent_integration import (
    NeuroIntentRecognizer,
    get_neuro_intent_recognizer,
    integrate_with_intent_system,
    is_neuro_stack_enabled,
    try_neuro_reflex_intent,
)
from app.neuro_bus.integrations.conversation_integration import (
    NeuroConversationCoordinator,
    integrate_with_conversation_coordinator,
)
from app.neuro_bus.integrations.fastapi_integration import (
    setup_neurobus_lifespan,
    get_neurobus_health,
)
from app.domain.neuro.processors.coordinator import (
    ProcessorCoordinator,
    get_processor_coordinator,
    ProcessingReport,
    ProcessorType,
)

__all__ = [
    "NeuroIntentRecognizer",
    "get_neuro_intent_recognizer",
    "integrate_with_intent_system",
    "is_neuro_stack_enabled",
    "try_neuro_reflex_intent",
    "NeuroConversationCoordinator",
    "integrate_with_conversation_coordinator",
    "setup_neurobus_lifespan",
    "get_neurobus_health",
    "ProcessorCoordinator",
    "get_processor_coordinator",
    "ProcessingReport",
    "ProcessorType",
]
