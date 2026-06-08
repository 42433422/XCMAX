"""Strip known reasoning / chain-of-thought wrappers from LLM-produced Python text.

Models occasionally emit XML-like thinking blocks inside the same ``content`` field
that should contain only source code. This module removes those fragments before
``ast.parse`` / ``py_compile``.
"""

from __future__ import annotations

import re
from typing import List, Tuple

# Common vendor-specific reasoning wrappers seen in chat completions.
_THINKING_STRIP_RES: Tuple[re.Pattern[str], ...] = (
    re.compile(r"(?is)<think>.*?</think>"),
    re.compile(r"(?is)<thinking>.*?</thinking>"),
    re.compile(r"(?is)<reasoning>.*?</reasoning>"),
    re.compile(r"(?is)<analysis>.*?</analysis>"),
)


def strip_llm_reasoning_noise(code: str) -> Tuple[str, List[str]]:
    """Remove reasoning-tag blocks; return cleaned source and human-readable notes."""
    warnings: List[str] = []
    s = code or ""
    for pat in _THINKING_STRIP_RES:
        new_s = pat.sub("", s)
        if new_s != s:
            warnings.append(f"已移除模型推理标签块 ({pat.pattern[:48]}…)")
            s = new_s
    # Trim excessive blank lines left after stripping
    lines = [ln for ln in s.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines), warnings


def finalize_extracted_python(code: str) -> Tuple[str, List[str]]:
    """Last-mile cleanup after :func:`extract_code_block` or fence stripping."""
    return strip_llm_reasoning_noise(code or "")
