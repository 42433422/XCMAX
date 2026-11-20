"""CI 自愈：校验失败来源 → 持久事件 → Para 执行 / 原任务恢复。

七元契约沿用桌面端：Signal(workflow_run failure) → Diagnosis(error extract) →
Action(Para task) → Policy(来源/预算/可信回执) → Adapter(GitHub API) →
RuntimeTruthSnapshot(logs) → AuditEntry(self-heal-fingerprints.jsonl)。

设计要点：
- 触发：GitHub Actions workflow_run.completed + conclusion=failure
- 同指纹 24h 去重：SHA256(repo + workflow + job + error_line_hash)
- 提取 ruff/bandit/mypy/pytest 证据，诊断/实现委托现有 Para 链路
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

# When this file is executed by path, Python only adds ``scripts/ci`` to
# ``sys.path``. Keep the FHD package root importable regardless of the
# caller's working directory (including GitHub Actions' working directory).
ROOT = Path(__file__).resolve().parents[2]
for _import_root in (ROOT, Path(__file__).resolve().parent):
    if str(_import_root) not in sys.path:
        sys.path.insert(0, str(_import_root))

import self_heal_freshness as freshness
import self_heal_reconcile as recovery

from app.utils.operational_errors import RECOVERABLE_ERRORS

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
    risk_level: str = (
        "r3"  # r0/r1/r2/r3 — 分级合并 SLA 依据（bandit 安全类强制 r3，LLM 业务修复降 r1）
    )


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
GITHUB_API_VERSION = "2022-11-28"
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
    except RECOVERABLE_ERRORS:
        return ""
    finally:
        if close_after:
            try:
                client.close()
            except RECOVERABLE_ERRORS:
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
    workflow_path: str = "",
    workflow_id: int = 0,
) -> IncidentBudgetDecision:
    """Bound new incidents using the durable queue and verified source identities."""
    repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
    token = token or os.environ.get("GITHUB_TOKEN", "")
    max_open = max_open or _positive_env_int(
        "AI_SELF_HEAL_MAX_OPEN_INCIDENTS", DEFAULT_MAX_OPEN_INCIDENTS
    )
    max_open_per_workflow = max_open_per_workflow or _positive_env_int(
        "AI_SELF_HEAL_MAX_OPEN_PER_WORKFLOW", DEFAULT_MAX_OPEN_INCIDENTS_PER_WORKFLOW
    )
    max_recent = max_recent or _positive_env_int(
        "AI_SELF_HEAL_MAX_RECENT_INCIDENTS", DEFAULT_MAX_RECENT_INCIDENTS
    )
    budget_hours = budget_hours or _positive_env_int(
        "AI_SELF_HEAL_INCIDENT_BUDGET_HOURS", DEFAULT_INCIDENT_BUDGET_HOURS
    )
    if not repo or not token:
        return IncidentBudgetDecision(False, "budget_lookup_missing_repo_or_token")
    if client is None and httpx is None:
        return IncidentBudgetDecision(False, "budget_lookup_httpx_unavailable")
    close_after = client is None
    client = client or httpx.Client(timeout=30.0)
    get = _client_getter(client, token)
    cutoff = (time.time() if now_ts is None else now_ts) - budget_hours * 3600
    total = per_workflow = recent = 0
    try:
        for item in freshness.pages(
            get,
            f"/repos/{repo}/issues",
            {
                "state": "open",
                "labels": "auto-incident",
                "sort": "created",
                "direction": "desc",
            },
        ):
            if item.get("pull_request"):
                continue
            total += 1
            body = str(item.get("body") or "")
            same = f"- Workflow: `{workflow or 'unknown'}`" in body
            if workflow_path:
                fields = freshness.incident_fields(body)
                source_id = fields.get("Run ID", "")
                if source_id.isdigit():
                    source = freshness._get(get, f"/repos/{repo}/actions/runs/{source_id}")
                    if source.get("id") != int(source_id):
                        raise freshness.LookupFailed("budget source run invalid")
                    identity, path = freshness.workflow_identity(source)
                    same = path == workflow_path
                    if same and identity != workflow_id:
                        raise freshness.LookupFailed("budget workflow identity changed")
                elif fields.get("Workflow") or fields.get("Self-Heal-Workflow"):
                    raise freshness.LookupFailed("budget incident source identity missing")
            per_workflow += int(same)
            try:
                recent += int(
                    datetime.fromisoformat(
                        str(item.get("created_at") or "").replace("Z", "+00:00")
                    ).timestamp()
                    >= cutoff
                )
            except ValueError:
                pass
            if total >= max_open:
                return IncidentBudgetDecision(
                    False,
                    f"global_open_incidents:{total}>={max_open}",
                    total,
                    per_workflow,
                    recent,
                )
            if per_workflow >= max_open_per_workflow:
                return IncidentBudgetDecision(
                    False,
                    f"workflow_open_incidents:{per_workflow}>={max_open_per_workflow}",
                    total,
                    per_workflow,
                    recent,
                )
            if recent >= max_recent:
                return IncidentBudgetDecision(
                    False,
                    f"recent_incidents:{recent}>={max_recent}/{budget_hours}h",
                    total,
                    per_workflow,
                    recent,
                )
    except (freshness.LookupFailed, *RECOVERABLE_ERRORS) as exc:
        return IncidentBudgetDecision(
            False,
            f"budget_lookup_error:{type(exc).__name__}",
            total,
            per_workflow,
            recent,
        )
    finally:
        if close_after:
            client.close()
    return IncidentBudgetDecision(True, "within_budget", total, per_workflow, recent)


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
    """Find an open durable incident; lookup failure never proves absence."""
    repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
    token = token or os.environ.get("GITHUB_TOKEN", "")
    if not fingerprint:
        return ""
    if not repo or not token or (client is None and httpx is None):
        raise freshness.LookupFailed("incident lookup client/repo/token unavailable")
    since = datetime.fromtimestamp(
        (time.time() if now_ts is None else now_ts) - budget_hours * 3600, tz=UTC
    ).isoformat()
    close_after = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        for item in freshness.pages(
            _client_getter(client, token),
            f"/repos/{repo}/issues",
            {
                "state": "open",
                "labels": "auto-incident",
                "sort": "created",
                "direction": "desc",
                "since": since,
            },
        ):
            if not item.get("pull_request") and f"Correlation/Fingerprint: `{fingerprint}`" in str(
                item.get("body") or ""
            ):
                return str(item.get("html_url") or "")
    except RECOVERABLE_ERRORS as exc:
        raise freshness.LookupFailed(f"incident lookup failed: {type(exc).__name__}") from exc
    finally:
        if close_after:
            client.close()
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
    - 缺 XCAGI_LLM_ENDPOINT → 返回 None（不再回退到占位地址，避免把密钥发给第三方）
    - httpx 缺失 → 返回 None
    - 超时/网络错误 → 返回 None
    - 任意异常 → 返回 None
    """
    api_key = api_key or os.environ.get("XCAGI_LLM_API_KEY")
    if not api_key or not errors:
        return None
    if httpx is None and client is None:
        return None
    endpoint = (endpoint or os.environ.get("XCAGI_LLM_ENDPOINT") or "").strip()
    if not endpoint:
        # 曾默认回退到 https://api.example.com/v1/fix：该地址在 GitHub runner 上可解析，
        # 每次自愈都会把 Bearer XCAGI_LLM_API_KEY 发给与本项目无关的主机且永远失败。
        print("[heal] XCAGI_LLM_ENDPOINT not configured; skip LLM fallback")
        return None
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
    except RECOVERABLE_ERRORS:
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


def create_remediation_issue(
    *,
    run_id: int,
    workflow: str,
    branch: str,
    fingerprint: str,
    log_excerpt: str,
    errors: list[ErrorEntry],
    head_repo: str = "",
    markers: list[str] | None = None,
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
        f"- Correlation/Fingerprint: `{fingerprint}`\n"
        + "".join(f"- {mark}\n" for mark in markers or [])
        + "\n"
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
    except RECOVERABLE_ERRORS:
        return ""
    finally:
        if close_after:
            try:
                client.close()
            except RECOVERABLE_ERRORS:
                pass


def dispatch_issue_implementation(
    issue_url: str,
    *,
    token: str | None = None,
    repo: str | None = None,
    ref: str = "main",
    target_branch: str = "main",
    control_task_id: str = "",
    client: Any = None,
) -> bool:
    """Explicitly dispatch the implementation loop for a token-created issue.

    Events emitted with ``GITHUB_TOKEN`` do not recursively start most other
    workflows. ``workflow_dispatch`` is the supported exception, so incident
    creation and implementation handoff must be two explicit API operations.
    """

    repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
    token = token or os.environ.get("GITHUB_TOKEN", "")
    match = re.fullmatch(
        re.escape(f"https://github.com/{repo}/issues/") + r"(?P<number>\d+)/?",
        str(issue_url or ""),
    )
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
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }
    receipt = {
        "repo": repo,
        "issue_number": int(match.group("number")),
        "base_branch": str(target_branch or "main").strip(),
        "control_task_id": control_task_id,
        "status": "pending",
        "dispatch_run_id": 0,
    }
    try:
        # Persist intent first. A lost response must not become a fresh control task.
        intent = client.post(
            f"{GITHUB_API}/repos/{repo}/issues/{match.group('number')}/comments",
            headers=headers,
            json={"body": recovery.receipt_body(receipt)},
        )
        intent_id = int(intent.json().get("id") or 0) if intent.status_code == 201 else 0
        if not intent_id:
            return False
        inputs = {
            "issue_number": match.group("number"),
            "target_branch": receipt["base_branch"],
        }
        if control_task_id:
            inputs["control_task_id"] = control_task_id
        accepted = False
        try:
            response = client.post(
                f"{GITHUB_API}/repos/{repo}/actions/workflows/fhd-ai-issue-implement.yml/dispatches",
                headers=headers,
                json={
                    "ref": str(ref).strip(),
                    "inputs": inputs,
                    "return_run_details": True,
                },
            )
            if response.status_code == 200:
                details = response.json()
                receipt["dispatch_run_id"] = (
                    int(details.get("workflow_run_id") or 0) if isinstance(details, dict) else 0
                )
                accepted = receipt["dispatch_run_id"] > 0
                receipt["status"] = "accepted" if accepted else "unknown"
            elif response.status_code == 204:
                accepted, receipt["status"] = True, "accepted_unknown_run"
            else:
                receipt["status"] = (
                    "rejected" if response.status_code in {400, 401, 403, 404, 422} else "unknown"
                )
        except RECOVERABLE_ERRORS:
            receipt["status"] = "unknown"
        print(f"[heal] dispatch status={receipt['status']} run_id={receipt['dispatch_run_id']}")
        recorded = client.patch(
            f"{GITHUB_API}/repos/{repo}/issues/comments/{intent_id}",
            headers=headers,
            json={"body": recovery.receipt_body(receipt)},
        )
        if recorded.status_code != 200:
            print("::warning::[heal] dispatch outcome receipt unavailable; pending intent retained")
        return accepted
    except RECOVERABLE_ERRORS:
        return False
    finally:
        if close_after:
            try:
                client.close()
            except RECOVERABLE_ERRORS:
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
    parser.add_argument("--dry-run", action="store_true", help="只读诊断/对账，不派发或关闭事件")
    parser.add_argument("--reconcile", action="store_true", help="对账并恢复已有 auto-incident")
    parser.add_argument(
        "--scan-open-prs",
        action="store_true",
        help="扫描授权的 main PR，并将当前 HEAD 上受支持的失败 CI 接入既有 Para 自愈链路",
    )
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if args.reconcile:
        return reconcile_incidents(token, repo, dry_run=args.dry_run)
    if args.scan_open_prs:
        return scan_open_prs(token, repo, dry_run=args.dry_run)

    # autonomy/ 分支不递归
    if is_autonomy_branch(args.branch):
        print(f"[skip] autonomy/* branch detected ({args.branch}), 递归保护触发，跳过自愈")
        return 0

    run_id = args.run_id or _run_id_from_env()
    if not run_id:
        print("::error::[heal] no failed run_id provided")
        return 2

    # 过期失败过滤：在下载日志 / 调 LLM / 建单之前判定；跳过=0，查询失败拦截=2。
    gate = check_freshness(args.workflow, run_id, token, repo)
    if gate.action != freshness.PROCEED:
        return 0 if gate.action == freshness.SKIP else 2
    gated = gate.reason == "current_head"
    if (gate.head_branch and args.branch and gate.head_branch != args.branch) or (
        gate.head_repo and args.head_repo and gate.head_repo.casefold() != args.head_repo.casefold()
    ):
        print("::error::[heal] source branch/repository does not match the API")
        return 2
    args.branch, args.head_repo = (
        gate.head_branch or args.branch,
        gate.head_repo or args.head_repo,
    )
    if is_autonomy_branch(args.branch):
        return 0
    workflow = gate.workflow or args.workflow
    markers = freshness.source_markers(gate, include_source=gated) if gate.run_attempt else []
    if markers and not args.dry_run:
        lookup_ok, existing = find_source_incident(markers, token, repo)
        if not lookup_ok:
            return 2
        if existing:
            recover_existing_incident(existing, token, repo, dry_run=True)
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
    # Para owns diagnosis and execution. Unused LLM patches here only spent tokens.
    fingerprint_evidence = canonical_fingerprint_evidence(errors, log_text)
    fingerprint = compute_fingerprint(
        repo=repo,
        workflow=gate.workflow_path or workflow,
        job=args.branch,
        error_line=fingerprint_evidence,
    )
    if args.dry_run:
        print(
            f"[dry-run] failure has {len(errors)} actionable error(s), "
            f"fingerprint={fingerprint[:8]}"
        )
        return 0

    # A local fingerprint is a cache, not proof of completion. Existing incidents
    # are reconciled before the creation budget, including when the queue is full.
    try:
        existing_issue = find_existing_remediation_issue(fingerprint, token=token, repo=repo)
    except (freshness.LookupFailed, *RECOVERABLE_ERRORS) as exc:
        print(f"::error::[heal] durable lookup unresolved: {type(exc).__name__}")
        return 2
    if existing_issue:
        result = recover_existing_incident(existing_issue, token, repo, dry_run=True)
        if result["state"] not in {"recovered", "superseded"}:
            return 2

    budget = check_incident_budget(
        workflow,
        token=token,
        repo=repo,
        workflow_path=gate.workflow_path,
        workflow_id=gate.workflow_id,
    )
    if not budget.allowed:
        print(
            "::error::[heal] incident circuit open; no issue or LLM dispatch created: "
            f"{budget.reason} "
            f"(open={budget.open_total}, workflow_open={budget.open_for_workflow}, "
            f"recent={budget.recent_total})"
        )
        return 2

    if gated:  # 派单前再查一次：排队或处理期间 PR / 分支可能已推新提交
        gate = check_freshness(args.workflow, run_id, token, repo)
        if gate.action != freshness.PROCEED:
            return 0 if gate.action == freshness.SKIP else 2

    issue_url = create_remediation_issue(
        markers=markers,
        run_id=run_id,
        workflow=workflow,
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
        workflow=workflow,
        store_path=args.store,
    )
    print(
        f"::error::[heal] original failure is not healed; remediation incident created: {issue_url}"
    )
    print(f"[heal] fingerprint recorded: {fingerprint[:8]}")
    return 2


def scan_open_prs(token: str, repo: str, *, dry_run: bool = False) -> int:
    """Backstop workflow_run delivery by discovering eligible failures on open PRs.

    This is deliberately narrow: same-repository, trusted author, non-draft PRs
    targeting this repository's main branch, and a completed failure from an
    allowlisted code workflow on the exact current PR HEAD. Each candidate is
    handed to the normal self-heal entrypoint, which rechecks freshness and
    authorization before creating an incident or dispatching Para.
    """
    if not token or not repo or httpx is None:
        print("::error::[scan] GitHub token, repository, or HTTP client unavailable")
        return 2

    from scripts.dev import para_pr_repair

    get = _github_getter(token, repo)
    authors = para_pr_repair.load_trusted_authors()
    failures: list[tuple[dict[str, Any], dict[str, Any]]] = []
    try:
        prs = freshness.pages(
            get,
            f"/repos/{repo}/pulls",
            {"state": "open", "base": "main", "sort": "updated", "direction": "desc"},
        )
        for pr in prs:
            head, base = pr.get("head") or {}, pr.get("base") or {}
            number, branch, sha = (
                pr.get("number"),
                str(head.get("ref") or ""),
                str(head.get("sha") or ""),
            )
            if (
                type(number) is not int
                or not para_pr_repair.authorized_pr(pr, authors)
                or not para_pr_repair.BRANCH.fullmatch(branch)
                or ".." in branch
                or branch == "main"
                or is_autonomy_branch(branch)
                or base.get("ref") != "main"
                or (base.get("repo") or {}).get("full_name", "").casefold() != repo.casefold()
                or (head.get("repo") or {}).get("full_name", "").casefold() != repo.casefold()
                or not re.fullmatch(r"[0-9a-f]{40}", sha)
            ):
                continue

            runs = freshness.pages(
                get,
                f"/repos/{repo}/actions/runs",
                {"head_sha": sha, "event": "pull_request", "per_page": 100},
                key="workflow_runs",
            )
            latest = {}
            for run in runs:
                path = run.get("path")
                if (
                    path not in freshness.CODE_CI_PATHS
                    or run.get("head_sha") != sha
                    or run.get("head_branch") != branch
                    or run.get("event") != "pull_request"
                    or (
                        run.get("pull_requests")
                        and [item.get("number") for item in run["pull_requests"]] != [number]
                    )
                ):
                    continue
                current = latest.get(path)
                if current is None or _run_order(run) > _run_order(current):
                    latest[path] = run
            eligible = [
                run
                for run in latest.values()
                if run.get("status") == "completed" and run.get("conclusion") == "failure"
            ]
            if not eligible:
                continue
            run = max(eligible, key=_run_order)
            workflow_id = int(run.get("workflow_id") or 0)
            path = str(run.get("path") or "")
            if workflow_id < 1:
                continue
            target = para_pr_repair.Target(number, branch, sha, int(run["id"]), workflow_id, path)
            # Reuse the original-PR authorization contract; discovery alone never
            # grants write permission or weakens the implementation workflow gate.
            try:
                para_pr_repair.open_pr(repo, target, sha, get)
            except ValueError:
                print(f"::notice::[scan] PR #{number} could not be reauthorized")
                continue
            failures.append((pr, run))
    except (
        freshness.LookupFailed,
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        *RECOVERABLE_ERRORS,
    ) as exc:
        print(f"::error::[scan] fail-closed GitHub discovery: {type(exc).__name__}: {exc}")
        return 2

    print(f"[scan] eligible exact-HEAD PR failures={len(failures)}")
    result = 0
    for pr, run in failures:
        print(
            f"[scan] PR #{pr['number']} head={pr['head']['sha']} "
            f"run={run['id']} workflow={run['name']}"
        )
        code = main(
            [
                "--run-id",
                str(run["id"]),
                "--workflow",
                freshness.CODE_CI_PATHS[run["path"]],
                "--branch",
                str(pr["head"]["ref"]),
                "--head-repo",
                repo,
                *(["--dry-run"] if dry_run else []),
            ]
        )
        if code:
            result = code
    return result


def _run_order(run: dict) -> tuple[str, int, int]:
    return str(run.get("created_at") or ""), int(run["id"]), int(run.get("run_attempt") or 0)


def _run_id_from_env() -> int | None:
    """从 workflow_run 事件 payload 中提取 run_id（GitHub Actions 环境）。"""
    run_id = freshness.event_workflow_run().get("id")
    if isinstance(run_id, str) and run_id.isdigit():
        return int(run_id)
    return run_id if isinstance(run_id, int) else None


def _client_getter(client, token: str) -> freshness.Getter:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }

    def get(path: str, params: dict[str, Any]) -> tuple[int, Any]:
        if client is None or not token:
            raise freshness.LookupFailed("GitHub client/token/repo unavailable")
        try:
            resp = client.get(f"{GITHUB_API}{path}", headers=headers, params=params)
            return resp.status_code, resp.json()
        except RECOVERABLE_ERRORS as exc:
            raise freshness.LookupFailed(f"GET {path}: {type(exc).__name__}") from exc

    return get


def _github_getter(token: str, repo: str) -> freshness.Getter:
    """Read-only GitHub access; each request owns its transport lifetime."""

    def get(path: str, params: dict[str, Any]) -> tuple[int, Any]:
        if httpx is None or not repo:
            raise freshness.LookupFailed("GitHub client/repo unavailable")
        with httpx.Client(timeout=30.0) as client:
            return _client_getter(client, token)(path, params)

    return get


def check_freshness(workflow: str, run_id: int, token: str, repo: str) -> freshness.Decision:
    """过期失败过滤（只读）；结果写日志与 job summary。"""
    decision = freshness.evaluate(
        workflow=workflow,
        run_id=run_id,
        repo=repo,
        get=_github_getter(token, repo),
        event_run=freshness.event_workflow_run(),
    )
    freshness.record(decision)
    return decision


def find_source_incident(markers: list[str], token: str, repo: str) -> tuple[bool, str]:
    """按 run id+attempt / workflow@head_sha 标记查重；返回 (查询成功, 已有 issue)。"""
    try:
        return True, freshness.find_marked_issue(_github_getter(token, repo), repo, markers)
    except (freshness.LookupFailed, *RECOVERABLE_ERRORS) as exc:
        print(f"[freshness] incident marker lookup failed: {exc}")
        return False, ""


def _github_writer(token: str, repo: str):
    def write(method: str, path: str, payload: dict) -> tuple[int, Any]:
        if httpx is None or not token or not repo:
            raise freshness.LookupFailed("GitHub writer/token/repo unavailable")
        with httpx.Client(timeout=30.0) as client:
            response = client.request(
                method,
                f"{GITHUB_API}{path}",
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": GITHUB_API_VERSION,
                },
            )
            return response.status_code, response.json() if response.content else None

    return write


def _reconcile_issue(issue: dict, token: str, repo: str, *, dry_run: bool, get) -> dict:
    try:
        result = recovery.reconcile_one(
            issue,
            repo=repo,
            get=get,
            write=_github_writer(token, repo),
            dry_run=dry_run,
            dispatch=lambda url, **kw: dispatch_issue_implementation(
                url, token=token, repo=repo, **kw
            ),
        )
    except (freshness.LookupFailed, *RECOVERABLE_ERRORS) as exc:
        result = {
            "issue_number": issue.get("number"),
            "state": "unresolved",
            "reason": f"lookup_or_action_failed:{type(exc).__name__}",
        }
    print(f"[reconcile] {json.dumps(result, sort_keys=True)}")
    return result


def recover_existing_incident(
    issue_url: str, token: str, repo: str, *, dry_run: bool = True
) -> dict:
    """Source-event jobs observe only; the serialized reconciler owns recovery writes."""
    match = re.fullmatch(re.escape(f"https://github.com/{repo}/issues/") + r"(\d+)", issue_url)
    if not match:
        return {"state": "unresolved", "reason": "incident_url_mismatch"}
    get = _github_getter(token, repo)
    try:
        issue = freshness._get(get, f"/repos/{repo}/issues/{match.group(1)}")
    except (freshness.LookupFailed, *RECOVERABLE_ERRORS) as exc:
        return {
            "state": "unresolved",
            "reason": f"incident_lookup_failed:{type(exc).__name__}",
        }
    return _reconcile_issue(issue, token, repo, dry_run=dry_run, get=get)


def reconcile_incidents(
    token: str, repo: str, *, dry_run: bool, report_path: Path | None = None
) -> int:
    """Existing queue maintenance, independent of the new-incident budget."""
    get = _github_getter(token, repo)
    try:
        issues = list(
            freshness.pages(
                get,
                f"/repos/{repo}/issues",
                {
                    "state": "open",
                    "labels": "auto-incident",
                    "sort": "created",
                    "direction": "asc",
                },
            )
        )
    except (freshness.LookupFailed, *RECOVERABLE_ERRORS) as exc:
        results = [
            {
                "state": "unresolved",
                "reason": f"queue_lookup_failed:{type(exc).__name__}",
            }
        ]
    else:
        results = [
            _reconcile_issue(issue, token, repo, dry_run=dry_run, get=get) for issue in issues
        ]
    output = report_path or ROOT / "test_reports" / "self_heal_reconciliation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"dry_run": dry_run, "incidents": results}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write("\n### Self-Heal incident reconciliation\n\n")
            for result in results:
                stream.write(
                    f"- #{result.get('issue_number', '?')}: `{result['state']}` — `{result['reason']}`\n"
                )
    # A successful inventory is not a claim of repair. Applied pending work stays red.
    return (
        0
        if dry_run
        or all(r["state"] in {"recovered", "superseded", "already_closed"} for r in results)
        else 2
    )


if __name__ == "__main__":
    sys.exit(main())
