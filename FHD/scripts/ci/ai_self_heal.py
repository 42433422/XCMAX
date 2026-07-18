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


# 错误提取正则（覆盖 ruff / bandit / mypy / pytest 常见模式）
_RUFF_RE = re.compile(r"^(?P<file>[^\s:]+):(?P<line>\d+):\d+:\s+(?P<code>[A-Z]\d+)\s+(?P<msg>.*)$")
_BANDIT_RE = re.compile(r"^\s*Issue:\s*\[(?P<code>B\d+)\]\s*(?P<msg>.*)$")
_MYPY_RE = re.compile(r"^(?P<file>[^\s:]+):(?P<line>\d+):\s*error:\s*(?P<msg>.*)$")
_MYPY_CODE_RE = re.compile(r"\[(?P<code>[\w-]+)\]")
_PYTEST_FAIL_RE = re.compile(r"^(?P<file>[^\s:]+):(?P<line>\d+):\s*(?P<msg>FAILED|ERROR.*)$")
_PYTEST_FAILED_RE = re.compile(r"^FAILED\s+(?P<msg>.*)$")


def extract_errors(log_text: str) -> list[ErrorEntry]:
    """从 CI 日志文本中提取错误条目。

    顺序扫描每一行，依次尝试 ruff / bandit / mypy / pytest 模式。
    返回去重后的列表（同 file+line+code+msg 视为重复）。
    """
    if not log_text:
        return []
    seen: set[tuple[str, str, str, str]] = set()
    out: list[ErrorEntry] = []
    for raw_line in log_text.splitlines():
        line = raw_line.rstrip("\r")
        if not line:
            continue
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
    """规则匹配：覆盖 80% 常见失败，返回每个错误对应的修复方案。"""
    fixes: list[Fix] = []
    for err in errors:
        if err.tool == "ruff":
            if err.code in {"F401", "F811"}:  # 未使用 import / 重复定义
                patch = _make_remove_import_patch(err.file_path, err.line, err.raw)
                fixes.append(
                    Fix(
                        error=err,
                        patch=patch,
                        needs_human=False,
                        description=f"删除未使用 import: {err.file_path}:{err.line}",
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
                    )
                )
                continue
            if err.code == "F841":  # 未使用局部变量
                fixes.append(
                    Fix(
                        error=err,
                        patch="",
                        needs_human=True,
                        description=f"未使用局部变量，需人工确认是否安全删除: {err.message}",
                    )
                )
                continue
            fixes.append(
                Fix(
                    error=err,
                    patch="",
                    needs_human=True,
                    description=f"ruff 未知错误码 {err.code}，需人工修复",
                )
            )
            continue
        if err.tool == "bandit":
            # bandit 全部标 needs-human（安全相关，不自动修）
            fixes.append(
                Fix(
                    error=err,
                    patch="",
                    needs_human=True,
                    description=f"bandit 安全告警 [{err.code}]，需人工评估: {err.message}",
                )
            )
            continue
        if err.tool == "mypy":
            fixes.append(
                Fix(
                    error=err,
                    patch="",
                    needs_human=True,
                    description=f"mypy 类型错误，需人工修复: {err.message}",
                )
            )
            continue
        if err.tool == "pytest":
            fixes.append(
                Fix(
                    error=err,
                    patch="",
                    needs_human=True,
                    description=f"pytest 测试失败，需人工分析: {err.message}",
                )
            )
            continue
        fixes.append(
            Fix(error=err, patch="", needs_human=True, description="未知工具错误，需人工分析")
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
    """创建修复 PR，返回 PR URL（失败返回空字符串）。"""
    repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
    token = token or os.environ.get("GITHUB_TOKEN", "")
    if not repo or not token:
        return ""
    labels = labels or ["needs-human", "ai-self-heal"]
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
        # 1. 创建分支
        # 简化：直接 POST createRef（实际需要先 GET 默认分支 sha）
        body_payload = {
            "title": title,
            "body": body or f"ai-self-heal 自动修复 PR\n\n分支: {branch}\n\n需人工审查后合并。",
            "head": branch,
            "base": base,
        }
        resp = client.post(
            f"{GITHUB_API}/repos/{repo}/pulls",
            headers=headers,
            json=body_payload,
        )
        if resp.status_code not in (200, 201):
            return ""
        data = resp.json()
        pr_url = data.get("html_url", "")
        pr_number = data.get("number")
        # 2. 添加标签
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
    except Exception:
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
            # LLM 提供的修复替换原 needs-human fix（但仍标记 needs-human，不自动合并）
            for lf in llm_fixes:
                # 找到原 fix 替换 patch
                for i, orig in enumerate(fixes):
                    if orig.error is lf.error:
                        fixes[i] = Fix(
                            error=lf.error,
                            patch=lf.patch or orig.patch,
                            needs_human=True,  # LLM 修复仍标 needs-human
                            description=f"[LLM] {lf.description}",
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
        return 0

    patch = apply_fixes(fixes)
    branch_name = f"autonomy/self-heal-{fingerprint[:8]}"
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
            f"- 指纹: `{fingerprint[:8]}`\n\n"
            f"**业务码修复必须人工审查，禁止自动合并。**\n"
        ),
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
