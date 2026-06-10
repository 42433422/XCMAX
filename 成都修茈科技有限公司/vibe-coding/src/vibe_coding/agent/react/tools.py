"""Tool primitives for the ReAct agent.

Three layers, smallest first:

- :class:`Tool` — a callable + descriptor pair the agent can invoke.
  Built from a Python function via :func:`tool` (preferred) or hand-
  rolled by implementing the small Protocol.
- :class:`ToolRegistry` — collection of tools keyed by name, generates
  the JSON-schema-flavoured listing the agent feeds the LLM.
- :class:`ToolResult` — return shape: success / output / error message,
  plus a string ``observation`` that gets fed back into the next prompt.

We deliberately avoid OpenAI's specific ``functions`` / ``tools`` schema
— the agent emits and parses plain JSON commands so the same loop runs
against any of the providers in ``vibe_coding.nl.providers``. Vendors
that *do* support native tool-calling will still see correct calls
because the prompt instructs JSON-only and our parser is tolerant.
"""

from __future__ import annotations

import inspect
import textwrap
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Protocol, runtime_checkable

ToolFunc = Callable[..., Any]


class ToolError(RuntimeError):
    """Raised when a tool fails to execute or its arguments are malformed."""


class ToolNotFoundError(ToolError):
    """Raised when the LLM asks for a tool that isn't registered."""


@dataclass(slots=True)
class ToolResult:
    """Outcome of one :meth:`Tool.run` call.

    ``observation`` is the textual snippet that goes back into the
    agent prompt. Keep it tight (≤ a few KB) so the context window
    doesn't explode after a long run.
    """

    success: bool
    observation: str
    output: Any = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "observation": self.observation,
            "output": self.output,
            "error": self.error,
        }


@dataclass(slots=True)
class Tool:
    """A named callable plus enough schema for the LLM to call it.

    ``arguments`` is a list of ``{"name", "type", "description",
    "required"}`` records. We use a list-of-dicts rather than a real
    JSON schema so the prompt fits in plain text and stays readable
    when the agent dumps the registry into the system prompt.
    """

    name: str
    description: str
    func: ToolFunc
    arguments: list[dict[str, Any]] = field(default_factory=list)
    aliases: tuple[str, ...] = ()
    sync: bool = True

    def run(self, **kwargs: Any) -> ToolResult:
        try:
            output = self.func(**kwargs)
        except ToolError as exc:
            return ToolResult(
                success=False,
                observation=f"[{self.name}] failed: {exc}",
                error=str(exc),
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                observation=f"[{self.name}] crashed: {type(exc).__name__}: {exc}",
                error=f"{type(exc).__name__}: {exc}",
            )
        if isinstance(output, ToolResult):
            return output
        return ToolResult(success=True, observation=_render_observation(output), output=output)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description.strip(),
            "arguments": list(self.arguments),
        }


@runtime_checkable
class _ToolLike(Protocol):
    name: str
    description: str

    def run(self, **kwargs: Any) -> ToolResult: ...


def tool(
    name: str | None = None,
    *,
    description: str = "",
    arguments: list[dict[str, Any]] | None = None,
    aliases: tuple[str, ...] = (),
) -> Callable[[ToolFunc], Tool]:
    """Decorator that turns a Python function into a :class:`Tool`.

    Argument schema is inferred from the function signature when not
    supplied explicitly:

        @tool(description="Read a file")
        def read_file(path: str) -> str:
            ...
    """

    def decorate(fn: ToolFunc) -> Tool:
        n = name or fn.__name__
        desc = description or (fn.__doc__ or "").strip().split("\n\n")[0]
        args = arguments or _infer_arguments(fn)
        return Tool(name=n, description=desc, func=fn, arguments=args, aliases=tuple(aliases))

    return decorate


class ToolRegistry:
    """Name → Tool registry with prompt rendering and dispatch helpers."""

    def __init__(self, tools: Iterable[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for t in tools or []:
            self.register(t)

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._tools)

    def __iter__(self):  # pragma: no cover - trivial
        return iter(self._tools.values())

    def register(self, t: Tool) -> Tool:
        if t.name in self._tools:
            raise ValueError(f"tool {t.name!r} already registered")
        self._tools[t.name] = t
        for alias in t.aliases:
            if alias and alias not in self._tools:
                self._tools[alias] = t
        return t

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"tool {name!r} not registered") from exc

    def names(self) -> list[str]:
        # Deduplicate primary names from aliases.
        seen: set[int] = set()
        out: list[str] = []
        for t in self._tools.values():
            if id(t) in seen:
                continue
            seen.add(id(t))
            out.append(t.name)
        return out

    def to_prompt_schema(self) -> str:
        """Render every tool as a Markdown block for the agent prompt."""
        lines: list[str] = []
        seen: set[int] = set()
        for t in self._tools.values():
            if id(t) in seen:
                continue
            seen.add(id(t))
            lines.append(f"### `{t.name}`")
            if t.description:
                lines.append(t.description.strip())
            if t.arguments:
                arg_lines = []
                for a in t.arguments:
                    req = "**required**" if a.get("required", True) else "optional"
                    arg_lines.append(
                        f"- `{a['name']}` ({a.get('type', 'string')}, {req}): "
                        f"{a.get('description', '')}"
                    )
                lines.append("\n".join(arg_lines))
            lines.append("")
        return "\n".join(lines).rstrip()

    def call(self, name: str, kwargs: dict[str, Any]) -> ToolResult:
        return self.get(name).run(**(kwargs or {}))


# --------------------------------------------------------------- helpers


def _infer_arguments(fn: ToolFunc) -> list[dict[str, Any]]:
    sig = inspect.signature(fn)
    out: list[dict[str, Any]] = []
    for param in sig.parameters.values():
        if param.name in ("self", "cls"):
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        annotation = (
            param.annotation if param.annotation is not inspect.Parameter.empty else str
        )
        out.append(
            {
                "name": param.name,
                "type": _annotation_to_type(annotation),
                "required": param.default is inspect.Parameter.empty,
                "description": "",
            }
        )
    return out


_STRING_ANNOTATION_MAP: dict[str, str] = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "list": "array",
    "tuple": "array",
    "Sequence": "array",
    "dict": "object",
    "Mapping": "object",
}


def _annotation_to_type(annotation: Any) -> str:
    # PEP 563 (``from __future__ import annotations``) leaves annotations as
    # strings. Bool MUST come before int because ``bool`` is a subclass of
    # ``int`` and we want the tighter type.
    if isinstance(annotation, str):
        head = annotation.strip()
        # ``Optional[bool]`` / ``bool | None`` → look at the inside.
        for key, value in _STRING_ANNOTATION_MAP.items():
            if head == key or head.startswith(f"{key} ") or head.endswith(f"[{key}]"):
                return value
        return "string"
    if annotation is bool:
        return "boolean"
    if annotation is int:
        return "integer"
    if annotation is float:
        return "number"
    if annotation is str:
        return "string"
    if annotation in (list, tuple):
        return "array"
    if annotation is dict:
        return "object"
    name = getattr(annotation, "__name__", "string")
    return _STRING_ANNOTATION_MAP.get(str(name), str(name))


def _render_observation(output: Any, *, max_chars: int = 4_000) -> str:
    if output is None:
        return "(no output)"
    if isinstance(output, str):
        text = output
    else:
        try:
            import json as _json

            text = _json.dumps(output, ensure_ascii=False, indent=2, default=str)
        except (TypeError, ValueError):
            text = repr(output)
    if len(text) > max_chars:
        text = text[: max_chars] + f"\n... [truncated {len(text) - max_chars} chars]"
    return text


def render_observation(output: Any, *, max_chars: int = 4_000) -> str:
    """Public version of the truncating observation renderer."""
    return _render_observation(output, max_chars=max_chars)


__all__ = [
    "Tool",
    "ToolError",
    "ToolNotFoundError",
    "ToolRegistry",
    "ToolResult",
    "render_observation",
    "tool",
]


_ = textwrap  # silence "unused import" — kept for future help-text wrapping.
