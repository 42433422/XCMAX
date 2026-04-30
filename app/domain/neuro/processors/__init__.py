"""神经处理器"""

from app.domain.neuro.processors.subconscious import SubconsciousProcessor
from app.domain.neuro.processors.conscious import ConsciousProcessor
from app.domain.neuro.processors.coordinator import ProcessorCoordinator, ProcessorType

__all__ = [
    "SubconsciousProcessor",
    "ConsciousProcessor", 
    "ProcessorCoordinator",
    "ProcessorType",
]
