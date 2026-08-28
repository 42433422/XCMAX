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

# The apex domain already owns the MODstore compatibility surface under
# /admin.  Serve the full FHD management console from the canonical www TLS
# vhost instead, while keeping every other www request redirected to the apex
# site.  This avoids two different SPAs fighting over the same origin/path.
WWW_MANAGED_INCLUDES = ("include /etc/nginx/snippets/admin-console-www.inc.conf;",)

MANAGED_LOCATION_HEADERS = (
    "location ~ ^/(styles\\.css|main\\.js|contact-intake\\.js|contact-channels\\.js|visualization\\.js|world-will\\.js|world-will-ticker\\.js|world-will-ticker\\.css)$ {",
    "location = /admin/founder-autonomy {",
    "location = /admin/founder-autonomy/ {",
    "location = /admin {",
    "location = /admin/ {",
    "location ^~ /admin/assets/ {",
    "location = /admin/vite.svg {",
    "location = /api/xcmax/ops/founder-autonomy {",
    "location = /download-founder-autonomy.json {",
    "location ^~ /market/assets/assets/ {",
    "location ^~ /market/assets/ {",
    "location = /market/main.js {",
    "location = /market/styles.css {",
    "location = /market {",
    "location /market/ {",
    "location = /site/main.js {",
    "location = /site/styles.css {",
    "location = /download-release.json {",
    "location /releases/stable/ {",
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


def _server_names(lines: list[str], start: int, end: int) -> set[str]:
    body = "\n".join(lines[start : end + 1])
    names: set[str] = set()
    for match in re.finditer(r"\bserver_name\s+([^;]+);", body):
        names.update(match.group(1).split())
    return names


def _select_tls_server(
    lines: list[str], blocks: list[tuple[int, int]], hostname: str
) -> tuple[int, int]:
    candidates: list[tuple[bool, bool, int, int]] = []
    for start, end in blocks:
        names = _server_names(lines, start, end)
        if hostname not in names:
            continue
        body = "\n".join(lines[start : end + 1])
        candidates.append(
            (
                bool(re.search(r"\blisten\b[^;]*\b443\b", body)),
                names == {hostname},
                start,
                end,
            )
        )
    if not candidates:
        raise ValueError(f"cannot find nginx server block for {hostname}")
    tls, _exact, start, end = max(candidates)
    if not tls:
        raise ValueError(f"cannot find TLS nginx server block for {hostname}")
    return start, end


def _strip_legacy_blocks(text: str) -> str:
    # Repair the partially deleted assets location left by the former inline
    # updater. Use line structure instead of whitespace-sensitive regex because
    # the production file has passed through several generations of formatters.
    lines = text.splitlines()
    asset_alias = "alias /root/成都修茈科技有限公司/MODstore_deploy/market/dist/assets/;"
    for alias_index, line in enumerate(lines):
        if asset_alias not in line:
            continue
        search_start = max(0, alias_index - 10)
        comment_index = next(
            (
                index
                for index in range(alias_index - 1, search_start - 1, -1)
                if "market 静态 chunk" in lines[index]
            ),
            None,
        )
        if comment_index is None:
            continue
        if any(
            "location" in candidate and "{" in candidate
            for candidate in lines[comment_index:alias_index]
        ):
            continue
        closing_index = next(
            (
                index
                for index in range(alias_index + 1, min(len(lines), alias_index + 10))
                if lines[index].strip() == "}"
            ),
            None,
        )
        if closing_index is not None:
            del lines[comment_index : closing_index + 1]
            text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
        break

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
        r"(?m)^[ \t]*# market 静态 chunk：[^\n]*\n(?:^[ \t]*\n)*"
        r"^[ \t]+alias[ \t]+/root/成都修茈科技有限公司/MODstore_deploy/market/dist/assets/;[ \t]*\n"
        r"^[ \t]+add_header[ \t]+Cache-Control[ \t]+\"public, max-age=31536000, immutable\";[ \t]*\n"
        r"(?:^[ \t]*\n)*^[ \t]*\}[ \t]*\n",
        "",
        text,
    )
    return text


def _is_managed_location(line: str) -> bool:
    header = " ".join(line.strip().split())
    return header in MANAGED_LOCATION_HEADERS or header.startswith("location ~ ^/xcagi-v")


def _strip_managed_locations(text: str) -> str:
    """Remove direct locations now owned by the managed snippet files."""

    lines = text.splitlines()
    index = 0
    while index < len(lines):
        if not _is_managed_location(lines[index]):
            index += 1
            continue
        depth = 0
        closing_index: int | None = None
        for candidate_index in range(index, len(lines)):
            syntax = _nginx_syntax(lines[candidate_index])
            depth += syntax.count("{") - syntax.count("}")
            if depth == 0:
                closing_index = candidate_index
                break
        if closing_index is None:
            raise ValueError(f"unclosed managed nginx location at line {index + 1}")
        del lines[index : closing_index + 1]
        while index < len(lines) and not lines[index].strip():
            del lines[index]
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def merge_managed_includes(text: str) -> str:
    """Return an idempotent config with apex and isolated www includes."""

    text = _strip_legacy_blocks(text)
    text = _strip_managed_locations(text)
    managed = {*MANAGED_INCLUDES, *WWW_MANAGED_INCLUDES}
    # A previous deploy inserted these lines beside every marker, including a
    # marker nested in `location`. Remove all managed lines before rebuilding.
    lines = [line for line in text.splitlines() if line.strip() not in managed]
    blocks = _server_blocks(lines)
    _apex_start, apex_end = _select_tls_server(lines, blocks, "xiu-ci.com")
    try:
        www_start, www_end = _select_tls_server(lines, blocks, "www.xiu-ci.com")
    except ValueError:
        www_start = www_end = -1
    if www_start >= 0 and _server_names(lines, www_start, www_end) != {"www.xiu-ci.com"}:
        # A combined legacy vhost cannot safely host the isolated management
        # locations without also shadowing the apex MODstore routes.
        www_start = www_end = -1

    # A server-scope return runs before location selection.  Move the redirect
    # into the managed snippet's fallback `location /` so /admin and /api can
    # reach FHD on the www-only management origin.
    redirect = "return 301 https://xiu-ci.com$request_uri;"
    if www_start >= 0:
        lines = [
            line
            for index, line in enumerate(lines)
            if not (www_start < index < www_end and line.strip() == redirect)
        ]

    blocks = _server_blocks(lines)
    _apex_start, apex_end = _select_tls_server(lines, blocks, "xiu-ci.com")
    insertions: list[tuple[int, tuple[str, ...]]] = [(apex_end, MANAGED_INCLUDES)]
    if www_start >= 0:
        _www_start, www_end = _select_tls_server(lines, blocks, "www.xiu-ci.com")
        insertions.append((www_end, WWW_MANAGED_INCLUDES))
    for end, includes in sorted(insertions, reverse=True):
        while end > 0 and not lines[end - 1].strip():
            del lines[end - 1]
            end -= 1
        inserted = [f"    {include}" for include in includes]
        lines[end:end] = ["", *inserted]
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
