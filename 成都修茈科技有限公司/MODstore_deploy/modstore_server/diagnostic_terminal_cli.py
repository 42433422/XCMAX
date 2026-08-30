"""Operator CLI for the shared XC diagnostic terminal."""

from __future__ import annotations

import argparse
import json
import os
import shlex
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.request import ProxyHandler, build_opener

from modstore_server.diagnostic_terminal import (
    DiagnosticTerminalError,
    execute_diagnostic_command,
    parse_command,
)
from modstore_server.entitlement_fast_lane import FastLaneError, require_admin_actor
from modstore_server.env_loader import load_modstore_env
from modstore_server.models import get_session_factory, init_db
from modstore_server.operational_errors import RECOVERABLE_ERRORS

ROOT = Path(__file__).resolve().parents[1]


def load_operator_environment(env_file: str = "") -> list[str]:
    """Load repository dotenv plus the immutable production service environment."""

    from dotenv import load_dotenv

    loaded = load_modstore_env(ROOT, include_synced=False)
    configured = env_file.strip() or (os.environ.get("MODSTORE_TERMINAL_ENV_FILE") or "").strip()
    candidates = (
        [Path(configured).expanduser()]
        if configured
        else [Path("/etc/xcmax/modstore.env"), Path("/etc/xcmax/modstore-release.env")]
    )
    for path in candidates:
        if path.is_file():
            load_dotenv(path, override=False)
            loaded.append(str(path))
    return list(dict.fromkeys(loaded))


def has_explicit_database_target() -> bool:
    return bool(
        (os.environ.get("DATABASE_URL") or "").strip()
        or (os.environ.get("MODSTORE_DB_PATH") or "").strip()
        or (os.environ.get("MODSTORE_PYTEST_USE_SQLITE") or "").strip() == "1"
    )


def fetch_route_catalog(url: str) -> list[dict[str, Any]]:
    """Fetch an optional local OpenAPI catalog without inheriting proxy settings."""

    if not url.strip():
        return []
    try:
        with build_opener(ProxyHandler({})).open(url, timeout=0.8) as response:  # nosec B310
            payload = json.loads(response.read().decode("utf-8"))
    except RECOVERABLE_ERRORS:
        return []
    paths = payload.get("paths") if isinstance(payload, dict) else None
    if not isinstance(paths, dict):
        return []
    routes: list[dict[str, Any]] = []
    for path, operations in paths.items():
        if not isinstance(operations, dict):
            continue
        methods = [
            str(method).upper()
            for method in operations
            if str(method).casefold() in {"get", "post", "put", "patch", "delete", "head"}
        ]
        names = [
            str(value.get("operationId") or "")
            for value in operations.values()
            if isinstance(value, dict) and value.get("operationId")
        ]
        routes.append({"path": str(path), "methods": methods, "name": ",".join(names)})
    return routes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xcmax-terminal",
        description="XC 软件统一只读诊断终端（不执行 shell、不修改业务数据）",
        epilog=(
            "示例: xcmax-terminal doctor | xcmax-terminal find 登录 | "
            "xcmax-terminal account SUNBIRD | xcmax-terminal logs error --limit 20"
        ),
    )
    parser.add_argument("command", nargs="*", help="诊断命令及查询词；留空默认 doctor")
    parser.add_argument("--limit", type=int, default=None, help="最多返回 1–200 条")
    parser.add_argument("--json", action="store_true", help="输出完整机器可读 JSON")
    parser.add_argument("--actor", default="", help="可选：校验操作人为管理员账号")
    parser.add_argument("--env-file", default="", help="显式 dotenv 文件")
    parser.add_argument(
        "--openapi-url",
        default=os.environ.get(
            "MODSTORE_TERMINAL_OPENAPI_URL", "http://127.0.0.1:9999/openapi.json"
        ),
        help="routes/find 使用的运行时 OpenAPI；不可用时自动降级",
    )
    return parser


def _command_line(tokens: Sequence[str], limit: int | None) -> str:
    command = " ".join(shlex.quote(token) for token in tokens).strip() or "doctor"
    if limit is not None:
        command = f"{command} --limit {limit}"
    return command


def run(
    argv: Sequence[str] | None = None,
    *,
    session_factory: Callable[..., Any] | None = None,
    route_catalog: Sequence[dict[str, Any]] | None = None,
    runtime_provider: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    args = build_parser().parse_args(argv)
    command_line = _command_line(args.command, args.limit)
    parsed = parse_command(command_line)
    if session_factory is None:
        load_operator_environment(args.env_file)
        if not has_explicit_database_target():
            raise DiagnosticTerminalError(
                "未找到 DATABASE_URL 或 MODSTORE_DB_PATH，已拒绝访问默认本地 SQLite"
            )
        init_db()
        session_factory = get_session_factory()
    if route_catalog is None:
        route_catalog = (
            fetch_route_catalog(args.openapi_url) if parsed.name in {"find", "routes"} else []
        )
    with session_factory() as db:
        if args.actor.strip():
            require_admin_actor(db, args.actor)
        return execute_diagnostic_command(
            db,
            command_line,
            route_catalog=route_catalog,
            runtime_provider=runtime_provider,
        )


def _render_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def render_human(result: dict[str, Any]) -> str:
    status = str(result.get("status") or "unknown").upper()
    lines = [
        f"[{status}] {result.get('summary') or ''}",
        f"command={result.get('command')} elapsed_ms={result.get('elapsed_ms')}",
    ]
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    if metrics:
        lines.append("\n指标")
        lines.extend(f"  {key}: {_render_value(value)}" for key, value in metrics.items())
    items = result.get("items") if isinstance(result.get("items"), list) else []
    if items:
        lines.append("\n证据")
        for entry in items:
            if not isinstance(entry, dict):
                continue
            prefix = str(entry.get("severity") or "info").upper()
            lines.append(f"  [{prefix}] {entry.get('title') or ''}")
            if entry.get("detail"):
                lines.append(f"    {entry['detail']}")
            trail = " · ".join(
                str(value)
                for value in (entry.get("source"), entry.get("reference"), entry.get("timestamp"))
                if value
            )
            if trail:
                lines.append(f"    {trail}")
    hints = result.get("hints") if isinstance(result.get("hints"), list) else []
    if hints:
        lines.append("\n下一步")
        lines.extend(f"  - {hint}" for hint in hints)
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run(argv)
    except (DiagnosticTerminalError, FastLaneError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(
        json.dumps(result, ensure_ascii=False, indent=2, default=str)
        if args.json
        else render_human(result)
    )
    return 1 if str(result.get("status") or "") == "degraded" else 0


__all__ = [
    "build_parser",
    "fetch_route_catalog",
    "has_explicit_database_target",
    "load_operator_environment",
    "main",
    "render_human",
    "run",
]
