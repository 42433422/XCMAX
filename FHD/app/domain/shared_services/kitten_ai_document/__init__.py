"""LLM-driven Word/Excel generation for 小猫分析."""

from app.domain.shared_services.kitten_ai_document import generate as generate
from app.domain.shared_services.kitten_ai_document import pickup as pickup
from app.domain.shared_services.kitten_ai_document.generate import (
    draft_document_spec,
    generate_office_file,
)

__all__ = [
    "draft_document_spec",
    "generate",
    "generate_office_file",
    "pickup",
]
