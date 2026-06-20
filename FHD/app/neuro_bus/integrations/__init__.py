"""
NeuroBus 集成模块

提供与现有系统的集成：
- 意图识别系统（CognitiveRouter 元认知路由）
- FastAPI 健康检查/统计端点
"""

from app.domain.neuro.processors.coordinator import (
    ProcessingReport,
    ProcessorCoordinator,
    ProcessorType,
    get_processor_coordinator,
)
from app.neuro_bus.integrations.fastapi_integration import (
    add_neurobus_routes,
    get_neurobus_health,
)
from app.neuro_bus.integrations.intent_integration import (
    NeuroIntentRecognizer,
    get_neuro_intent_recognizer,
    integrate_with_intent_system,
    is_neuro_stack_enabled,
    try_neuro_reflex_intent,
)

__all__ = [
    "NeuroIntentRecognizer",
    "get_neuro_intent_recognizer",
    "integrate_with_intent_system",
    "is_neuro_stack_enabled",
    "try_neuro_reflex_intent",
    "add_neurobus_routes",
    "get_neurobus_health",
    "ProcessorCoordinator",
    "get_processor_coordinator",
    "ProcessingReport",
    "ProcessorType",
]
