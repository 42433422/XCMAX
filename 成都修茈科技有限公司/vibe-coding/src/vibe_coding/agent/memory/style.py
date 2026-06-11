"""Project style fingerprint extracted from :class:`RepoIndex`.

The :class:`StyleProfile` is intentionally lightweight and deterministic: it
counts observable facts (snake_case vs camelCase names, type-hint coverage,
docstring rate, …) rather than trying to reproduce the LLM-based style
inference that heavyweight tools (e.g. sourcery) do. The goal is to give the
LLM enough signal to write blending-in code, not to enforce a style guide.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from ..repo_index import RepoIndex


@dataclass
class StyleProfile:
    """Observable style facts about a Python project.

    Extracted from :class:`RepoIndex` without running the actual code or
    importing anything from the project.
    """

    naming_convention: str = "snake_case"
    type_hint_rate: float = 0.0
    docstring_rate: float = 0.0
    common_imports: list[str] = field(default_factory=list)
    common_exceptions: list[str] = field(default_factory=list)
    avg_function_length: float = 0.0
    uses_dataclasses: bool = False
    uses_protocols: bool = False
    uses_type_aliases: bool = False
    has_async: bool = False

    @classmethod
    def from_index(cls, index: RepoIndex) -> "StyleProfile":
        functions = [
            s for e in index.files.values() for s in e.symbols if s.kind in ("function", "method", "async_function")
        ]
        classes = [s for e in index.files.values() for s in e.symbols if s.kind == "class"]
        all_names = [s.name for s in functions] + [s.name for s in classes]

        naming = _infer_naming(all_names)
        hint_count = sum(1 for s in functions if s.signature and "->" in s.signature)
        hint_rate = hint_count / max(len(functions), 1)
        doc_count = sum(1 for s in functions if s.docstring)
        doc_rate = doc_count / max(len(functions), 1)

        all_imports: list[str] = []
        all_symbols_names: list[str] = []
        for entry in index.files.values():
            all_imports.extend(entry.imports)
            all_symbols_names.extend(s.name for s in entry.symbols)

        common_imports = [name for name, _ in Counter(all_imports).most_common(10)]
        common_excs = _infer_exceptions(all_symbols_names)

        func_lengths = [
            s.end_line - s.start_line + 1 for s in functions if s.end_line > s.start_line
        ]
        avg_len = sum(func_lengths) / max(len(func_lengths), 1)

        uses_dc = any("dataclasses" in (e.imports or []) for e in index.files.values())
        uses_proto = any(
            "Protocol" in (s.signature or "") for e in index.files.values() for s in e.symbols
        )
        uses_aliases = any(
            s.kind == "variable" and s.name.endswith("Type")
            for e in index.files.values()
            for s in e.symbols
        )
        has_async = any(s.kind == "async_function" for e in index.files.values() for s in e.symbols)

        return cls(
            naming_convention=naming,
            type_hint_rate=round(hint_rate, 2),
            docstring_rate=round(doc_rate, 2),
            common_imports=common_imports,
            common_exceptions=common_excs,
            avg_function_length=round(avg_len, 1),
            uses_dataclasses=uses_dc,
            uses_protocols=uses_proto,
            uses_type_aliases=uses_aliases,
            has_async=has_async,
        )

    def to_prompt_block(self) -> str:
        lines = [
            "## 项目风格档案（请让生成的代码保持一致）",
            f"- 命名风格：{self.naming_convention}",
            f"- 类型注解覆盖率：{self.type_hint_rate:.0%}",
            f"- docstring 覆盖率：{self.docstring_rate:.0%}",
            f"- 常用 import：{', '.join(self.common_imports[:6]) or '无'}",
            f"- 常见异常：{', '.join(self.common_exceptions[:5]) or '无'}",
            f"- 平均函数长度：{self.avg_function_length:.0f} 行",
        ]
        if self.uses_dataclasses:
            lines.append("- 项目使用 @dataclass")
        if self.uses_protocols:
            lines.append("- 项目使用 Protocol")
        if self.has_async:
            lines.append("- 项目包含 async/await 代码")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "StyleProfile":
        return cls(
            naming_convention=str(raw.get("naming_convention") or "snake_case"),
            type_hint_rate=float(raw.get("type_hint_rate") or 0.0),
            docstring_rate=float(raw.get("docstring_rate") or 0.0),
            common_imports=[str(x) for x in raw.get("common_imports") or []],
            common_exceptions=[str(x) for x in raw.get("common_exceptions") or []],
            avg_function_length=float(raw.get("avg_function_length") or 0.0),
            uses_dataclasses=bool(raw.get("uses_dataclasses", False)),
            uses_protocols=bool(raw.get("uses_protocols", False)),
            uses_type_aliases=bool(raw.get("uses_type_aliases", False)),
            has_async=bool(raw.get("has_async", False)),
        )


_CAMEL_RE = re.compile(r"[A-Z][a-z]+[A-Z]")
_SNAKE_RE = re.compile(r"[a-z]_[a-z]")
_EXCEPTION_NAMES = frozenset(
    {"ValueError", "TypeError", "KeyError", "RuntimeError", "IndexError",
     "AttributeError", "NotImplementedError", "Exception", "OSError",
     "FileNotFoundError", "PermissionError", "ImportError", "StopIteration"}
)


def _infer_naming(names: list[str]) -> str:
    snake = sum(1 for n in names if _SNAKE_RE.search(n))
    camel = sum(1 for n in names if _CAMEL_RE.search(n))
    if camel > snake:
        return "camelCase"
    return "snake_case"


def _infer_exceptions(symbol_names: list[str]) -> list[str]:
    return [n for n in symbol_names if n in _EXCEPTION_NAMES][:5]


__all__ = ["StyleProfile"]
