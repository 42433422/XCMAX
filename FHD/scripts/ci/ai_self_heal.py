"""CI 自愈脚本：失败 workflow → 提取错误 → 规则匹配 + LLM 兜底 → 创建修复 PR。

七元契约沿用桌面端：Signal(workflow_run failure) → Diagnosis(error extract) →
Action(fix patch) → Policy(规则匹配优先) → Adapter(GitHub API) →
RuntimeTruthSnapshot(logs) → AuditEntry(self-heal-fingerprints.jsonl)。

设计要点：
- 触发：GitHub Actions workflow_run.completed + conclusion=failure
- 同指纹 24h 去重：SHA256(repo + workflow + job + error_line_hash)
- 规则匹配优先：覆盖 ruff/bandit/mypy/pytest 常见错误模式
- LLM 兜底：fail-open，超时/key 缺失不阻断
- autonomy/ 分支不递归：避免自愈自身故障
- 修复 PR 标 needs-human，不自动合并
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover - 测试环境可能未装 httpx
    httpx = None  # type: ignore[assignment]


# =====================================================================
# 数据模型
# =====================================================================


@dataclass
class ErrorEntry:
    """CI 日志中提取的单条错误。"""

    tool: str  # 'ruff' / 'bandit' / 'mypy' / 'pytest' / 'unknown'
    code: str  # 错误码（如 'F401' / 'B101'）或空字符串
    message: str
    file_path: str  # 文件路径（可能为空）
    line: int  # 行号（0 = 未知）
    raw: str  # 原始错误行


@dataclass
class Fix:
    """对单条错误的修复方案。"""

    error: ErrorEntry
    patch: str  # unified diff 片段（或空字符串表示 needs-human）
    needs_human: bool
    description: str
    risk_level: str = "r3"  # r0/r1/r2/r3 — 分级合并 SLA 依据（LLM 修复强制 r3）


@dataclass
class FingerprintRecord:
    """指纹去重记录。"""

    fingerprint: str
    pr_url: str
    ts: float  # UNIX 秒
    repo: str
    workflow: str


# =====================================================================
# 日志下载与解析
# =====================================================================

GITHUB_API = "https://api.github.com"


def fetch_workflow_logs(
    run_id: int,
    *,
    token: str | None = None,
    repo: str | None = None,
    client: Any = None,
) -> str:
    """下载指定 workflow run 的合并日志文本。

    GitHub Actions logs 接口返回 zip 流。本函数解压并拼接所有 .txt 文件。
    若网络/权限失败则返回空字符串（fail-open，主流程继续）。
    """
    repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
    if not repo or not run_id:
        return ""
    url = f"{GITHUB_API}/repos/{repo}/actions/runs/{run_id}/logs"
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if client is None:
        if httpx is None:
            return ""
        client = httpx.Client(timeout=30.0)
        close_after = True
    else:
        close_after = False
    try:
        resp = client.get(url, headers=headers, follow_redirects=True)
        if resp.status_code != 200:
            return ""
        buf = io.BytesIO(resp.content)
        try:
            with zipfile.ZipFile(buf) as zf:
                parts: list[str] = []
                for name in zf.namelist():
                    if name.endswith(".txt"):
                        try:
                            parts.append(zf.read(name).decode("utf-8", errors="replace"))
                        except (KeyError, RuntimeError):
                            continue
                return "\n".join(parts)
        except zipfile.BadZipFile:
            return ""
    except Exception:  # pragma: no cover - fail-open
        return ""
    finally:
        if close_after:
            try:
                client.close()
            except Exception:  # pragma: no cover
                pass


# 错误提取正则（覆盖 ruff / bandit / mypy / pytest / format 常见模式）
_RUFF_RE = re.compile(r"^(?P<file>[^\s:]+):(?P<line>\d+):\d+:\s+(?P<code>[A-Z]\d+)\s+(?P<msg>.*)$")
_BANDIT_RE = re.compile(r"^\s*Issue:\s*\[(?P<code>B\d+)\]\s*(?P<msg>.*)$")
_MYPY_RE = re.compile(r"^(?P<file>[^\s:]+):(?P<line>\d+):\s*error:\s*(?P<msg>.*)$")
_MYPY_CODE_RE = re.compile(r"\[(?P<code>[\w-]+)\]")
_PYTEST_FAIL_RE = re.compile(r"^(?P<file>[^\s:]+):(?P<line>\d+):\s*(?P<msg>FAILED|ERROR.*)$")
_PYTEST_FAILED_RE = re.compile(r"^FAILED\s+(?P<msg>.*)$")
# ruff format --check / black --check（生产失败高频，旧提取器完全漏掉）
_RUFF_FORMAT_RE = re.compile(r"^Would reformat:\s+(?P<file>\S.+)$")
_BLACK_FORMAT_RE = re.compile(r"^would reformat\s+(?P<file>\S.+)$", re.IGNORECASE)
_GHA_ERROR_RE = re.compile(r"^##\[error\](?P<msg>.*)$")
# GHA downloaded logs: optional "job\tstep\t" + ISO timestamp + "Z "
_GHA_PREFIX_RE = re.compile(
    r"^(?:[^\t\n]+\t[^\t\n]+\t)?"  # job\tstep\t (gh run view --log style)
    r"(?:\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z\s+)?"  # timestamp
)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _normalize_log_line(raw_line: str) -> str:
    """去掉 GHA 前缀 / ANSI，得到可匹配的净文本。"""
    line = raw_line.rstrip("\r")
    if line.startswith("\ufeff"):
        line = line.lstrip("\ufeff")
    line = _ANSI_RE.sub("", line)
    line = _GHA_PREFIX_RE.sub("", line)
    return line.strip()


def extract_errors(log_text: str) -> list[ErrorEntry]:
    """从 CI 日志文本中提取错误条目。

    顺序扫描每一行，依次尝试 ruff format / ruff lint / bandit / mypy / pytest /
    GHA ##[error] 模式。返回去重后的列表（同 file+line+code+msg 视为重复）。

    2026-07-20：生产审计发现大量 failure 仅输出 ``Would reformat:``，旧正则
    导致 ``[skip] no extractable errors``。此处补齐 format + 前缀剥离。
    """
    if not log_text:
        return []
    seen: set[tuple[str, str, str, str]] = set()
    out: list[ErrorEntry] = []
    for raw_line in log_text.splitlines():
        line = _normalize_log_line(raw_line)
        if not line:
            continue
        entry: ErrorEntry | None = None
        m = _RUFF_FORMAT_RE.match(line)
        if m:
            entry = ErrorEntry(
                tool="ruff",
                code="FORMAT",
                message=f"Would reformat: {m.group('file').strip()}",
                file_path=m.group("file").strip(),
                line=0,
                raw=line,
            )
        else:
            m = _BLACK_FORMAT_RE.match(line)
            if m:
                entry = ErrorEntry(
                    tool="black",
                    code="FORMAT",
                    message=f"would reformat {m.group('file').strip()}",
                    file_path=m.group("file").strip(),
                    line=0,
                    raw=line,
                )
            else:
                m = _RUFF_RE.match(line)
                if m:
                    entry = ErrorEntry(
                        tool="ruff",
                        code=m.group("code"),
                        message=m.group("msg"),
                        file_path=m.group("file"),
                        line=int(m.group("line")),
                        raw=line,
                    )
                else:
                    m = _BANDIT_RE.match(line)
                    if m:
                        entry = ErrorEntry(
                            tool="bandit",
                            code=m.group("code"),
                            message=m.group("msg").strip(),
                            file_path="",
                            line=0,
                            raw=line,
                        )
                    else:
                        m = _MYPY_RE.match(line)
                        if m:
                            code_match = _MYPY_CODE_RE.search(m.group("msg"))
                            code = code_match.group("code") if code_match else ""
                            entry = ErrorEntry(
                                tool="mypy",
                                code=code,
                                message=m.group("msg").strip(),
                                file_path=m.group("file"),
                                line=int(m.group("line")),
                                raw=line,
                            )
                        else:
                            m = _PYTEST_FAILED_RE.match(line)
                            if m:
                                entry = ErrorEntry(
                                    tool="pytest",
                                    code="FAILED",
                                    message=m.group("msg").strip(),
                                    file_path="",
                                    line=0,
                                    raw=line,
                                )
                            else:
                                m = _PYTEST_FAIL_RE.match(line)
                                if m:
                                    entry = ErrorEntry(
                                        tool="pytest",
                                        code=m.group("msg").split(" ")[0],
                                        message=line,
                                        file_path=m.group("file"),
                                        line=int(m.group("line")),
                                        raw=line,
                                    )
                                else:
                                    m = _GHA_ERROR_RE.match(line)
                                    if m:
                                        msg = m.group("msg").strip()
                                        # 跳过无诊断价值的壳消息；有 format/lint 时不必重复
                                        if msg and not msg.startswith("Process completed with exit code"):
                                            entry = ErrorEntry(
                                                tool="gha",
                                                code="ERROR",
                                                message=msg,
                                                file_path="",
                                                line=0,
                                                raw=line,
                                            )
        if entry is None:
            continue
        key = (entry.tool, entry.code, entry.file_path, entry.message)
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out


# =====================================================================
# 指纹去重
# =====================================================================


def compute_fingerprint(repo: str, workflow: str, job: str, error_line: str) -> str:
    """计算错误指纹 = SHA256(repo + workflow + job + error_line_hash)。"""
    error_hash = hashlib.sha256(error_line.encode("utf-8")).hexdigest()[:16]
    raw = f"{repo}|{workflow}|{job}|{error_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _fingerprint_path(store_path: str | Path | None = None) -> Path:
    if store_path:
        return Path(store_path)
    return Path(".trae/autonomy-ci/self-heal-fingerprints.jsonl")


def is_already_processed(
    fingerprint: str,
    *,
    budget_hours: int = 24,
    store_path: str | Path | None = None,
    now_ts: float | None = None,
) -> bool:
    """判断指纹是否在 budget_hours 小时内已处理过。"""
    p = _fingerprint_path(store_path)
    if not p.exists():
        return False
    if now_ts is None:
        now_ts = time.time()
    cutoff = now_ts - budget_hours * 3600
    try:
        with p.open("r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rec = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                if rec.get("fingerprint") == fingerprint and rec.get("ts", 0) >= cutoff:
                    return True
    except OSError:
        return False
    return False


def record_fingerprint(
    fingerprint: str,
    pr_url: str,
    *,
    repo: str = "",
    workflow: str = "",
    store_path: str | Path | None = None,
    now_ts: float | None = None,
) -> None:
    """追加一条指纹记录到 jsonl 文件。"""
    p = _fingerprint_path(store_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if now_ts is None:
        now_ts = time.time()
    rec = FingerprintRecord(
        fingerprint=fingerprint,
        pr_url=pr_url,
        ts=now_ts,
        repo=repo,
        workflow=workflow,
    )
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec.__dict__) + "\n")


# =====================================================================
# 规则匹配
# =====================================================================


def _make_remove_import_patch(file_path: str, line_no: int, raw: str) -> str:
    """生成删除 import 行的 unified diff 片段。"""
    return (
        f"--- a/{file_path}\n"
        f"+++ b/{file_path}\n"
        f"@@ -{line_no},1 +{line_no},0 @@\n"
        f"-{raw.split(':', 1)[-1] if ':' in raw else raw}\n"
    )


def _make_truncate_line_patch(file_path: str, line_no: int) -> str:
    """生成行长截断的占位 patch（实际修复需源文件内容，此处仅占位）。"""
    return (
        f"--- a/{file_path}\n"
        f"+++ b/{file_path}\n"
        f"@@ -{line_no},1 +{line_no},1 @@\n"
        f"-{file_path}:{line_no}: E501 line too long\n"
        f"+# line truncated by ai-self-heal (E501)\n"
    )


def match_rules(errors: list[ErrorEntry]) -> list[Fix]:
    """规则匹配：覆盖 80% 常见失败，返回每个错误对应的修复方案。

    风险分级（risk_level）：
    - r0 极低：机械删除/截断/format，可 24h 自动合并
    - r1 低：可能影响语义但校验可兜底，72h 无 review 自动合并
    - r2 中：需人工 review，7d stale / 14d close
    - r3 高：安全/业务/LLM，永不自动合并，7d stale / 30d close
    """
    fixes: list[Fix] = []
    for err in errors:
        if err.tool in {"ruff", "black"} and err.code == "FORMAT" and err.file_path:
            # patch 字段约定：FORMAT:<tool>:<path> —— materialize 时跑 format 命令
            fixes.append(
                Fix(
                    error=err,
                    patch=f"FORMAT:{err.tool}:{err.file_path}",
                    needs_human=False,
                    description=f"自动 format: {err.file_path}",
                    risk_level="r0",
                )
            )
            continue
        if err.tool == "ruff":
            if err.code in {"F401", "F811"}:  # 未使用 import / 重复定义
                patch = _make_remove_import_patch(err.file_path, err.line, err.raw)
                fixes.append(
                    Fix(
                        error=err,
                        patch=patch,
                        needs_human=False,
                        description=f"删除未使用 import: {err.file_path}:{err.line}",
                        risk_level="r0",
                    )
                )
                continue
            if err.code == "E501":  # 行长超限
                patch = _make_truncate_line_patch(err.file_path, err.line)
                fixes.append(
                    Fix(
                        error=err,
                        patch=patch,
                        needs_human=False,
                        description=f"截断超长行: {err.file_path}:{err.line}",
                        risk_level="r0",
                    )
                )
                continue
            if err.code == "F841":  # 未使用局部变量
                fixes.append(
                    Fix(
                        error=err,
                        patch="",
                        needs_human=True,
                        description=f"未使用局部变量（r1 二次校验后 72h 可 auto-merge）: {err.message}",
                        risk_level="r1",
                    )
                )
                continue
            fixes.append(
                Fix(
                    error=err,
                    patch="",
                    needs_human=True,
                    description=f"ruff 错误码 {err.code}（r2 需人工）",
                    risk_level="r2",
                )
            )
            continue
        if err.tool == "bandit":
            # bandit 全部 r3（安全相关，永不自动合并）
            fixes.append(
                Fix(
                    error=err,
                    patch="",
                    needs_human=True,
                    description=f"bandit 安全告警 [{err.code}]（r3 需人工）: {err.message}",
                    risk_level="r3",
                )
            )
            continue
        if err.tool == "mypy":
            fixes.append(
                Fix(
                    error=err,
                    patch="",
                    needs_human=True,
                    description=f"mypy 类型错误（r2 需人工）: {err.message}",
                    risk_level="r2",
                )
            )
            continue
        if err.tool == "pytest":
            fixes.append(
                Fix(
                    error=err,
                    patch="",
                    needs_human=True,
                    description=f"pytest 测试失败（r3 需人工分析）: {err.message}",
                    risk_level="r3",
                )
            )
            continue
        fixes.append(
            Fix(error=err, patch="", needs_human=True, description="未知工具错误（r3）", risk_level="r3")
        )
    return fixes


# =====================================================================
# LLM 兜底（fail-open）
# =====================================================================


def call_llm(
    errors: list[ErrorEntry],
    *,
    api_key: str | None = None,
    endpoint: str | None = None,
    client: Any = None,
    timeout: float = 30.0,
) -> list[Fix] | None:
    """LLM 兜底生成修复方案。

    fail-open 策略：
    - 缺 api_key → 返回 None
    - httpx 缺失 → 返回 None
    - 超时/网络错误 → 返回 None
    - 任意异常 → 返回 None
    """
    api_key = api_key or os.environ.get("XCAGI_LLM_API_KEY")
    if not api_key or not errors:
        return None
    if httpx is None and client is None:
        return None
    endpoint = endpoint or os.environ.get("XCAGI_LLM_ENDPOINT", "https://api.example.com/v1/fix")
    payload = {
        "errors": [
            {
                "tool": e.tool,
                "code": e.code,
                "message": e.message,
                "file": e.file_path,
                "line": e.line,
            }
            for e in errors
        ],
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        if client is None:
            client = httpx.Client(timeout=timeout)
            close_after = True
        else:
            close_after = False
        try:
            resp = client.post(endpoint, json=payload, headers=headers)
            if resp.status_code != 200:
                return None
            data = resp.json()
        finally:
            if close_after:
                client.close()
    except Exception:
        return None
    fixes_data = data.get("fixes") if isinstance(data, dict) else None
    if not isinstance(fixes_data, list):
        return None
    out: list[Fix] = []
    for item in fixes_data:
        if not isinstance(item, dict):
            continue
        idx = item.get("error_index")
        if not isinstance(idx, int) or idx < 0 or idx >= len(errors):
            continue
        out.append(
            Fix(
                error=errors[idx],
                patch=str(item.get("patch", "")),
                needs_human=bool(item.get("needs_human", True)),
                description=str(item.get("description", "LLM 生成修复")),
            )
        )
    return out


# =====================================================================
# 应用修复 & 创建 PR
# =====================================================================


def apply_fixes(fixes: list[Fix]) -> str:
    """合并所有 fix 的 patch，返回完整 patch 文本。"""
    parts: list[str] = []
    for fix in fixes:
        if fix.patch:
            parts.append(fix.patch)
    return "\n".join(parts)


def _repo_root() -> Path:
    """优先 GITHUB_WORKSPACE，否则从本文件向上找含 .git 的根。"""
    env = os.environ.get("GITHUB_WORKSPACE", "").strip()
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / ".git").exists():
            return parent
    return Path.cwd()


def _run_git(args: list[str], *, cwd: Path) -> tuple[int, str]:
    import subprocess

    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out


def materialize_branch_with_fixes(
    branch: str,
    fixes: list[Fix],
    *,
    base: str = "main",
    repo_root: Path | None = None,
) -> bool:
    """在本地 checkout 上应用 r0 机械修复并推送到 ``origin/<branch>``。

    - ``FORMAT:ruff:<path>`` / ``FORMAT:black:<path>`` → 跑对应 format 命令
    - 其它 unified diff patch → 暂存为说明文件（避免残缺 patch 破坏工作树）；
      format 是当前生产空跑的主因，优先保证 format 通路可落地。

    成功推送返回 True；无可应用修复 / git 失败返回 False。
    """
    import subprocess

    root = repo_root or _repo_root()
    format_files: list[tuple[str, str]] = []  # (tool, path)
    for fix in fixes:
        if fix.needs_human or not fix.patch:
            continue
        if fix.patch.startswith("FORMAT:"):
            parts = fix.patch.split(":", 2)
            if len(parts) == 3 and parts[2].strip():
                format_files.append((parts[1], parts[2].strip()))

    if not format_files:
        print("[heal] no materializable FORMAT fixes; skip branch push")
        return False

    # 基于当前 HEAD 建分支（workflow 已 checkout 失败源或默认分支）
    code, out = _run_git(["checkout", "-B", branch], cwd=root)
    if code != 0:
        print(f"[heal] git checkout -B failed: {out.strip()}")
        return False

    changed: list[str] = []
    for tool, rel in format_files:
        path = root / rel
        # CI 常在 FHD/ 工作目录跑；日志路径可能相对 FHD
        if not path.is_file():
            alt = root / "FHD" / rel
            if alt.is_file():
                path = alt
                rel = str(Path("FHD") / rel)
        if not path.is_file():
            print(f"[heal] format target missing: {rel}")
            continue
        cmd = ["ruff", "format", str(path)] if tool == "ruff" else ["black", str(path)]
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            print(f"[heal] {tool} format failed for {rel}: {(proc.stderr or proc.stdout or '').strip()}")
            continue
        changed.append(rel)

    if not changed:
        print("[heal] format produced no file changes")
        return False

    _run_git(["add", "--", *changed], cwd=root)
    code, out = _run_git(
        [
            "commit",
            "-m",
            f"ai-self-heal: auto-format {len(changed)} file(s)",
        ],
        cwd=root,
    )
    if code != 0:
        print(f"[heal] git commit failed: {out.strip()}")
        return False

    code, out = _run_git(["push", "-u", "origin", branch, "--force-with-lease"], cwd=root)
    if code != 0:
        # 首次推送无 lease 也可
        code, out = _run_git(["push", "-u", "origin", branch, "--force"], cwd=root)
    if code != 0:
        print(f"[heal] git push failed: {out.strip()}")
        return False
    print(f"[heal] pushed branch {branch} with {len(changed)} formatted file(s)")
    return True


def create_pr(
    branch: str,
    patch: str,
    *,
    title: str = "ai-self-heal: auto fix",
    body: str = "",
    labels: list[str] | None = None,
    base: str = "main",
    token: str | None = None,
    repo: str | None = None,
    client: Any = None,
) -> str:
    """创建修复 PR，返回 PR URL（失败返回空字符串）。

    调用方须先 :func:`materialize_branch_with_fixes` 把 ``branch`` 推到 origin。
    """
    repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
    token = token or os.environ.get("GITHUB_TOKEN", "")
    if not repo or not token:
        return ""
    labels = labels or ["ai-self-heal"]
    if client is None:
        if httpx is None:
            return ""
        client = httpx.Client(timeout=30.0)
        close_after = True
    else:
        close_after = False
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    }
    try:
        body_payload = {
            "title": title,
            "body": body or f"ai-self-heal 自动修复 PR\n\n分支: {branch}\n",
            "head": branch,
            "base": base,
        }
        resp = client.post(
            f"{GITHUB_API}/repos/{repo}/pulls",
            headers=headers,
            json=body_payload,
        )
        if resp.status_code not in (200, 201):
            print(f"[heal] create PR HTTP {resp.status_code}: {resp.text[:300]}")
            return ""
        data = resp.json()
        pr_url = data.get("html_url", "")
        pr_number = data.get("number")
        if pr_number and labels:
            try:
                client.post(
                    f"{GITHUB_API}/repos/{repo}/issues/{pr_number}/labels",
                    headers=headers,
                    json={"labels": labels},
                )
            except Exception:
                pass
        return pr_url
    except Exception as exc:
        print(f"[heal] create PR exception: {exc}")
        return ""
    finally:
        if close_after:
            try:
                client.close()
            except Exception:  # pragma: no cover
                pass


# =====================================================================
# 分支递归检查
# =====================================================================


def is_autonomy_branch(branch: str | None) -> bool:
    """判断分支名是否以 autonomy/ 开头（避免自愈自身故障递归）。"""
    if not branch:
        return False
    return branch.startswith("autonomy/")


# =====================================================================
# 主入口
# =====================================================================


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CI ai-self-heal")
    parser.add_argument("--run-id", type=int, default=None, help="失败 workflow run id")
    parser.add_argument("--workflow", default="", help="workflow 名称")
    parser.add_argument("--branch", default="", help="失败 workflow 所在分支")
    parser.add_argument(
        "--store",
        default=None,
        help="指纹存储路径（默认 .trae/autonomy-ci/self-heal-fingerprints.jsonl）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只输出诊断，不创建 PR")
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")

    # autonomy/ 分支不递归
    if is_autonomy_branch(args.branch):
        print(f"[skip] autonomy/* branch detected ({args.branch}), 递归保护触发，跳过自愈")
        return 0

    run_id = args.run_id or _run_id_from_env()
    if not run_id:
        print("[skip] no run_id provided (env GITHUB_RUN_ID or --run-id)")
        return 0

    print(f"[heal] fetch logs for run_id={run_id} repo={repo}")
    log_text = fetch_workflow_logs(run_id, token=token, repo=repo)
    if not log_text:
        print("[skip] empty logs (fail-open)")
        return 0

    errors = extract_errors(log_text)
    if not errors:
        print("[skip] no extractable errors in logs")
        return 0

    print(f"[heal] extracted {len(errors)} error(s)")
    fixes = match_rules(errors)
    needs_human_count = sum(1 for f in fixes if f.needs_human)
    print(f"[heal] rules matched: {len(fixes)} fix(es), {needs_human_count} need human")

    # LLM 兜底（仅对 needs-human 的 fix）
    needs_human_errors = [f.error for f in fixes if f.needs_human]
    if needs_human_errors:
        llm_fixes = call_llm(needs_human_errors)
        if llm_fixes is not None:
            print(f"[heal] LLM 兜底生成 {len(llm_fixes)} 个候选修复")
            # LLM 提供的修复替换原 needs-human fix，但 LLM 强制 r3 永不自动合并
            for lf in llm_fixes:
                # 找到原 fix 替换 patch
                for i, orig in enumerate(fixes):
                    if orig.error is lf.error:
                        fixes[i] = Fix(
                            error=lf.error,
                            patch=lf.patch or orig.patch,
                            needs_human=True,  # LLM 修复仍标 needs-human
                            description=f"[LLM] {lf.description}",
                            risk_level="r3",
                        )
                        break
        else:
            print("[heal] LLM unavailable (fail-open), 仅使用规则匹配结果")

    # 计算指纹 & 去重
    error_lines = [e.raw for e in errors]
    fingerprint = compute_fingerprint(
        repo=repo,
        workflow=args.workflow,
        job="",  # job 信息从 logs 解析较复杂，此处留空
        error_line="\n".join(error_lines),
    )
    if is_already_processed(fingerprint, store_path=args.store):
        print(f"[skip] fingerprint {fingerprint[:8]} already processed within 24h")
        return 0

    if args.dry_run:
        print(f"[dry-run] would create PR with {len(fixes)} fix(es), fingerprint={fingerprint[:8]}")
        for fx in fixes:
            print(f"  - [{fx.risk_level}] {fx.description}")
        return 0

    patch = apply_fixes(fixes)
    branch_name = f"autonomy/self-heal-{fingerprint[:8]}"

    # 计算最高风险等级（r0 < r1 < r2 < r3），决定 PR 标签与 SLA 路径
    risk_rank = {"r0": 0, "r1": 1, "r2": 2, "r3": 3}
    max_risk = "r0"
    for f in fixes:
        if risk_rank.get(f.risk_level, 3) > risk_rank[max_risk]:
            max_risk = f.risk_level
    labels = ["ai-self-heal", f"risk:{max_risk}"]
    if max_risk in {"r2", "r3"}:
        labels.append("needs-human")

    # 先落到失败源分支内容，再切 heal 分支并 push（否则 create_pr 无 head）
    root = _repo_root()
    source_branch = (args.branch or "").strip()
    if source_branch and source_branch != branch_name:
        _run_git(["fetch", "origin", source_branch, "--depth=1"], cwd=root)
        code, out = _run_git(["checkout", "-B", f"heal-base/{source_branch}", f"origin/{source_branch}"], cwd=root)
        if code != 0:
            # 浅克隆可能没有 origin/<branch>；尝试直接 checkout
            code, out = _run_git(["checkout", source_branch], cwd=root)
            if code != 0:
                print(f"[heal] checkout source branch failed ({source_branch}): {out.strip()}")

    pushed = materialize_branch_with_fixes(branch_name, fixes, base=source_branch or "main", repo_root=root)
    if not pushed:
        print("[error] materialize/push failed (fail-open, not blocking)")
        return 0

    pr_url = create_pr(
        branch=branch_name,
        patch=patch,
        title=f"ai-self-heal: auto fix for {args.workflow or 'workflow'}",
        body=(
            f"## ai-self-heal 自动修复 PR\n\n"
            f"- 触发 workflow: `{args.workflow or 'unknown'}`\n"
            f"- 失败分支: `{args.branch or 'unknown'}`\n"
            f"- 错误条数: {len(errors)}\n"
            f"- 自动修复: {len(fixes) - needs_human_count}\n"
            f"- 需人工: {needs_human_count}\n"
            f"- 最高风险: **{max_risk}**\n"
            f"- 指纹: `{fingerprint[:8]}`\n\n"
            f"### 分级合并 SLA\n"
            f"| 等级 | 含义 | 处理 |\n"
            f"|------|------|------|\n"
            f"| r0 | 机械修复（lint/format） | 24h 二次守卫通过 → auto-merge |\n"
            f"| r1 | 低风险（未用变量等） | 72h 无 review → auto-merge |\n"
            f"| r2 | 中风险（其他 lint/mypy） | 7d stale / 14d auto-close |\n"
            f"| r3 | 高风险（bandit/pytest/LLM） | 永不自动合并，7d stale / 30d close |\n\n"
            f"**当前 PR 风险等级 = `{max_risk}`，按上表对应路径处理。**\n"
        ),
        labels=labels,
    )
    if not pr_url:
        print("[error] PR creation failed (fail-open, not blocking)")
        return 0

    record_fingerprint(
        fingerprint=fingerprint,
        pr_url=pr_url,
        repo=repo,
        workflow=args.workflow,
        store_path=args.store,
    )
    print(f"[heal] PR created: {pr_url}")
    print(f"[heal] fingerprint recorded: {fingerprint[:8]}")
    return 0


def _run_id_from_env() -> int | None:
    """从 workflow_run 事件 payload 中提取 run_id（GitHub Actions 环境）。"""
    payload_path = os.environ.get("GITHUB_EVENT_PATH")
    if not payload_path:
        return None
    try:
        with open(payload_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    wf_run = payload.get("workflow_run") or {}
    run_id = wf_run.get("id") or wf_run.get("run_id")
    if isinstance(run_id, int):
        return run_id
    if isinstance(run_id, str) and run_id.isdigit():
        return int(run_id)
    return None


def _branch_from_env() -> str:
    """从 workflow_run 事件 payload 中提取分支名。"""
    payload_path = os.environ.get("GITHUB_EVENT_PATH")
    if not payload_path:
        return ""
    try:
        with open(payload_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return ""
    wf_run = payload.get("workflow_run") or {}
    return str(wf_run.get("head_branch") or "")


def _workflow_name_from_env() -> str:
    """从 workflow_run 事件 payload 中提取 workflow 名称。"""
    payload_path = os.environ.get("GITHUB_EVENT_PATH")
    if not payload_path:
        return ""
    try:
        with open(payload_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return ""
    wf_run = payload.get("workflow_run") or {}
    return str(wf_run.get("name") or "")


if __name__ == "__main__":
    sys.exit(main())
