"""CI 自愈脚本：失败 workflow → 提取错误 → 规则匹配 + LLM 兜底 → 创建修复 PR。

七元契约沿用桌面端：Signal(workflow_run failure) → Diagnosis(error extract) →
Action(fix patch) → Policy(规则匹配优先) → Adapter(GitHub API) →
RuntimeTruthSnapshot(logs) → AuditEntry(self-heal-fingerprints.jsonl)。

设计要点：
- 触发：GitHub Actions workflow_run.completed + conclusion=failure
- 同指纹 24h 去重：SHA256(repo + workflow + job + error_line_hash)
- 规则匹配优先：覆盖 ruff/bandit/mypy/pytest 常见错误模式
- 无法自动提取或实现时创建预授权 incident，交给 AI Issue Implement
- autonomy/ 分支不递归：避免自愈自身故障
- 原失败在真实修复 PR 合入前保持失败状态，禁止“跳过即成功”
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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover - 测试环境可能未装 httpx
    httpx = None  # type: ignore[assignment]

try:
    from _approval_ledger_client import post_to_approval_ledger
except ImportError:  # pragma: no cover - 测试环境路径可能不通
    post_to_approval_ledger = None  # type: ignore[assignment]


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


@dataclass(frozen=True)
class IncidentBudgetDecision:
    """Durable GitHub-side circuit-breaker decision for incident creation."""

    allowed: bool
    reason: str
    open_total: int = 0
    open_for_workflow: int = 0
    recent_total: int = 0


# =====================================================================
# 日志下载与解析
# =====================================================================

GITHUB_API = "https://api.github.com"
DEFAULT_MAX_OPEN_INCIDENTS = 20
DEFAULT_MAX_OPEN_INCIDENTS_PER_WORKFLOW = 5
DEFAULT_MAX_RECENT_INCIDENTS = 20
DEFAULT_INCIDENT_BUDGET_HOURS = 24


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
_ACTION_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\s+")
_ACTION_ERROR_RE = re.compile(r"##\[error\](?P<msg>.+)", re.IGNORECASE)
_ACTION_EXIT_RE = re.compile(r"Process completed with exit code\s+(?P<code>\d+)", re.IGNORECASE)
_ACTION_STATUS_RE = re.compile(r"(?:failed with status|status)\s+(?P<code>\d+)", re.IGNORECASE)


def _normalize_action_log_line(raw_line: str) -> str:
    """Remove GitHub's job/step/timestamp envelope without losing evidence."""

    line = str(raw_line or "").rstrip("\r").lstrip("\ufeff")
    if line.count("\t") >= 2:
        line = line.split("\t", 2)[-1]
    return _ACTION_TIMESTAMP_RE.sub("", line.lstrip("\ufeff"), count=1)


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
        line = _normalize_action_log_line(raw_line)
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
                            action_error = _ACTION_ERROR_RE.search(line)
                            action_exit = _ACTION_EXIT_RE.search(line)
                            action_status = _ACTION_STATUS_RE.search(line)
                            if not (action_error or action_exit or action_status):
                                continue
                            code_match = action_exit or action_status
                            code = code_match.group("code") if code_match else "ERROR"
                            message = (
                                action_error.group("msg").strip() if action_error else line.strip()
                            )
                            entry = ErrorEntry(
                                tool="github-actions",
                                code=f"EXIT_{code}" if code.isdigit() else code,
                                message=message,
                                file_path="",
                                line=0,
                                raw=line,
                            )
        key = (entry.tool, entry.code, entry.file_path, entry.message)
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out


def select_actionable_errors(errors: list[ErrorEntry]) -> list[ErrorEntry]:
    """Prefer terminal failed-step evidence over advisory output from other jobs.

    A workflow log archive contains every job, including successful jobs that
    emit mypy/ruff diagnostics as advisory output.  When GitHub provides an
    explicit ``##[error]`` or non-zero exit/status marker, that marker is the
    authoritative incident signal.  Keeping unrelated advisory paths caused a
    single CVM timeout to be estimated as a 20+ file repair.
    """

    action_errors = [entry for entry in errors if entry.tool == "github-actions"]
    if not action_errors:
        return errors
    specific = [
        entry
        for entry in action_errors
        if not _ACTION_EXIT_RE.search(entry.message)
        and not entry.message.lower().startswith("process completed")
    ]
    return specific or action_errors


def select_incident_log_excerpt(log_text: str, *, max_chars: int = 12000) -> str:
    """Prefer failing-step evidence over an arbitrary tail from another job."""

    lines = list((log_text or "").splitlines())
    interesting = [
        index
        for index, raw in enumerate(lines)
        if _ACTION_ERROR_RE.search(_normalize_action_log_line(raw))
        or _ACTION_EXIT_RE.search(_normalize_action_log_line(raw))
        or _ACTION_STATUS_RE.search(_normalize_action_log_line(raw))
    ]
    if not interesting:
        return "\n".join(lines)[-max_chars:]
    selected: list[str] = []
    seen: set[int] = set()
    for index in interesting:
        for current in range(max(0, index - 8), min(len(lines), index + 4)):
            if current in seen:
                continue
            seen.add(current)
            selected.append(lines[current])
    return "\n".join(selected)[-max_chars:]


# =====================================================================
# 指纹去重
# =====================================================================


def compute_fingerprint(repo: str, workflow: str, job: str, error_line: str) -> str:
    """计算错误指纹 = SHA256(repo + workflow + job + error_line_hash)。"""
    error_hash = hashlib.sha256(error_line.encode("utf-8")).hexdigest()[:16]
    raw = f"{repo}|{workflow}|{job}|{error_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def canonical_fingerprint_evidence(errors: list[ErrorEntry], log_text: str) -> str:
    """Build stable root-cause evidence when Actions only exposes a generic exit line."""

    def normalize(raw: str) -> str:
        line = re.sub(r"\x1b\[[0-9;]*m", "", raw)
        line = re.sub(
            r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\b",
            "<timestamp>",
            line,
        )
        line = re.sub(r"\brun(?:_id| id)?[=: ]+\d+\b", "run_id=<id>", line, flags=re.I)
        line = re.sub(r"\b[0-9a-f]{40,64}\b", "<digest>", line, flags=re.I)
        line = re.sub(
            r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
            "<uuid>",
            line,
            flags=re.I,
        )
        return " ".join(line.split())

    meaningful_errors = [
        normalize(error.raw)
        for error in errors
        if "process completed with exit code" not in error.raw.casefold()
    ]
    if meaningful_errors:
        return "\n".join(meaningful_errors)

    excerpt = select_incident_log_excerpt(log_text)
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in excerpt.splitlines():
        line = normalize(raw)
        folded = line.casefold()
        if not line or any(
            noise in folded
            for noise in (
                "process completed with exit code",
                "node 20 is being deprecated",
                "post job cleanup",
                "[command]/usr/bin/git version",
            )
        ):
            continue
        if line in seen:
            continue
        seen.add(line)
        normalized.append(line)
    if normalized:
        return "\n".join(normalized)
    return "\n".join(error.raw for error in errors) or "unclassified-workflow-failure"


def _positive_env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def check_incident_budget(
    workflow: str,
    *,
    token: str | None = None,
    repo: str | None = None,
    client: Any = None,
    now_ts: float | None = None,
    max_open: int | None = None,
    max_open_per_workflow: int | None = None,
    max_recent: int | None = None,
    budget_hours: int | None = None,
) -> IncidentBudgetDecision:
    """Fail closed when the durable incident queue exceeds a bounded budget.

    Hosted-runner JSONL state disappears after every run, so the circuit breaker
    must use GitHub issues as its coordination plane.  A lookup failure also
    blocks creation: the original failed workflow remains authoritative evidence,
    while blindly creating another issue would amplify an outage.
    """

    repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
    token = token or os.environ.get("GITHUB_TOKEN", "")
    max_open = max_open or _positive_env_int(
        "AI_SELF_HEAL_MAX_OPEN_INCIDENTS", DEFAULT_MAX_OPEN_INCIDENTS
    )
    max_open_per_workflow = max_open_per_workflow or _positive_env_int(
        "AI_SELF_HEAL_MAX_OPEN_PER_WORKFLOW",
        DEFAULT_MAX_OPEN_INCIDENTS_PER_WORKFLOW,
    )
    max_recent = max_recent or _positive_env_int(
        "AI_SELF_HEAL_MAX_RECENT_INCIDENTS", DEFAULT_MAX_RECENT_INCIDENTS
    )
    budget_hours = budget_hours or _positive_env_int(
        "AI_SELF_HEAL_INCIDENT_BUDGET_HOURS", DEFAULT_INCIDENT_BUDGET_HOURS
    )
    if not repo or not token:
        return IncidentBudgetDecision(False, "budget_lookup_missing_repo_or_token")
    if now_ts is None:
        now_ts = time.time()
    if client is None:
        if httpx is None:
            return IncidentBudgetDecision(False, "budget_lookup_httpx_unavailable")
        client = httpx.Client(timeout=30.0)
        close_after = True
    else:
        close_after = False
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    workflow_marker = f"- Workflow: `{workflow or 'unknown'}`"
    cutoff = now_ts - budget_hours * 3600
    open_total = 0
    open_for_workflow = 0
    recent_total = 0
    try:
        for page in range(1, 11):
            response = client.get(
                f"{GITHUB_API}/repos/{repo}/issues",
                headers=headers,
                params={
                    "state": "open",
                    "labels": "auto-incident",
                    "sort": "created",
                    "direction": "desc",
                    "per_page": 100,
                    "page": page,
                },
            )
            if response.status_code != 200:
                return IncidentBudgetDecision(
                    False,
                    f"budget_lookup_http_{response.status_code}",
                    open_total,
                    open_for_workflow,
                    recent_total,
                )
            payload = response.json()
            if not isinstance(payload, list):
                return IncidentBudgetDecision(
                    False,
                    "budget_lookup_invalid_payload",
                    open_total,
                    open_for_workflow,
                    recent_total,
                )
            for item in payload:
                if not isinstance(item, dict) or item.get("pull_request"):
                    continue
                open_total += 1
                body = str(item.get("body") or "")
                if workflow_marker in body:
                    open_for_workflow += 1
                created_at = str(item.get("created_at") or "")
                try:
                    created_ts = datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    created_ts = 0.0
                if created_ts >= cutoff:
                    recent_total += 1
            if open_total >= max_open:
                return IncidentBudgetDecision(
                    False,
                    f"global_open_incidents:{open_total}>={max_open}",
                    open_total,
                    open_for_workflow,
                    recent_total,
                )
            if open_for_workflow >= max_open_per_workflow:
                return IncidentBudgetDecision(
                    False,
                    f"workflow_open_incidents:{open_for_workflow}>={max_open_per_workflow}",
                    open_total,
                    open_for_workflow,
                    recent_total,
                )
            if recent_total >= max_recent:
                return IncidentBudgetDecision(
                    False,
                    f"recent_incidents:{recent_total}>={max_recent}/{budget_hours}h",
                    open_total,
                    open_for_workflow,
                    recent_total,
                )
            if len(payload) < 100:
                break
    except Exception as exc:  # noqa: BLE001 - circuit breaker must fail closed
        return IncidentBudgetDecision(
            False,
            f"budget_lookup_error:{type(exc).__name__}",
            open_total,
            open_for_workflow,
            recent_total,
        )
    finally:
        if close_after:
            try:
                client.close()
            except Exception:  # pragma: no cover
                pass
    return IncidentBudgetDecision(
        True,
        "within_budget",
        open_total,
        open_for_workflow,
        recent_total,
    )


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


def find_existing_remediation_issue(
    fingerprint: str,
    *,
    budget_hours: int = 24,
    token: str | None = None,
    repo: str | None = None,
    client: Any = None,
    now_ts: float | None = None,
) -> str:
    """Return a recent GitHub incident carrying the same fingerprint.

    The runner-local JSONL store disappears after every hosted Actions run, so
    it cannot provide cross-run deduplication.  GitHub issues are the durable
    coordination plane already used by the remediation loop; query that plane
    before creating another incident.  API failures deliberately fail open so
    an outage in the dedup lookup never suppresses a real incident.
    """

    repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
    token = token or os.environ.get("GITHUB_TOKEN", "")
    if not fingerprint or not repo or not token:
        return ""
    if now_ts is None:
        now_ts = time.time()
    since = datetime.fromtimestamp(now_ts - budget_hours * 3600, tz=UTC).isoformat()
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
    }
    marker = f"Correlation/Fingerprint: `{fingerprint}`"
    try:
        for page in range(1, 11):
            response = client.get(
                f"{GITHUB_API}/repos/{repo}/issues",
                headers=headers,
                params={
                    "state": "all",
                    "labels": "auto-incident",
                    "sort": "created",
                    "direction": "desc",
                    "since": since,
                    "per_page": 100,
                    "page": page,
                },
            )
            if response.status_code != 200:
                return ""
            payload = response.json()
            if not isinstance(payload, list):
                return ""
            for item in payload:
                if not isinstance(item, dict) or marker not in str(item.get("body") or ""):
                    continue
                return str(item.get("html_url") or "")
            if len(payload) < 100:
                break
    except Exception:
        return ""
    finally:
        if close_after:
            try:
                client.close()
            except Exception:  # pragma: no cover
                pass
    return ""


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
    - r0 极低：机械删除/截断，可 24h 自动合并
    - r1 低：可能影响语义但校验可兜底，72h 无 review 自动合并
    - r2 中：需人工 review，7d stale / 14d close
    - r3 高：安全/业务/LLM，永不自动合并，7d stale / 30d close
    """
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
            Fix(
                error=err,
                patch="",
                needs_human=True,
                description="未知工具错误（r3）",
                risk_level="r3",
            )
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
    fixes: list[Fix] | None = None,
) -> str:
    """创建修复 PR，返回 PR URL（失败返回空字符串）。

    PR 创建成功后会旁路调用 approval ledger（fire-and-forget，fail-open），
    把 needs-human 待办写入管理端审批中心。ledger 写入失败绝不阻断 PR 创建。
    """
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
        # 3. 旁路写 approval ledger（fire-and-forget，fail-open 在 client 内处理）
        if post_to_approval_ledger is not None:
            try:
                risk_level = "r3" if "needs-human" in (labels or []) else "r0"
                fixes_summary = (
                    [{"file": f.file, "line": f.line, "rule": f.rule} for f in (fixes or [])]
                    if fixes
                    else []
                )
                post_to_approval_ledger(
                    action="self_maintenance_merge",
                    payload={
                        "pr_number": pr_number,
                        "pr_url": pr_url,
                        "branch": branch,
                        "base": base,
                        "risk_level": risk_level,
                        "fixes_summary": fixes_summary,
                    },
                    source="ci_self_heal",
                )
            except Exception:  # pragma: no cover - fail-open
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


def create_remediation_issue(
    *,
    run_id: int,
    workflow: str,
    branch: str,
    fingerprint: str,
    log_excerpt: str,
    errors: list[ErrorEntry],
    head_repo: str = "",
    token: str | None = None,
    repo: str | None = None,
    client: Any = None,
) -> str:
    """Create a deduplicated, pre-authorized incident for the implementation loop."""

    repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
    token = token or os.environ.get("GITHUB_TOKEN", "")
    if not repo or not token:
        return ""
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
    error_lines = "\n".join(f"- `{entry.raw[:500]}`" for entry in errors[:30])
    if not error_lines:
        error_lines = "- 日志存在失败结论，但当前解析器未提取到结构化错误。"
    body = (
        "## CI 自愈事件\n\n"
        f"- Workflow: `{workflow or 'unknown'}`\n"
        f"- Run ID: `{run_id}`\n"
        f"- Branch: `{branch or 'unknown'}`\n"
        f"- Head Repository: `{head_repo or repo}`\n"
        f"- Correlation/Fingerprint: `{fingerprint}`\n\n"
        "### 提取结果\n\n"
        f"{error_lines}\n\n"
        "### 运行日志摘录\n\n"
        f"```text\n{log_excerpt[-12000:]}\n```\n\n"
        "请定位根因、实现最小安全修复、执行相关测试并创建 PR。"
    )
    payload = {
        "title": f"[auto-incident] Repair {workflow or 'failed workflow'} run {run_id}",
        "body": body,
        # Keep this list aligned with labels provisioned in the repository;
        # GitHub rejects issue creation when a requested label is unavailable.
        "labels": ["ai-implement", "incident", "auto-incident"],
    }
    try:
        response = client.post(
            f"{GITHUB_API}/repos/{repo}/issues",
            headers=headers,
            json=payload,
        )
        if response.status_code not in (200, 201):
            return ""
        data = response.json()
        return str(data.get("html_url") or "")
    except Exception:
        return ""
    finally:
        if close_after:
            try:
                client.close()
            except Exception:  # pragma: no cover
                pass


def dispatch_issue_implementation(
    issue_url: str,
    *,
    token: str | None = None,
    repo: str | None = None,
    ref: str = "main",
    target_branch: str = "main",
    client: Any = None,
) -> bool:
    """Explicitly dispatch the implementation loop for a token-created issue.

    Events emitted with ``GITHUB_TOKEN`` do not recursively start most other
    workflows. ``workflow_dispatch`` is the supported exception, so incident
    creation and implementation handoff must be two explicit API operations.
    """

    match = re.search(r"/issues/(?P<number>\d+)/?$", str(issue_url or ""))
    repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
    token = token or os.environ.get("GITHUB_TOKEN", "")
    if not match or not repo or not token or not str(ref or "").strip():
        return False
    if client is None:
        if httpx is None:
            return False
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
        response = client.post(
            f"{GITHUB_API}/repos/{repo}/actions/workflows/fhd-ai-issue-implement.yml/dispatches",
            headers=headers,
            json={
                "ref": str(ref).strip(),
                "inputs": {
                    "issue_number": match.group("number"),
                    "target_branch": str(target_branch or "main").strip(),
                },
            },
        )
        return response.status_code == 204
    except Exception:
        return False
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
    parser.add_argument("--head-repo", default="", help="失败 workflow 的 head 仓库")
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
        print("::error::[heal] no failed run_id provided")
        return 2

    print(f"[heal] fetch logs for run_id={run_id} repo={repo}")
    log_text = fetch_workflow_logs(run_id, token=token, repo=repo)
    if not log_text:
        log_text = "workflow log download returned no content"

    extracted_errors = extract_errors(log_text)
    errors = select_actionable_errors(extracted_errors)
    if not errors:
        print("::warning::[heal] no extractable errors; routing raw evidence to incident")

    print(
        f"[heal] extracted {len(extracted_errors)} error(s); "
        f"selected {len(errors)} actionable error(s)"
    )
    fixes = match_rules(errors)
    needs_human_count = sum(1 for f in fixes if f.needs_human)
    print(f"[heal] rules matched: {len(fixes)} fix(es), {needs_human_count} need human")

    # 先计算指纹、去重并检查持久化预算，再调用 LLM。否则同一故障风暴会在
    # 确认是否值得新建 incident 之前反复消耗模型、Actions 与 artifact 配额。
    fingerprint_evidence = canonical_fingerprint_evidence(errors, log_text)
    fingerprint = compute_fingerprint(
        repo=repo,
        workflow=args.workflow,
        job=args.branch,
        error_line=fingerprint_evidence,
    )
    if is_already_processed(fingerprint, store_path=args.store):
        print(f"[skip] fingerprint {fingerprint[:8]} already processed within 24h")
        return 0

    if args.dry_run:
        print(
            f"[dry-run] would create remediation incident with {len(fixes)} candidate fix(es), "
            f"fingerprint={fingerprint[:8]}"
        )
        return 0

    budget = check_incident_budget(
        args.workflow,
        token=token,
        repo=repo,
    )
    if not budget.allowed:
        print(
            "::error::[heal] incident circuit open; no issue or LLM dispatch created: "
            f"{budget.reason} "
            f"(open={budget.open_total}, workflow_open={budget.open_for_workflow}, "
            f"recent={budget.recent_total})"
        )
        return 2

    existing_issue = find_existing_remediation_issue(
        fingerprint,
        token=token,
        repo=repo,
    )
    if existing_issue:
        record_fingerprint(
            fingerprint=fingerprint,
            pr_url=existing_issue,
            repo=repo,
            workflow=args.workflow,
            store_path=args.store,
        )
        print(f"[skip] durable fingerprint {fingerprint[:8]} already tracked by {existing_issue}")
        return 0

    # LLM 兜底（仅对通过去重与预算门禁的 needs-human fix）
    needs_human_errors = [f.error for f in fixes if f.needs_human]
    if needs_human_errors:
        llm_fixes = call_llm(needs_human_errors)
        if llm_fixes is not None:
            print(f"[heal] LLM 兜底生成 {len(llm_fixes)} 个候选修复")
            # LLM 提供的修复替换原 needs-human fix。
            # 全量自主修复：LLM 修复从 r3 降为 r1（可自动合并），但保留
            # 三层护栏：hold-merge veto 通道 + 二次守卫（CI 全绿/体量/文件
            # 类型/禁止路径）+ 48h 观察期。bandit 安全告警仍强制 r3 永不自动合并。
            for lf in llm_fixes:
                # 找到原 fix 替换 patch
                for i, orig in enumerate(fixes):
                    if orig.error is lf.error:
                        is_security = orig.error.tool == "bandit"
                        fixes[i] = Fix(
                            error=lf.error,
                            patch=lf.patch or orig.patch,
                            needs_human=is_security,  # 仅安全类保留 needs-human
                            description=f"[LLM] {lf.description}",
                            risk_level="r3" if is_security else "r1",
                        )
                        break
        else:
            print("[heal] LLM unavailable (fail-open), 仅使用规则匹配结果")

    issue_url = create_remediation_issue(
        run_id=run_id,
        workflow=args.workflow,
        branch=args.branch,
        head_repo=args.head_repo,
        fingerprint=fingerprint,
        log_excerpt=select_incident_log_excerpt(log_text),
        errors=errors,
        token=token,
        repo=repo,
    )
    if not issue_url:
        print("::error::[heal] remediation incident creation failed")
        return 2

    same_repo_head = not args.head_repo or args.head_repo.casefold() == repo.casefold()
    implementation_dispatched = False
    if same_repo_head:
        implementation_dispatched = dispatch_issue_implementation(
            issue_url,
            token=token,
            repo=repo,
            target_branch=args.branch or "main",
        )
    else:
        print(
            "::warning::[heal] incident came from a fork; automatic implementation "
            f"is disabled for unowned head repository {args.head_repo}"
        )
    if implementation_dispatched:
        print(f"[heal] implementation workflow dispatched for {issue_url}")
    else:
        print(f"::warning::[heal] incident created but implementation dispatch failed: {issue_url}")

    record_fingerprint(
        fingerprint=fingerprint,
        pr_url=issue_url,
        repo=repo,
        workflow=args.workflow,
        store_path=args.store,
    )
    print(
        f"::error::[heal] original failure is not healed; remediation incident created: {issue_url}"
    )
    print(f"[heal] fingerprint recorded: {fingerprint[:8]}")
    return 2


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
