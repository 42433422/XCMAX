"""
神经反射与处理器

提供：
- IntentReflexArc: 快速反射弧
- Reflex patterns: 预定义反射模式
- SubconsciousProcessor: 潜意识处理器
- ConsciousProcessor: 显意识处理器
- ProcessorCoordinator: 处理器协调器
"""

from app.domain.neuro.reflex_arc import IntentReflexArc, ReflexResult
from app.domain.neuro.reflex_patterns import ReflexPatternMatcher
from app.domain.neuro.processors.subconscious import SubconsciousProcessor
from app.domain.neuro.processors.conscious import ConsciousProcessor
from app.domain.neuro.processors.coordinator import (
    ProcessorCoordinator,
    ProcessorType,
    get_processor_coordinator,
)
from app.domain.neuro.neuro_uow import NeuroUnitOfWork, neuro_uow_session

__all__ = [
    "IntentReflexArc",
    "ReflexResult",
    "ReflexPatternMatcher",
    "SubconsciousProcessor",
    "ConsciousProcessor",
    "ProcessorCoordinator",
    "ProcessorType",
    "get_processor_coordinator",
    "NeuroUnitOfWork",
    "neuro_uow_session",
]
