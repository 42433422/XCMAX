"""LLM-driven Word/Excel generation for 小猫分析."""

from app.services.kitten_ai_document.generate import draft_document_spec, generate_office_file

__all__ = ["draft_document_spec", "generate_office_file"]
