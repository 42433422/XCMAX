#!/usr/bin/env python3
"""拦截新增明文凭据（密码默认值、硬编码令牌、命令行明文密码）。

只看 PR/提交范围内新增的行，不扫历史；输出只给 文件:行号:规则，绝不打印命中的值。
确属非凭据（如公开示例）时，在该行加 ``credential-guard: allow`` 注释，评审可见。
gitleaks 负责高熵令牌形态；本检查补它覆盖不到的短口令、默认值和 Markdown。

用法：
  python3 FHD/scripts/security/check_plaintext_credentials.py --base <sha> --head <sha>
  python3 FHD/scripts/security/check_plaintext_credentials.py --files a.py b.sh
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

ALLOW_MARK = "credential-guard: allow"
_SECRET_WORD = r"(?:PASSWORD|PASSWD|PWD|SECRET|TOKEN|API_?KEY|PRIVATE_?KEY|CREDENTIALS?)"
RULES: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    (
        "env-default-literal",
        re.compile(
            r"(?i)(?:environ\.get|getenv|setdefault)\(\s*[\"'][A-Z0-9_]*"
            + _SECRET_WORD
            + r"[A-Z0-9_]*[\"']\s*,\s*[\"']([^\"'\s]{4,})[\"']"
        ),
    ),
    (
        "js-env-fallback-literal",
        re.compile(
            r"(?i)process\.env\.[A-Z0-9_]*"
            + _SECRET_WORD
            + r"[A-Z0-9_]*\s*(?:\|\||\?\?)\s*[\"'`]([^\"'`\s]{4,})[\"'`]"
        ),
    ),
    (
        "js-env-assign-literal",
        re.compile(
            r"(?i)process\.env\.[A-Z0-9_]*"
            + _SECRET_WORD
            + r"[A-Z0-9_]*\s*=\s*[\"'`]([^\"'`\s]{4,})[\"'`]"
        ),
    ),
    (
        "shell-default-literal",
        re.compile(r"\$\{[A-Z0-9_]*" + _SECRET_WORD + r"[A-Z0-9_]*:?[-=]([^}\s$]{4,})\}"),
    ),
    (
        "cli-password-literal",
        re.compile(
            r"(?:sshpass\s+-p\s*|--password[= ]|redis-cli\b[^\n]*\s-a\s+)[\"']?([^\s\"'$<{]{4,})"
        ),
    ),
    (
        "password-assign-literal",
        re.compile(
            r"(?i)[\"']?\b[A-Za-z0-9_]*(?:password|passwd|pgpassword)\b[\"']?\s*[:=]\s*[\"']([^\"'\s]{4,})[\"']"
        ),
    ),
    (
        "secret-assign-literal",
        re.compile(
            r"(?i)\b[A-Za-z0-9_]*(?:secret|token|api_?key|private_?key)\b[\"']?\s*[:=]\s*[\"']([^\"'\s]{12,})[\"']"
        ),
    ),
)
_PLACEHOLDER = re.compile(
    r"(?i)^(?:\$|\{|<|%|\*+$|x{3,}|\.\.\.|changeme|change[-_]me|your[-_]|example|placeholder|dummy|fake|"
    r"redacted|replace|todo|none|null|undefined|true|false|secret[-_]?here|xxx|env:|vault:|cred:|\[)"
)
_SKIP_PATH = re.compile(
    r"(?:^|/)(?:tests?|__tests__|fixtures?|testdata)/|(?:^|/)test_[^/]*$|\.(?:test|spec)\.[cm]?[jt]sx?$"
    r"|(?:^|/)(?:package-lock\.json|pnpm-lock\.yaml|yarn\.lock|poetry\.lock|Pipfile\.lock)$"
    r"|\.(?:png|jpe?g|gif|ico|svg|webp|pdf|zip|gz|woff2?|ttf|mp4|db|sqlite)$"
    r"|(?:^|/)FHD/scripts/security/check_plaintext_credentials\.py$"
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}"


_FIELD_WORDS = {
    "password",
    "passwd",
    "pwd",
    "token",
    "secret",
    "apikey",
    "api_key",
    "access_token",
    "refresh_token",
    "bearer",
    "basic",
    "credentials",
    "credential",
}


def _looks_like_reference(value: str) -> bool:
    if _PLACEHOLDER.match(value) or value.lower() in _FIELD_WORDS or value.isdigit():
        return True
    # 环境变量名（列表）引用，如 OPENAI_API_KEY,CODEX_API_KEY。
    if "_" in value and re.fullmatch(r"[A-Z][A-Z0-9_]*(?:,[A-Z][A-Z0-9_]*)*", value):
        return True
    # 带分隔符的纯字母标识符（字段名、错误码、枚举值）不是口令。
    return bool(re.fullmatch(r"(?:[a-z]+(?:[_.][a-z]+)+|[A-Z]+(?:[_.][A-Z]+)+)", value))


def scan_line(path: str, line_no: int, text: str) -> List[Finding]:
    if ALLOW_MARK in text or len(text) > 600:
        return []
    found: List[Finding] = []
    for rule, pattern in RULES:
        for match in pattern.finditer(text):
            if not _looks_like_reference(match.group(1)):
                found.append(Finding(path, line_no, rule))
                break
    return found[:1]


def scan_added_lines(added: Iterable[Tuple[str, int, str]]) -> List[Finding]:
    out: List[Finding] = []
    for path, line_no, text in added:
        if _SKIP_PATH.search(path):
            continue
        out.extend(scan_line(path, line_no, text))
    return out


def _git_added_lines(base: str, head: str) -> List[Tuple[str, int, str]]:
    diff = subprocess.run(
        ["git", "diff", "--unified=0", "--no-color", "--no-ext-diff", "-M", f"{base}...{head}"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout
    added: List[Tuple[str, int, str]] = []
    path, line_no = "", 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:].strip()
            path = (
                "" if target == "/dev/null" else target[2:] if target.startswith("b/") else target
            )
            path = path.strip('"')
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            line_no = int(m.group(1)) if m else 0
        elif raw.startswith("+") and path:
            added.append((path, line_no, raw[1:]))
            line_no += 1
    return added


def _file_lines(files: Sequence[str]) -> List[Tuple[str, int, str]]:
    added: List[Tuple[str, int, str]] = []
    for name in files:
        text = Path(name).read_text(encoding="utf-8", errors="replace")
        added.extend((name, i, line) for i, line in enumerate(text.splitlines(), 1))
    return added


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--files", nargs="*")
    args = parser.parse_args(argv)
    if args.files:
        added = _file_lines(args.files)
    elif args.base:
        added = _git_added_lines(args.base, args.head)
    else:
        parser.error("需要 --base/--head 或 --files")
    findings = scan_added_lines(added)
    for item in findings:
        print(item.render())
    if findings:
        print(
            f"credential-guard: 发现 {len(findings)} 处新增明文凭据（值已隐藏）。"
            "请改为经凭据层/密钥库读取；确属非凭据时在该行加 `credential-guard: allow`。",
            file=sys.stderr,
        )
        return 1
    print(f"credential-guard: 新增 {len(added)} 行，无明文凭据。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
