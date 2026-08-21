#!/usr/bin/env python3
"""Place XCMAX-managed nginx snippets at the xiu-ci.com server scope."""

from __future__ import annotations

import argparse
import os
import re
import tempfile
from pathlib import Path


MANAGED_INCLUDES = (
    "include /etc/nginx/snippets/marketing-site-static.inc.conf;",
    "include /etc/nginx/snippets/corp-main-styles.inc.conf;",
    "include /etc/nginx/snippets/xcagi-cos-alias.inc.conf;",
    "include /etc/nginx/snippets/market-static.inc.conf;",
    "include /etc/nginx/snippets/founder-autonomy-admin.inc.conf;",
)


def _nginx_syntax(line: str) -> str:
    """Return text whose braces are structural, excluding quotes and comments."""

    result: list[str] = []
    quote: str | None = None
    escaped = False
    for char in line:
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote is not None:
            escaped = True
            continue
        if quote is not None:
            if char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
            continue
        if char == "#":
            break
        result.append(char)
    return "".join(result)


def _server_blocks(lines: list[str]) -> list[tuple[int, int]]:
    blocks: list[tuple[int, int]] = []
    stack: list[tuple[int, int]] = []
    depth = 0

    for index, line in enumerate(lines):
        syntax = _nginx_syntax(line)
        opens = syntax.count("{")
        closes = syntax.count("}")
        if re.match(r"^\s*server\s*\{", syntax):
            stack.append((index, depth + 1))
        depth += opens - closes
        if depth < 0:
            recent = ", ".join(f"{start + 1}-{end + 1}" for start, end in blocks[-4:])
            context = "\n".join(
                f"{line_no + 1}: {lines[line_no]}"
                for line_no in range(max(0, index - 8), min(len(lines), index + 9))
            )
            prior_ends = "\n".join(
                f"prior server end {end + 1}: {lines[end]}" for _, end in blocks[-4:]
            )
            raise ValueError(
                f"unbalanced nginx closing brace at line {index + 1}; "
                f"recent server blocks={recent or 'none'}\n{prior_ends}\n{context}"
            )
        while stack and depth < stack[-1][1]:
            start, _ = stack.pop()
            blocks.append((start, index))

    if stack or depth:
        raise ValueError("unbalanced or unclosed nginx block")
    return blocks


def _strip_legacy_blocks(text: str) -> str:
    # Remove the dangerous full-site market SPA fallback.
    text = re.sub(
        r"\n    # MODstore 仅通过 /market/.*?\n",
        "\n",
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r"\n    # MODstore 前端根路径\n    location / \{\n"
        r"        root /root/成都修茈科技有限公司/MODstore_deploy/market/dist;\n"
        r"        index index\.html;\n"
        r"        try_files \$uri \$uri/ /index\.html;\n"
        r"        add_header Cache-Control \"no-cache\";\n    \}\n",
        "\n",
        text,
        count=1,
    )

    # Remove old duplicated market/COS blocks now owned by the snippets.
    blocks = (
        r"\n    # Vite 偶发解析出 /market/assets/assets/.*?location \^~ /market/assets/ \{[^}]+\}\n",
        r"\n    # 旧缓存页请求 /market/main\.js.*?add_header Cache-Control \"no-cache, must-revalidate\" always;\n    \}\n",
        r"\n    # market 静态 chunk：.*?location \^~ /market/assets/ \{[^}]+\}\n",
        r"\n    location /market/ \{\n        alias /root/成都修茈科技有限公司/MODstore_deploy/market/dist/;\n"
        r"        try_files \$uri \$uri/ /market/index\.html;[^}]+\}\n",
        r"\n    # 避免 /market/main\.js.*?location = /market/styles\.css \{[^}]+\}\n",
        r"\n    ## XCAGI_COS_ALIAS_BEGIN.*?## XCAGI_RELEASES_END\n",
    )
    for pattern in blocks:
        text = re.sub(pattern, "\n", text, flags=re.DOTALL)

    # An older non-atomic cleanup could delete only the opening `location`
    # line before nginx validation failed. Repair that exact production residue
    # before parsing block depth, otherwise its orphan `}` looks like the end of
    # the containing server block.
    text = re.sub(
        r"\n    # market 静态 chunk：[^\n]*\n(?:\s*\n)*"
        r"        alias /root/成都修茈科技有限公司/MODstore_deploy/market/dist/assets/;\n"
        r"        add_header Cache-Control \"public, max-age=31536000, immutable\";\n"
        r"(?:\s*\n)*    \}\n",
        "\n",
        text,
    )
    return text


def merge_managed_includes(text: str) -> str:
    """Return an idempotent config with includes in the TLS server block."""

    text = _strip_legacy_blocks(text)
    managed = set(MANAGED_INCLUDES)
    # A previous deploy inserted these lines beside every marker, including a
    # marker nested in `location`. Remove all managed lines before rebuilding.
    lines = [line for line in text.splitlines() if line.strip() not in managed]
    blocks = _server_blocks(lines)
    candidates: list[tuple[bool, int, int]] = []
    for start, end in blocks:
        body = "\n".join(lines[start : end + 1])
        if re.search(r"\bserver_name\b[^;]*\bxiu-ci\.com\b", body):
            candidates.append(
                (bool(re.search(r"\blisten\b[^;]*\b443\b", body)), start, end)
            )
    if not candidates:
        raise ValueError("cannot find nginx server block for xiu-ci.com")

    _, _, end = max(candidates)
    inserted = [f"    {include}" for include in MANAGED_INCLUDES]
    separator = [] if end > 0 and not lines[end - 1].strip() else [""]
    lines[end:end] = [*separator, *inserted]
    return "\n".join(lines).rstrip() + "\n"


def write_atomic(path: Path, text: str) -> None:
    mode = path.stat().st_mode
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "conf",
        nargs="?",
        type=Path,
        default=Path("/etc/nginx/conf.d/xiu-ci.com.conf"),
    )
    args = parser.parse_args()
    original = args.conf.read_text(encoding="utf-8")
    write_atomic(args.conf, merge_managed_includes(original))
    print(f"merged managed includes at xiu-ci.com server scope: {args.conf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
