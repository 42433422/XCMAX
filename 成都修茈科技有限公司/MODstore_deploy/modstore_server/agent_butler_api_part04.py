# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.agent_butler_api")


class CorpIntakeFillDTO(_facade().BaseModel):
    message: str = _facade().Field(..., min_length=1, max_length=2000)
    current_draft: _facade().Optional[_facade().Dict[str, _facade().Any]] = None
    page_summary: _facade().Optional[str] = _facade().Field(None, max_length=3500)
