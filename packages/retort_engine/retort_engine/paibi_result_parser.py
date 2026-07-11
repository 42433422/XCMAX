"""Backward-compatible re-exports for PaiBi result parsing.

The real implementation now lives in :mod:`retort_engine.paibi_status`, which is
the single source of truth for score extraction and normalization. This module
is kept so existing imports (`from retort_engine.paibi_result_parser import ...`)
keep working without maintaining a second, drift-prone copy of the logic.
"""

from __future__ import annotations

from retort_engine.paibi_status import extract_last_json_object, normalize_llm_scores

__all__ = ["extract_last_json_object", "normalize_llm_scores"]
