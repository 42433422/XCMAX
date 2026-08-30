"""Command grammar and result primitives for the XC diagnostic terminal."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import get_close_matches
from typing import Any, Iterable, Sequence

from modstore_server.llm_quota_monitor import scrub_llm_error

DEFAULT_LIMIT = 30
MAX_LIMIT = 200
MAX_COMMAND_LENGTH = 512
MAX_TEXT_LENGTH = 600
MAX_LOG_BYTES = 256_000

COMMANDS: tuple[dict[str, Any], ...] = (
    {
        "name": "doctor",
        "aliases": ["overview", "health", "概览", "体检"],
        "usage": "doctor",
        "description": "一屏汇总部署、数据库、调度器、DLQ、事件和交付异常",
    },
    {
        "name": "problems",
        "aliases": ["issues", "问题"],
        "usage": "problems [关键词] [--limit N]",
        "description": "只列当前需要关注的问题，可按关键词过滤",
    },
    {
        "name": "find",
        "aliases": ["search", "查", "搜索"],
        "usage": "find <关键词> [--limit N]",
        "description": "同时搜索账号、交付、调度任务、事件、DLQ 和 API 路由",
    },
    {
        "name": "account",
        "aliases": ["user", "账号"],
        "usage": "account <用户ID|用户名|邮箱>",
        "description": "查看账号、有效套餐及对应交付状态",
    },
    {
        "name": "delivery",
        "aliases": ["deliveries", "交付"],
        "usage": "delivery [账号关键词] [--limit N]",
        "description": "查询永久账号的客户桌面安装与首次登录闭环",
    },
    {
        "name": "scheduler",
        "aliases": ["jobs", "任务"],
        "usage": "scheduler [任务关键词] [--limit N]",
        "description": "查看调度任务真实状态，并分开失败、停滞和策略等待",
    },
    {
        "name": "incidents",
        "aliases": ["events", "事件"],
        "usage": "incidents [关键词] [--limit N]",
        "description": "查询最近系统事件，敏感字段自动脱敏",
    },
    {
        "name": "logs",
        "aliases": ["log", "日志"],
        "usage": "logs [关键词] [--limit N]",
        "description": "搜索安全事件账本和受控错误日志，不允许任意文件路径",
    },
    {
        "name": "routes",
        "aliases": ["route", "api", "路由"],
        "usage": "routes [关键词] [--limit N]",
        "description": "搜索线上应用实际注册的 API 路由",
    },
    {
        "name": "version",
        "aliases": ["release", "版本"],
        "usage": "version",
        "description": "查看部署档位、Git SHA、制品哈希和主机",
    },
    {
        "name": "help",
        "aliases": ["?", "帮助"],
        "usage": "help [命令]",
        "description": "查看命令与示例",
    },
)

_ALIAS_TO_COMMAND = {
    alias.casefold(): entry["name"]
    for entry in COMMANDS
    for alias in [entry["name"], *entry["aliases"]]
}
PROBLEM_STATES = frozenset({"failed", "failing", "stale", "error", "unhealthy"})


class DiagnosticTerminalError(ValueError):
    """Safe validation error returned to an operator."""


@dataclass(frozen=True)
class ParsedCommand:
    name: str
    query: str = ""
    limit: int = DEFAULT_LIMIT


def safe_text(value: Any, *, limit: int = MAX_TEXT_LENGTH) -> str:
    text_value = scrub_llm_error(value).replace("\x00", "").strip()
    return text_value if len(text_value) <= limit else f"{text_value[: limit - 1]}…"


def iso(value: Any) -> str:
    if not isinstance(value, datetime):
        return ""
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).replace(microsecond=0).isoformat()


def matches(query: str, *values: Any) -> bool:
    needle = query.casefold().strip()
    return not needle or any(needle in str(value or "").casefold() for value in values)


def item(
    kind: str,
    severity: str,
    title: str,
    detail: Any = "",
    *,
    source: str = "",
    reference: str = "",
    timestamp: Any = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "kind": kind,
        "severity": severity,
        "title": safe_text(title, limit=200),
        "detail": safe_text(detail),
        "source": safe_text(source, limit=120),
        "reference": safe_text(reference, limit=200),
        "timestamp": iso(timestamp) if isinstance(timestamp, datetime) else str(timestamp or ""),
    }
    if data is not None:
        result["data"] = data
    return result


def parse_command(command_line: str) -> ParsedCommand:
    raw = str(command_line or "").strip()
    if not raw:
        return ParsedCommand("doctor")
    if len(raw) > MAX_COMMAND_LENGTH:
        raise DiagnosticTerminalError(f"命令最多 {MAX_COMMAND_LENGTH} 个字符")
    try:
        tokens = shlex.split(raw)
    except ValueError as exc:
        raise DiagnosticTerminalError(f"命令引号不完整：{exc}") from exc
    if not tokens:
        return ParsedCommand("doctor")
    requested = tokens.pop(0).casefold()
    name = _ALIAS_TO_COMMAND.get(requested)
    if name is None:
        suggestions = get_close_matches(requested, sorted(_ALIAS_TO_COMMAND), n=3, cutoff=0.45)
        hint = (
            f"；你可能想输入：{', '.join(suggestions)}" if suggestions else "；输入 help 查看命令"
        )
        raise DiagnosticTerminalError(f"未知命令：{requested}{hint}")

    limit = DEFAULT_LIMIT
    query_tokens: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--limit":
            if index + 1 >= len(tokens):
                raise DiagnosticTerminalError("--limit 后必须填写数字")
            try:
                limit = int(tokens[index + 1])
            except ValueError as exc:
                raise DiagnosticTerminalError("--limit 必须是数字") from exc
            index += 2
            continue
        if token.startswith("--"):
            raise DiagnosticTerminalError(f"不支持的选项：{token}")
        query_tokens.append(token)
        index += 1
    if limit < 1 or limit > MAX_LIMIT:
        raise DiagnosticTerminalError(f"--limit 必须在 1–{MAX_LIMIT} 之间")
    query = " ".join(query_tokens).strip()
    if name in {"find", "account"} and not query:
        raise DiagnosticTerminalError(f"{name} 命令必须填写查询内容")
    return ParsedCommand(name=name, query=query, limit=limit)


def status_for(items: Iterable[dict[str, Any]], *, empty: str = "healthy") -> str:
    severities = {str(entry.get("severity") or "") for entry in items}
    if severities.intersection({"critical", "error"}):
        return "degraded"
    if "warning" in severities:
        return "attention"
    return empty


def envelope(
    parsed: ParsedCommand,
    *,
    summary: str,
    status: str = "healthy",
    metrics: dict[str, Any] | None = None,
    items: Sequence[dict[str, Any]] = (),
    hints: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "ok": True,
        "read_only": True,
        "command": parsed.name,
        "query": parsed.query,
        "status": status,
        "summary": summary,
        "metrics": metrics or {},
        "items": list(items),
        "hints": list(hints),
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }


def command_catalog() -> list[dict[str, Any]]:
    """Return a copy suitable for UI completion without exposing internals."""

    return [dict(entry) for entry in COMMANDS]


__all__ = [
    "COMMANDS",
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "MAX_LOG_BYTES",
    "PROBLEM_STATES",
    "DiagnosticTerminalError",
    "ParsedCommand",
    "command_catalog",
    "envelope",
    "item",
    "matches",
    "parse_command",
    "safe_text",
    "status_for",
]
