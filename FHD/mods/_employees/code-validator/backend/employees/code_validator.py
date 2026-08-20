"""Deterministic, read-only source-code policy validator."""

from __future__ import annotations

import ast
from typing import Any

_BLOCKED_IMPORTS = {"requests", "httpx", "socket", "subprocess"}
_BLOCKED_CALLS = {
    "__import__",
    "eval",
    "exec",
    "os.popen",
    "os.remove",
    "os.system",
    "pathlib.Path.unlink",
    "shutil.rmtree",
    "subprocess.call",
    "subprocess.Popen",
    "subprocess.run",
}


def _call_name(node: ast.Call) -> str:
    current: ast.AST = node.func
    parts: list[str] = []
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def run(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("source")
    language = str(payload.get("language") or "python").strip().lower()
    if not isinstance(source, str) or not source.strip():
        return _failed("source is required", "missing_source")
    if language not in {"py", "python"}:
        return _failed("only deterministic Python validation is supported", "unsupported_language")

    issues: list[dict[str, Any]] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        issues.append(
            {
                "code": "syntax_error",
                "line": int(exc.lineno or 0),
                "detail": str(exc.msg or "invalid syntax"),
            }
        )
        tree = None

    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    if root in _BLOCKED_IMPORTS:
                        issues.append(
                            {
                                "code": "blocked_import",
                                "line": node.lineno,
                                "symbol": alias.name,
                            }
                        )
            elif isinstance(node, ast.ImportFrom):
                root = str(node.module or "").split(".", 1)[0]
                if root in _BLOCKED_IMPORTS:
                    issues.append(
                        {
                            "code": "blocked_import",
                            "line": node.lineno,
                            "symbol": node.module,
                        }
                    )
            elif isinstance(node, ast.Call):
                symbol = _call_name(node)
                if symbol in _BLOCKED_CALLS:
                    issues.append({"code": "blocked_call", "line": node.lineno, "symbol": symbol})

    approved = tree is not None and not issues
    return {
        "ok": True,
        "status": "approved" if approved else "rejected",
        "summary": (
            f"Python 源码已完成确定性只读校验：语法{'通过' if tree is not None else '失败'}，"
            f"发现 {len(issues)} 个阻塞项；未执行输入代码。"
        ),
        "syntax_valid": tree is not None,
        "safe": approved,
        "issues": issues,
        "evidence": [
            "python.ast.parse",
            "blocked import policy",
            "blocked call policy",
        ],
        "read_only": True,
        "side_effects": [],
    }


def _failed(message: str, code: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "failed",
        "summary": message,
        "error_code": code,
        "evidence": [],
        "read_only": True,
        "side_effects": [],
    }
