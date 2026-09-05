"""xcagi-brain: standalone commands and an interactive HTTP console."""

from __future__ import annotations

import argparse
import getpass
import json
import math
import os
import shlex
import sys
import warnings
from pathlib import Path

from .brain_client import BrainClient
from .brain_output import terminal_text
from .brain_session import BrainError, SessionStore


def _default_origin() -> str:
    override = os.environ.get("XCAGI_BRAIN_ORIGIN")
    if override:
        return override
    raw = os.environ.get("XCAGI_DESKTOP_PORT", "17500")
    port = int(raw) if len(raw) <= 5 and raw.isdigit() and 0 < int(raw) <= 65535 else 17500
    return f"http://127.0.0.1:{port}"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="xcagi-brain", description="智脑 HTTP 终端")
    result.add_argument("--origin", default=_default_origin())
    result.add_argument("--session-dir", type=Path, default=Path.home() / ".xcagi-brain")
    result.add_argument("--timeout", type=float, default=30)
    result.add_argument("--json", action="store_true", help="输出紧凑 JSON")
    commands = result.add_subparsers(dest="command", required=True)
    login = commands.add_parser("login", help="普通账号登录（密码不放在命令行）")
    login.add_argument("--username", required=True)
    login.add_argument("--account-kind", choices=["enterprise", "personal"], default="enterprise")
    login.add_argument("--password-stdin", action="store_true", help="从 stdin 读取一行密码")
    login.add_argument("--totp", action="store_true", help="安全提示输入动态验证码")
    commands.add_parser("logout")
    commands.add_parser("status", help="真实运行时状态；不会探测执行 AI 草稿")
    models = commands.add_parser("models", help="分别列出本地模型目录及云模型目录")
    models.add_argument("--scope", choices=["all", "local", "cloud"], default="all")
    openapi = commands.add_parser("openapi", help="查询服务端 OpenAPI 文档")
    openapi.add_argument("--filter", default="")
    openapi.add_argument("--method", type=str.upper, default="")
    chat = commands.add_parser("chat")
    chat.add_argument("message", nargs="?")
    chat.add_argument("--new", action="store_true", help="先创建新会话")
    _input_flags(chat)
    commands.add_parser("shell", help="交互终端：文本聊天，/命令，/help，/exit")
    analyze = commands.add_parser("analyze", help="读取服务端工作区内的文件预览")
    analyze.add_argument("path")
    draft = commands.add_parser("draft", help="调用现有 P2 AI 草稿 API；不会自动创建 edit")
    draft.add_argument("path")
    draft.add_argument("--instruction")
    _input_flags(draft)
    edit = commands.add_parser("edit", help="创建修改提案（--create 可能创建父目录）")
    edit.add_argument("path")
    edit.add_argument("--create", action="store_true")
    _input_flags(edit)
    diff = commands.add_parser("diff")
    diff.add_argument("edit_id")
    apply = commands.add_parser("apply", help="执行已检查的提案，需 P2，绝不自动重试")
    apply.add_argument("edit_id")
    apply.add_argument("--confirm", action="store_true", help="明确确认执行此 edit_id")
    return result


def _input_flags(command: argparse.ArgumentParser) -> None:
    source = command.add_mutually_exclusive_group()
    source.add_argument("--file", type=Path, help="读取本地 UTF-8 文件")
    source.add_argument("--stdin", action="store_true", help="从 stdin 读取全部内容")


def _read_input(args: argparse.Namespace, inline: str | None = None) -> str | None:
    if inline is not None and (args.file or args.stdin):
        raise BrainError("内联文本与 --file/--stdin 只能选择一个")
    if args.file:
        return Path(args.file).read_text(encoding="utf-8")
    if args.stdin:
        return sys.stdin.read()
    return inline


def _secret(prompt: str) -> str:
    if not sys.stdin.isatty():
        raise BrainError("安全交互输入需要终端；密码可使用 --password-stdin，P2 可用环境变量")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            return getpass.getpass(prompt)
    except getpass.GetPassWarning as exc:
        raise BrainError("终端不支持隐藏输入；已拒绝回显密码/token") from exc


def _p2_token() -> str:
    token = os.environ.get("XCAGI_BRAIN_P2_TOKEN") or _secret("P2 token: ")
    if not token.strip():
        raise BrainError("P2 token 不能为空（环境变量 XCAGI_BRAIN_P2_TOKEN）")
    if any(ord(char) < 32 or ord(char) > 126 for char in token.strip()):
        raise BrainError("P2 token 含不支持的 HTTP header 字符，未发送请求")
    return token.strip()


def _collect(client: BrainClient, endpoints: dict[str, str]) -> dict:
    result: dict = {"success": True}
    for name, path in endpoints.items():
        try:
            result[name] = client.request("GET", path)
        except BrainError as exc:
            result["success"] = False
            result[name] = {"available": False, "error": str(exc)}
    return result


def execute(args: argparse.Namespace, client: BrainClient) -> dict:
    command = args.command
    if command in {"models", "analyze", "draft", "edit", "diff", "apply"}:
        client.require_login()
    if command == "login":
        if args.password_stdin and sys.stdin.isatty():
            raise BrainError("--password-stdin 仅用于管道；终端登录请使用默认隐藏输入")
        password = (
            sys.stdin.readline().rstrip("\r\n") if args.password_stdin else _secret("Password: ")
        )
        if not password:
            raise BrainError("密码不能为空")
        return client.login(
            args.username, password, args.account_kind, _secret("TOTP: ") if args.totp else ""
        )
    if command == "logout":
        return client.logout()
    if command == "status":
        result = _collect(
            client,
            {
                "health": "/api/health",
                "desktop": "/api/desktop/status",
                "code_editor": "/api/code-editor/status",
            },
        )
        if result["health"].get("status") in {"degraded", "unhealthy", "error"}:
            result["success"] = False
        result["tier"] = {
            "available": False,
            "reason": "无只读查询接口；P2 由 draft/apply API 校验",
        }
        result["draft_execution_verified"] = False
        return result
    if command == "models":
        endpoints = {}
        if args.scope in {"all", "local"}:
            endpoints["installed_local_models"] = "/api/desktop/models"
        if args.scope in {"all", "cloud"}:
            endpoints["cloud_catalog"] = "/api/market/llm-catalog"
        return _collect(client, endpoints)
    if command == "openapi":
        specification = client.request("GET", "/api/system/openapi")
        paths = specification.get("paths")
        if not isinstance(paths, dict):
            raise BrainError("OpenAPI 响应缺少 paths")
        rows = []
        for path, methods in paths.items():
            for method, detail in methods.items():
                if method.lower() not in {
                    "get",
                    "post",
                    "put",
                    "patch",
                    "delete",
                    "head",
                    "options",
                    "trace",
                }:
                    continue
                summary = detail.get("summary", "")
                if args.method and method.upper() != args.method:
                    continue
                if args.filter.lower() not in f"{method} {path} {summary}".lower():
                    continue
                rows.append({"method": method.upper(), "path": path, "summary": summary})
        return {"success": True, "count": len(rows), "routes": rows}
    if command == "chat":
        message = _read_input(args, args.message)
        if message is not None and not message.strip():
            raise BrainError("消息不能为空")
        if message is None and not args.new:
            raise BrainError("提供聊天内容，或使用 chat --new 创建会话")
        return client.chat(message, new=args.new)
    if command == "analyze":
        return client.request("POST", "/api/code-editor/analyze", {"path": args.path})
    if command == "draft":
        instruction = _read_input(args, args.instruction)
        if not instruction or not instruction.strip():
            raise BrainError("提供 --instruction、--file 或 --stdin")
        return client.request(
            "POST",
            "/api/code-editor/draft",
            {"path": args.path, "instruction": instruction},
            p2_token=_p2_token(),
        )
    if command == "edit":
        content = _read_input(args)
        if content is None:
            raise BrainError("edit 需要 --file 或 --stdin；空文件内容允许")
        return client.request(
            "POST",
            "/api/code-editor/edit",
            {
                "path": args.path,
                "new_content": content,
                "create_if_missing": args.create,
            },
        )
    if command == "diff":
        return client.proposal("diff", args.edit_id)
    if command == "apply":
        if not args.confirm:
            raise BrainError("apply 未发送：先查看 diff，再使用 apply EDIT_ID --confirm")
        return client.proposal("apply", args.edit_id, p2_token=_p2_token())
    raise BrainError(f"未知命令: {command}")


def _emit(value: dict, compact: bool, command: str = "") -> int:
    if compact:
        print(json.dumps(value, ensure_ascii=False))
    else:
        from .brain_output import format_output

        print(format_output(value, command))
    return 1 if value.get("success") is False else 0


def shell(args: argparse.Namespace, client: BrainClient) -> int:
    print("智脑终端：输入文本聊天；/new 新会话；/help 命令；/exit 退出。", file=sys.stderr)
    failed = 0
    while True:
        try:
            line = input("brain> " if sys.stdin.isatty() else "").strip()
        except EOFError:
            return failed
        if not line:
            continue
        if line in {"/exit", "/quit"}:
            return failed
        if line == "/help":
            parser().print_help()
            continue
        try:
            if not line.startswith("/"):
                failed |= _emit(client.chat(line), args.json, "chat")
                continue
            words = ["chat", "--new"] if line == "/new" else shlex.split(line[1:])
            inner = parser().parse_args(words)
            if (
                inner.command == "shell"
                or getattr(inner, "stdin", False)
                or getattr(inner, "password_stdin", False)
            ):
                raise BrainError("交互终端内不支持嵌套 shell 或 stdin 参数；请使用文件/安全提示")
            failed |= _emit(execute(inner, client), args.json, inner.command)
        except SystemExit as exc:
            failed |= int(bool(exc.code))
        except (BrainError, OSError, ValueError) as exc:
            print(terminal_text(f"错误: {exc}"), file=sys.stderr)
            failed = 1


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            raise BrainError("--timeout 必须大于 0")
        client = BrainClient(SessionStore(args.origin, args.session_dir), args.timeout)
        if args.command == "shell":
            return shell(args, client)
        return _emit(execute(args, client), args.json, args.command)
    except (BrainError, OSError, ValueError) as exc:
        print(terminal_text(f"错误: {exc}"), file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("已取消", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
