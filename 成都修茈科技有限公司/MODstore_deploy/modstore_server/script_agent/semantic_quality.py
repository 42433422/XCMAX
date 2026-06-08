"""AST-level semantic heuristics for LLM-generated Python (scripts + employees).

Complements syntax/import checks: oversized string literals often indicate
reasoning dumps mistakenly embedded as code.
"""

from __future__ import annotations

import ast
from typing import List

# Tunable: reasoning traces rarely need >8k chars inside a single literal.
MAX_STRING_LITERAL_CHARS = 8000


def oversized_string_literal_errors(tree: ast.AST) -> List[str]:
    errs: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            ln = len(node.value)
            if ln > MAX_STRING_LITERAL_CHARS:
                snippet = node.value[:120].replace("\n", "\\n")
                errs.append(
                    f"存在过长字符串字面量（约 {ln} 字符），疑似推理/日志混入代码；"
                    f"开头片段: {snippet!r}…"
                )
                break  # one message is enough for repair prompts
    return errs


def oversized_string_literal_errors_for_source(src: str) -> List[str]:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    return oversized_string_literal_errors(tree)
