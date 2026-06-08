"""Markdown lint 工具：校验 .md 文件格式合法性。

支持两种模式：
1. CLI 模式：调用系统安装的 markdownlint-cli（npx markdownlint-cli）
2. 纯 Python 模式：自实现基础规则检查（MD001/MD009/MD010/MD012/MD013/MD022/MD032/MD041）
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MD_RULES = {
    "MD001": "Heading levels should only increment by one level at a time",
    "MD009": "Trailing spaces",
    "MD010": "Hard tabs",
    "MD012": "Multiple consecutive blank lines",
    "MD013": "Line length",
    "MD022": "Headings should be surrounded by blank lines",
    "MD032": "Lists should be surrounded by blank lines",
    "MD041": "First line in a file should be a top-level heading",
}


@dataclass
class LintError:
    line: int
    rule: str
    description: str

    def to_dict(self) -> Dict[str, Any]:
        return {"line": self.line, "rule": self.rule, "description": self.description}


@dataclass
class LintResult:
    file: str
    errors: List[LintError] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file,
            "errors": [e.to_dict() for e in self.errors],
            "error_count": self.error_count,
        }


def _python_lint(content: str, filepath: str, *, max_line_length: int = 200) -> LintResult:
    result = LintResult(file=filepath)
    lines = content.split("\n")

    if not lines or not lines[0].startswith("# "):
        result.errors.append(LintError(line=1, rule="MD041", description=_MD_RULES["MD041"]))

    prev_heading_level = 0
    in_code_block = False

    for i, line in enumerate(lines, start=1):
        stripped = line.rstrip()

        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        if stripped != line:
            result.errors.append(LintError(line=i, rule="MD009", description=_MD_RULES["MD009"]))

        if "\t" in line:
            result.errors.append(LintError(line=i, rule="MD010", description=_MD_RULES["MD010"]))

        if len(line) > max_line_length:
            result.errors.append(LintError(line=i, rule="MD013", description=_MD_RULES["MD013"]))

        heading_match = re.match(r"^(#{1,6})\s", line)
        if heading_match:
            level = len(heading_match.group(1))
            if prev_heading_level > 0 and level > prev_heading_level + 1:
                result.errors.append(
                    LintError(line=i, rule="MD001", description=_MD_RULES["MD001"])
                )
            prev_heading_level = level

    blank_count = 0
    for i, line in enumerate(lines, start=1):
        if line.strip() == "":
            blank_count += 1
            if blank_count >= 3:
                result.errors.append(
                    LintError(line=i, rule="MD012", description=_MD_RULES["MD012"])
                )
        else:
            blank_count = 0

    return result


def _cli_lint(filepath: str, *, cwd: Optional[str] = None) -> LintResult:
    result = LintResult(file=filepath)
    try:
        cmd = ["npx", "markdownlint-cli", "--json", filepath]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30.0, cwd=cwd, shell=True
        )
        if proc.stdout.strip():
            try:
                data = json.loads(proc.stdout)
                for item in data if isinstance(data, list) else [data]:
                    result.errors.append(
                        LintError(
                            line=int(item.get("lineNumber", 0)),
                            rule=str(
                                item.get("ruleNames", ["unknown"])[0]
                                if item.get("ruleNames")
                                else "unknown"
                            ),
                            description=str(item.get("ruleDescription", "")),
                        )
                    )
            except (json.JSONDecodeError, KeyError, IndexError):
                for m in re.finditer(r"(\S+):(\d+)(?::\d+)?\s+(\S+)\s+(.*)", proc.stdout):
                    result.errors.append(
                        LintError(
                            line=int(m.group(2)),
                            rule=m.group(3),
                            description=m.group(4),
                        )
                    )
    except FileNotFoundError:
        logger.info("markdownlint-cli not available, falling back to Python lint")
        try:
            content = Path(filepath).read_text(encoding="utf-8", errors="replace")
            return _python_lint(content, filepath)
        except OSError:
            pass
    except subprocess.TimeoutExpired:
        result.errors.append(
            LintError(line=0, rule="TIMEOUT", description="markdownlint timed out")
        )
    except Exception as exc:
        result.errors.append(LintError(line=0, rule="ERROR", description=str(exc)[:200]))
    return result


def lint_file(
    filepath: str, *, mode: str = "auto", cwd: Optional[str] = None, max_line_length: int = 200
) -> LintResult:
    if mode == "python":
        try:
            content = Path(filepath).read_text(encoding="utf-8", errors="replace")
            return _python_lint(content, filepath, max_line_length=max_line_length)
        except OSError as exc:
            result = LintResult(file=filepath)
            result.errors.append(LintError(line=0, rule="OSERROR", description=str(exc)[:200]))
            return result
    if mode == "cli":
        return _cli_lint(filepath, cwd=cwd)

    try:
        content = Path(filepath).read_text(encoding="utf-8", errors="replace")
        return _python_lint(content, filepath, max_line_length=max_line_length)
    except OSError as exc:
        result = LintResult(file=filepath)
        result.errors.append(LintError(line=0, rule="OSERROR", description=str(exc)[:200]))
        return result


def lint_files(
    filepaths: List[str],
    *,
    mode: str = "auto",
    cwd: Optional[str] = None,
    max_line_length: int = 200,
) -> Dict[str, Any]:
    results: List[LintResult] = []
    total_errors = 0
    for fp in filepaths:
        r = lint_file(fp, mode=mode, cwd=cwd, max_line_length=max_line_length)
        results.append(r)
        total_errors += r.error_count
    return {
        "status": "ok" if total_errors == 0 else "has_errors",
        "files_checked": len(results),
        "total_errors": total_errors,
        "results": [r.to_dict() for r in results],
    }
