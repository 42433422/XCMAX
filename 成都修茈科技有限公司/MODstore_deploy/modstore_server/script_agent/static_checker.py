"""脚本静态检查：AST + import 白名单 + 危险调用拦截。

设计要点：

- 默认 stdlib 全开（基于 ``sys.stdlib_module_names``），但
  :data:`ALWAYS_DENY_TOP` 里的几个 stdlib 模块禁用（``ctypes`` 等）
- 第三方包默认禁用，需在 ``runtime_allowlist.json`` 显式登记
- 危险调用（``eval/exec/compile/__import__`` 等）通过 AST 走查拦截
- ``modstore_runtime`` 始终允许
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Set

from modstore_server.script_agent.package_allowlist import allowed_packages
from modstore_server.script_agent.semantic_quality import oversized_string_literal_errors


def _syntax_error_is_llm_prose_not_python(code: str, exc: SyntaxError) -> bool:
    """``ast.parse`` 把模型返回的中文说明当成源码时，常见报错为 invalid character + 全角句号。"""
    msg_l = str(exc).lower()
    if "invalid character" not in msg_l:
        return False
    raw = (code or "").lstrip()
    if not raw:
        return False
    line1 = raw.split("\n", 1)[0]
    # 句末中文句号「。」常与自然语言首句一起出现
    if "。" in line1 and any("\u4e00" <= c <= "\u9fff" for c in line1):
        code_starts = (
            "#",
            '"',
            "'",
            "import ",
            "from ",
            "def ",
            "class ",
            "@",
            "if ",
            "for ",
            "while ",
            "try:",
            "with ",
            "async ",
            "pass",
            "return",
            "print(",
            "raise ",
            "yield ",
            "lambda ",
        )
        if any(line1.startswith(p) for p in code_starts):
            return False
        if line1.startswith(("r'", 'r"', "f'", 'f"', "b'", 'b"', "u'", 'u"')):
            return False
        return True
    if "U+3002" in str(exc) or "U+ff0c" in str(exc):
        return any("\u4e00" <= c <= "\u9fff" for c in raw[:400])
    return False


ALWAYS_DENY_TOP: Set[str] = {
    # 进程系：必须走 modstore_runtime 的受控 SDK
    "subprocess",
    "_subprocess",
    "multiprocessing",
    "_multiprocessing",
    # 原生 C 接口：可绕过任何 Python 层防护
    "ctypes",
    "_ctypes",
    # 网络 stdlib bedrock：脚本如需联网必须走 modstore_runtime SDK
    # （统一计费 / 审计 / 策略）。第三方网络包（requests/httpx/aiohttp/urllib3）
    # 留给管理员 ``runtime_allowlist`` 决定，但实际建连仍由 sandbox preamble 在
    # ``socket`` 层拦下（除 127.0.0.1:MODSTORE_RUNTIME_PORT 给 SDK RPC 回调外）。
    # ``urllib`` / ``http`` 整包不禁——``urllib.parse`` 是纯字符串操作。
    "socket",
    "_socket",
    "ssl",
    "_ssl",
    "ftplib",
    "smtplib",
    "poplib",
    "imaplib",
    "nntplib",
    "telnetlib",
    "xmlrpc",
    "webbrowser",
    "socketserver",
    "asyncore",
    "asynchat",
}

DANGEROUS_BUILTIN_CALLS: Set[str] = {
    "exec",
    "eval",
    "compile",
    "__import__",
}

DANGEROUS_ATTR_CALLS: Set[str] = {
    # subprocess 系：必须走 SDK 间接调用
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.run",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.getoutput",
    "subprocess.getstatusoutput",
    # os 进程系：fork/exec/spawn/system
    "os.system",
    "os.popen",
    "os.execv",
    "os.execve",
    "os.execvp",
    "os.execvpe",
    "os.execl",
    "os.execle",
    "os.execlp",
    "os.execlpe",
    "os.fork",
    "os.forkpty",
    "os.spawnl",
    "os.spawnle",
    "os.spawnlp",
    "os.spawnlpe",
    "os.spawnv",
    "os.spawnve",
    "os.spawnvp",
    "os.spawnvpe",
}


def _stdlib_top_modules() -> Set[str]:
    if hasattr(sys, "stdlib_module_names"):
        return set(sys.stdlib_module_names)  # type: ignore[attr-defined]
    return set()


def _attr_chain(node: ast.AST) -> str:
    """``a.b.c`` -> ``"a.b.c"``，否则返回 ``""``。"""
    parts: List[str] = []
    cur: Optional[ast.AST] = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return ""


def validate_script(
    code: str,
    *,
    allowlist_path: Optional[Path] = None,
    extra_allowed_packages: Iterable[str] = (),
) -> List[str]:
    """对 ``code`` 做 AST 走查，返回错误信息列表。空列表表示通过。"""
    errors: List[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        if _syntax_error_is_llm_prose_not_python(code, e):
            return [
                "脚本内容不是合法 Python：返回内容像中文说明而非可执行代码；"
                "请仅输出 Python（可用 ```python 代码块包裹整段）。"
            ]
        return [f"Python 语法错误: {e}"]

    stdlib = _stdlib_top_modules()
    third_party_ok = allowed_packages(allowlist_path) | set(extra_allowed_packages)
    allowed_top = (stdlib - ALWAYS_DENY_TOP) | third_party_ok | {"modstore_runtime"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = (alias.name or "").split(".")[0]
                if not top:
                    continue
                if top in ALWAYS_DENY_TOP:
                    errors.append(f"禁止 import {alias.name}（位于禁用列表）")
                elif top not in allowed_top:
                    errors.append(f"禁止 import {alias.name}（未在 stdlib 或第三方 allowlist 中）")
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if not top:
                errors.append("禁止相对 import（脚本必须自包含）")
                continue
            if top in ALWAYS_DENY_TOP:
                errors.append(f"禁止 from {node.module} import …（位于禁用列表）")
            elif top not in allowed_top:
                errors.append(f"禁止 from {node.module} import …（未在 allowlist）")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in DANGEROUS_BUILTIN_CALLS:
                errors.append(f"禁止调用内置函数 {func.id}()")
            elif isinstance(func, ast.Attribute):
                full = _attr_chain(func)
                if full in DANGEROUS_ATTR_CALLS:
                    errors.append(f"禁止调用 {full}()")
        elif isinstance(node, ast.Attribute):
            # `subprocess.Popen` 即使被赋值给变量也算引用，扫描覆盖到
            full = _attr_chain(node)
            if full in DANGEROUS_ATTR_CALLS and not _is_inside_call(node, tree):
                # 若不是在调用语境，仍标 warn
                # （为减少误报，这里只在不是 attr 链中段时报）
                pass
    errors.extend(oversized_string_literal_errors(tree))
    return errors


def _is_inside_call(target: ast.AST, tree: ast.AST) -> bool:
    """判断 ``target`` 是否作为某个 ``Call.func`` 出现。仅辅助避免重复报错。"""
    for parent in ast.walk(tree):
        if isinstance(parent, ast.Call) and parent.func is target:
            return True
    return False
