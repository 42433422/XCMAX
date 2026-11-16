"""Shared Issue authorization policy; execution stays inside Para / DevFleet.

Legacy Para receipts retain these policy helpers for reconciliation. The former
local LLM/file-writing/PR engine was retired with the Para execution boundary.
"""

from __future__ import annotations

import json
import logging
import os
import posixpath
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
FHD_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = FHD_ROOT.parent
DEFAULT_ALLOWLIST_PATH = REPO_ROOT / "config" / "auto-implement-allowlist.yaml"
MAX_CHANGED_FILES = 5
APPROVAL_COMMANDS = {"确认实现", "/approve-implementation"}
SAFE_SOURCE_SUFFIXES = {".py", ".ts", ".vue", ".js", ".json", ".md", ".yml", ".yaml", ".sh"}


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _gh_get(url: str, token: str) -> dict[str, Any]:
    """轻量 GitHub API GET（不引入 PyGithub 依赖也可工作）。"""
    import urllib.request

    req = urllib.request.Request(url, headers=_github_headers(token), method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _gh_post(url: str, token: str, body: dict[str, Any]) -> dict[str, Any]:
    import urllib.request

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_github_headers(token), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"_error": exc.code, "_body": exc.read().decode("utf-8", errors="replace")}


def _fetch_issue(repo: str, issue_number: int, token: str) -> dict[str, Any]:
    return _gh_get(f"https://api.github.com/repos/{repo}/issues/{issue_number}", token)


def _fetch_issue_comments(repo: str, issue_number: int, token: str) -> list[dict[str, Any]]:
    return _gh_get(
        f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments?per_page=100",
        token,
    )


def _has_aimplement_label(issue: dict[str, Any]) -> bool:
    labels = issue.get("labels") or []
    return any(
        str(lb.get("name") or "").strip() == "ai-implement" for lb in labels if isinstance(lb, dict)
    )


def _issue_label_names(issue: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for lb in issue.get("labels") or []:
        if not isinstance(lb, dict):
            continue
        name = str(lb.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def _allowlist_path() -> Path:
    override = (os.environ.get("AUTO_IMPLEMENT_ALLOWLIST_PATH") or "").strip()
    return Path(override) if override else DEFAULT_ALLOWLIST_PATH


def _load_allowlist_patterns(path: Path | None = None) -> list[str]:
    """读取域预授权 label regex 列表；文件缺失/禁用时返回空列表。"""
    cfg_path = path or _allowlist_path()
    if not cfg_path.is_file():
        return []
    try:
        text = cfg_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("allowlist read failed: %s", exc)
        return []
    try:
        import yaml
    except ImportError:
        data = _parse_allowlist_fallback(text)
    else:
        try:
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError:
            return []
    if not isinstance(data, dict) or not data.get("enabled", True):
        return []
    patterns = data.get("label_patterns") or []
    if not isinstance(patterns, list):
        return []
    return [str(p).strip() for p in patterns if str(p).strip()]


def _parse_allowlist_fallback(text: str) -> dict[str, Any]:
    """无 PyYAML 时的极简解析：只认 enabled / label_patterns 列表项。"""
    enabled = True
    patterns: list[str] = []
    in_patterns = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("enabled:"):
            val = stripped.split(":", 1)[1].strip().lower()
            enabled = val in ("true", "1", "yes")
            in_patterns = False
            continue
        if stripped.startswith("label_patterns:"):
            in_patterns = True
            continue
        if in_patterns and stripped.startswith("- "):
            item = stripped[2:].strip().strip("\"'")
            if item:
                patterns.append(item)
            continue
        if not line.startswith((" ", "\t")):
            in_patterns = False
    return {"enabled": enabled, "label_patterns": patterns}


def _allowlist_preauthorized(
    issue: dict[str, Any], *, patterns: list[str] | None = None
) -> tuple[bool, str]:
    """方案 B：issue 标签命中 allowlist regex 则视为预授权。"""
    pats = patterns if patterns is not None else _load_allowlist_patterns()
    if not pats:
        return False, "allowlist 未配置或未启用"
    names = _issue_label_names(issue)
    for name in names:
        for pat in pats:
            try:
                if re.fullmatch(pat, name):
                    return True, f"域预授权命中 label `{name}` (pattern={pat})"
            except re.error as exc:
                logger.warning("invalid allowlist pattern %r: %s", pat, exc)
    return False, "未命中域预授权 allowlist"


def _owner_confirmed(
    issue: dict[str, Any], comments: list[dict[str, Any]], repo: str
) -> tuple[bool, str]:
    """Require an exact repository-owner approval command in a comment.

    Issue bodies are untrusted implementation inputs and must never authorize
    themselves.  Likewise, the issue author may be a bot and is not equivalent
    to the repository owner.  GitHub's durable ``author_association=OWNER``
    assertion plus an exact command is the authorization boundary.
    """
    for c in comments:
        if str(c.get("author_association") or "").strip().upper() != "OWNER":
            continue
        body = str(c.get("body") or "").strip().lower()
        if body not in {command.casefold() for command in APPROVAL_COMMANDS}:
            continue
        author = str((c.get("user") or {}).get("login") or "owner")
        return True, f"repository owner @{author} issued exact approval command"
    commands = ", ".join(sorted(APPROVAL_COMMANDS))
    return False, f"repository owner 未提交精确批准命令（{commands}）"


def _is_authorized(
    issue: dict[str, Any], comments: list[dict[str, Any]], repo: str
) -> tuple[bool, str, str]:
    """授权：域预授权 allowlist 命中，或 repository owner 精确命令确认。

    返回 (authorized, reason, source)，source ∈ {"allowlist", "owner", ""}：
      - allowlist: 命中 config/auto-implement-allowlist.yaml:label_patterns，授权执行
      - owner:     repository owner 精确评论命令，授权执行

    授权来源不决定代码风险；LLM 代码统一进入 risk:r2 独立审查。
    """
    pre_ok, pre_reason = _allowlist_preauthorized(issue)
    if pre_ok:
        return True, pre_reason, "allowlist"
    owner_ok, owner_reason = _owner_confirmed(issue, comments, repo)
    if owner_ok:
        return True, owner_reason, "owner"
    return False, owner_reason, ""


def _estimate_files(issue_title: str, issue_body: str) -> int:
    """估算源码/配置/文档范围，排除日志中的产物并合并同一文件的路径别名。"""
    text = f"{issue_title}\n{issue_body}"
    paths = re.findall(
        r"(?:[A-Za-z]:)?[A-Za-z0-9_./-]+\.[A-Za-z0-9_]+(?![A-Za-z0-9_/-])",
        text.replace("\\", "/"),
    )
    generated_dirs = {
        "test_reports",
        "shard-evidence",
        "coverage",
        "htmlcov",
        "site-packages",
        "node_modules",
        ".pytest_cache",
        "__pycache__",
    }
    explicit: set[str] = set()
    for path in paths:
        # Check the complete suffix: a .jsonl log is not a .json source file.
        if Path(path).suffix.lower() not in SAFE_SOURCE_SUFFIXES | {".toml", ".ini", ".cfg"}:
            continue
        path = re.sub(
            r"^(?:/home/runner/work|/__w|[A-Za-z]:/a)/[^/]+/[^/]+/|^/github/workspace/",
            "",
            posixpath.normpath(re.sub(r"/+", "/", path)),
        ).removeprefix("FHD/")
        parts = path.split("/")
        if generated_dirs.intersection(parts[:-1]) or parts[-1] == "shard-summary.json":
            continue
        explicit.add(path)
    count = len(explicit)
    if re.search(r"新增|新建|add new|create new|scaffold", text, re.IGNORECASE):
        count += 2
    has_test = any(
        re.search(r"(^|/)(tests?|__tests__)/|(^|/)test_[^/]+$|(?:_test|\.test|\.spec)\.[^/]+$", p)
        for p in explicit
    )
    if not has_test and re.search(r"测试|\b(?:tests?|specs?)\b", text, re.IGNORECASE):
        count += 1
    return max(1, count)


if __name__ == "__main__":
    raise SystemExit("本地实现引擎已退役；请从管理端或 GitHub AI Issue Implement 工作流派工")
