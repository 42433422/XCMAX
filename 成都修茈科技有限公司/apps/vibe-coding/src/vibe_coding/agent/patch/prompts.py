"""Prompts for multi-file edit / repair flows.

The canonical strings live in :mod:`vibe_coding.nl.prompts` (alongside the
single-skill prompts) so existing users can import them via
``from vibe_coding import MULTI_FILE_EDIT_PROMPT``. This module re-exports them
so agent-layer code only depends on ``vibe_coding.agent.patch``.
"""

from __future__ import annotations

from ...nl.prompts import (
    CODE_HUNK_REPAIR_PROMPT,
    MULTI_FILE_EDIT_PROMPT,
    MULTI_FILE_REPAIR_PROMPT,
)

__all__ = [
    "CODE_HUNK_REPAIR_PROMPT",
    "MULTI_FILE_EDIT_PROMPT",
    "MULTI_FILE_REPAIR_PROMPT",
]
