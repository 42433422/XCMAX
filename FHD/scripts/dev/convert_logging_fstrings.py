#!/usr/bin/env python3
"""把 ``app/`` 下 ``logger.<level>(f"...")`` 的 f-string 日志转换为惰性 %s 格式（消除 G004）。

策略（保守、可验证）：
- 仅转换可安全映射的占位符：``{expr}`` 无格式说明符 / 无转换符 → ``%s``。
- 含 ``:`` 格式说明符、``!r`` 等转换符、自文档 ``{x=}``、嵌套动态的 → 不转换，
  在该诊断物理行末尾追加 ``# noqa: G004``（仅当 f-string 单行时；多行的留待人工）。
- 用 ``ast`` 定位 logger 调用与其首个 f-string 实参（整体 JoinedStr 位置在 3.11 稳定），
  随后用自写解析器逐字符改写 ``{...}``/``{{``/``}}``/``%``，保留原引号与原转义序列，
  不依赖 3.11 f-string 内部位置（避免切错）。

用法：
    python scripts/dev/convert_logging_fstrings.py --check   # 仅统计
    python scripts/dev/convert_logging_fstrings.py           # 就地改写 app/
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

LOG_METHODS = {
    "debug",
    "info",
    "warning",
    "warn",
    "error",
    "exception",
    "critical",
    "fatal",
}


def _receiver_name(value: ast.expr) -> str:
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        return value.attr
    return ""


def _is_logger_call(node: ast.Call) -> bool:
    if not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr not in LOG_METHODS:
        return False
    name = _receiver_name(node.func.value).lower()
    return "log" in name


def _split_literal(lit: str) -> tuple[str, str, str] | None:
    """拆 f-string 字面量为 (前缀, 引号, body)。非 f-string 返回 None。"""
    i = 0
    while i < len(lit) and lit[i] not in "'\"":
        i += 1
    prefix = lit[:i]
    if "f" not in prefix.lower():
        return None
    rest = lit[i:]
    if rest[:3] in ('"""', "'''"):
        quote = rest[:3]
    elif rest and rest[0] in "'\"":
        quote = rest[0]
    else:
        return None
    if len(rest) < 2 * len(quote):
        return None
    body = rest[len(quote) : -len(quote)]
    return prefix, quote, body


def _convert_body(body: str) -> tuple[str, list[str]] | None:
    """改写 body：``{expr}`` → ``%s`` 并收集 expr。不可安全转换返回 None。"""
    out: list[str] = []
    args: list[str] = []
    j = 0
    n = len(body)
    while j < n:
        c = body[j]
        if c == "{":
            if j + 1 < n and body[j + 1] == "{":
                out.append("{")
                j += 2
                continue
            j += 1
            depth = 0
            quote: str | None = None
            start = j
            while j < n:
                cc = body[j]
                if quote:
                    if cc == quote:
                        quote = None
                    j += 1
                    continue
                if cc in "'\"":
                    quote = cc
                    j += 1
                    continue
                if cc in "([{":
                    depth += 1
                    j += 1
                    continue
                if cc in ")]":
                    depth -= 1
                    j += 1
                    continue
                if cc == "}":
                    if depth == 0:
                        break
                    depth -= 1
                    j += 1
                    continue
                if depth == 0 and cc == ":":
                    return None
                if depth == 0 and cc == "!" and (j + 1 >= n or body[j + 1] != "="):
                    return None
                if depth == 0 and cc == "=":
                    prevc = body[j - 1] if j > start else ""
                    nextc = body[j + 1] if j + 1 < n else ""
                    if prevc not in "=!<>:" and nextc != "=":
                        return None
                j += 1
            if j >= n:
                return None
            expr = body[start:j].strip()
            if not expr:
                return None
            args.append(expr)
            out.append("%s")
            j += 1
        elif c == "}":
            if j + 1 < n and body[j + 1] == "}":
                out.append("}")
                j += 2
                continue
            return None
        elif c == "%":
            out.append("%%")
            j += 1
        else:
            out.append(c)
            j += 1
    return "".join(out), args


def _process_file(path: Path, *, write: bool) -> tuple[int, int, int]:
    """返回 (converted, noqa_added, skipped_multiline)。"""
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return (0, 0, 0)

    src_bytes = src.encode("utf-8")
    # 每行起始字节偏移（col_offset 为 UTF-8 字节偏移，需在 bytes 上定位）。
    offsets = [0]
    for idx, byte in enumerate(src_bytes):
        if byte == 0x0A:
            offsets.append(idx + 1)

    def boff(lineno: int, col: int) -> int:
        return offsets[lineno - 1] + col

    edits: list[tuple[int, int, bytes]] = []
    noqa_lines: set[int] = set()
    skipped_multiline = 0

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _is_logger_call(node) and node.args):
            continue
        first = node.args[0]
        if not isinstance(first, ast.JoinedStr):
            continue
        if first.lineno is None or first.end_lineno is None:
            continue
        s = boff(first.lineno, first.col_offset)
        e = boff(first.end_lineno, first.end_col_offset)
        lit = src_bytes[s:e].decode("utf-8")
        split = _split_literal(lit)
        if split is None:
            continue
        prefix, quote, body = split
        conv = _convert_body(body)
        if conv is None:
            if first.lineno == first.end_lineno:
                noqa_lines.add(first.lineno)
            else:
                skipped_multiline += 1
            continue
        new_body, args = conv
        new_prefix = prefix.replace("f", "").replace("F", "")
        new_lit = new_prefix + quote + new_body + quote
        if args:
            new_lit += ", " + ", ".join(args)
        edits.append((s, e, new_lit.encode("utf-8")))

    if not edits and not noqa_lines:
        return (0, 0, skipped_multiline)

    new_bytes = src_bytes
    for s, e, repl in sorted(edits, key=lambda t: t[0], reverse=True):
        new_bytes = new_bytes[:s] + repl + new_bytes[e:]

    text = new_bytes.decode("utf-8")
    if noqa_lines:
        lines = text.split("\n")
        for ln in noqa_lines:
            if 1 <= ln <= len(lines) and "noqa" not in lines[ln - 1]:
                lines[ln - 1] = lines[ln - 1].rstrip() + "  # noqa: G004"
        text = "\n".join(lines)

    if write:
        path.write_text(text, encoding="utf-8")
    return (len(edits), len(noqa_lines), skipped_multiline)


def main() -> int:
    write = "--check" not in sys.argv
    root = Path(__file__).resolve().parents[2] / "app"
    total_c = total_n = total_m = 0
    files = 0
    for py in sorted(root.rglob("*.py")):
        c, n, m = _process_file(py, write=write)
        if c or n or m:
            files += 1
        total_c += c
        total_n += n
        total_m += m
    mode = "WROTE" if write else "CHECK"
    print(
        f"[{mode}] files touched={files} converted={total_c} "
        f"noqa_added={total_n} skipped_multiline={total_m}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
