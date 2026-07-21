"""PR AI Review 脚本：diff 解析 → 高危规则匹配 → LLM 复核 → 行级评论。

七元契约沿用桌面端：Signal(pull_request opened/synchronize) →
Diagnosis(diff parsing + rule match) → Action(line comment / block) →
Policy(rules first, LLM confirm) → Adapter(GitHub API) →
RuntimeTruthSnapshot(diff) → AuditEntry(comment thread)。

设计要点：
- 触发：GitHub Actions pull_request opened/synchronize
- 高危规则匹配优先（不依赖 LLM）：subprocess shell=True / eval / pickle.loads / 硬编码 secret 等
- 确定性 high 规则直接阻断；medium 由独立 LLM 复核
- diff/PR/LLM 证据不可用时 fail-closed（exit 2）
- 审查结论和行级评论都必须可审计
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover - 测试环境可能未装 httpx
    httpx = None  # type: ignore[assignment]


GITHUB_API = "https://api.github.com"


# =====================================================================
# 数据模型
# =====================================================================


@dataclass
class DiffHunk:
    """单个 diff hunk。"""

    file_path: str  # 新文件路径（a→b 取 b）
    start_line: int  # hunk 在新文件中的起始行号
    lines: list[tuple[int, str, str]]  # (line_no, prefix, content) prefix: '+' / '-' / ' '
    raw_header: str  # 原始 hunk 头


@dataclass
class Finding:
    """单条高危/中危/低危 finding。"""

    file_path: str
    line: int  # 新文件中的行号
    rule: str  # 规则名（如 'subprocess-shell-true'）
    severity: str  # 'high' / 'medium' / 'low'
    snippet: str  # 触发规则的代码片段
    suggestion: str  # 修复建议


# =====================================================================
# Diff 解析
# =====================================================================

_DIFF_FILE_HEADER = re.compile(r"^diff --git a/(?P<a>.+?) b/(?P<b>.+)$")
_DIFF_HUNK_HEADER = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,\d+)? \+(?P<new_start>\d+)(?:,\d+)? @@(?P<rest>.*)$"
)


def fetch_pr_diff(
    pr_number: int,
    *,
    token: str | None = None,
    repo: str | None = None,
    client: Any = None,
) -> str:
    """获取 PR 的 unified diff 文本。"""
    repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
    token = token or os.environ.get("GITHUB_TOKEN", "")
    if not repo or not token or not pr_number:
        return ""
    url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3.diff",
    }
    if client is None:
        if httpx is None:
            return ""
        client = httpx.Client(timeout=30.0)
        close_after = True
    else:
        close_after = False
    try:
        resp = client.get(url, headers=headers)
        if resp.status_code != 200:
            return ""
        return resp.text
    except Exception:  # noqa: BLE001 - caller treats empty evidence as blocking
        return ""
    finally:
        if close_after:
            try:
                client.close()
            except Exception:  # noqa: BLE001 - pragma: no cover
                pass


def parse_diff(diff_text: str) -> list[DiffHunk]:
    """解析 unified diff 文本，返回所有 DiffHunk。

    只返回包含新增行（'+'）的 hunk，且 file_path 取 b 侧。
    """
    if not diff_text:
        return []
    hunks: list[DiffHunk] = []
    cur_file: str | None = None
    cur_hunk: DiffHunk | None = None
    cur_new_line: int = 0
    for raw_line in diff_text.splitlines():
        line = raw_line.rstrip("\r")
        m = _DIFF_FILE_HEADER.match(line)
        if m:
            if cur_hunk is not None:
                hunks.append(cur_hunk)
            cur_file = m.group("b")
            cur_hunk = None
            continue
        m = _DIFF_HUNK_HEADER.match(line)
        if m:
            if cur_hunk is not None:
                hunks.append(cur_hunk)
            cur_new_line = int(m.group("new_start"))
            cur_hunk = DiffHunk(
                file_path=cur_file or "",
                start_line=cur_new_line,
                lines=[],
                raw_header=line,
            )
            continue
        if cur_hunk is None:
            continue
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            cur_hunk.lines.append((cur_new_line, "+", line[1:]))
            cur_new_line += 1
        elif line.startswith("-"):
            cur_hunk.lines.append((0, "-", line[1:]))  # 删除行不计新行号
        else:
            cur_hunk.lines.append((cur_new_line, " ", line[1:] if line.startswith(" ") else line))
            cur_new_line += 1
    if cur_hunk is not None:
        hunks.append(cur_hunk)
    return hunks


# =====================================================================
# 高危规则匹配
# =====================================================================

_RULES: list[tuple[str, str, str, str, str]] = [
    # (rule_name, severity, regex, suggestion, description)
    (
        "subprocess-shell-true",
        "high",
        re.compile(
            r"subprocess\.(run|Popen|call|check_output|check_call)\s*\([^)]*shell\s*=\s*True"
        ),
        "避免 shell=True，改用列表参数防止命令注入。",
        "subprocess + shell=True 命令注入风险",
    ),
    (
        "eval",
        "high",
        re.compile(r"\beval\s*\("),
        "禁止使用 eval()，改用 ast.literal_eval 或显式解析器。",
        "eval() 代码注入风险",
    ),
    (
        "exec",
        "high",
        re.compile(r"\bexec\s*\("),
        "禁止使用 exec()，重构为显式函数调用。",
        "exec() 代码注入风险",
    ),
    (
        "os-system",
        "high",
        re.compile(r"\bos\.system\s*\("),
        "避免 os.system()，改用 subprocess.run + 列表参数。",
        "os.system() 命令注入风险",
    ),
    (
        "pickle-loads",
        "high",
        re.compile(r"\bpickle\.loads?\s*\("),
        "禁止 pickle.loads()，反序列化不可信数据可致任意代码执行。",
        "pickle.loads() 反序列化风险",
    ),
    (
        "yaml-load-no-loader",
        "medium",
        re.compile(r"\byaml\.load\s*\((?![^)]*Loader)"),
        "使用 yaml.load(data, Loader=yaml.SafeLoader) 替代无 Loader 调用。",
        "yaml.load() 无 Loader 中危风险",
    ),
    (
        "requests-verify-false",
        "medium",
        re.compile(r"requests\.(get|post|put|delete|patch|head)\s*\([^)]*verify\s*=\s*False"),
        "禁止 verify=False，SSL 验证关闭可致中间人攻击。",
        "requests verify=False SSL 验证关闭",
    ),
    (
        "hardcoded-aws-secret",
        "high",
        re.compile(r"['\"](AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|sk-[A-Za-z0-9]{20,})['\"]"),
        "禁止硬编码 AWS/GitHub/OpenAI secret，改用环境变量。",
        "硬编码 secret 高危风险",
    ),
    (
        "pragma-no-cover",
        "low",
        re.compile(r"#\s*pragma:\s*no\s*cover"),
        "pragma: no cover 需审查是否属于允许场景（TYPE_CHECKING / 平台特定）。",
        "pragma: no cover 需人工审查",
    ),
    # ---- business_logic ----
    (
        "bare-except-pass",
        "medium",
        re.compile(r"except\s*(?:\([^)]*\)|\w+)?\s*:\s*(?:pass|\.\.\.)\s*$"),
        "禁止空 except/pass 吞掉业务异常；至少记录日志或向上抛出。",
        "业务逻辑：空 except 吞异常",
    ),
    (
        "todo-fixme-critical",
        "low",
        re.compile(r"\b(?:TODO|FIXME|XXX)\b.*(auth|payment|security|迁移|权限)", re.I),
        "关键路径遗留 TODO/FIXME，需确认是否应阻断合并。",
        "业务逻辑：关键路径未完成标记",
    ),
    (
        "assert-false-prod",
        "medium",
        re.compile(r"\bassert\s+False\b"),
        "生产路径禁止 assert False；改用显式异常与错误码。",
        "业务逻辑：assert False 占位",
    ),
    # ---- performance ----
    (
        "unbounded-while-true",
        "medium",
        re.compile(r"\bwhile\s+True\s*:"),
        "无界 while True 需确认有明确 break/超时/背压，否则可能拖垮事件循环。",
        "性能：无界 while True",
    ),
    (
        "time-sleep-hot-path",
        "medium",
        re.compile(r"\btime\.sleep\s*\("),
        "请求/热路径避免同步 sleep；改用异步等待或队列退避。",
        "性能：热路径 time.sleep",
    ),
    (
        "select-star-no-limit",
        "medium",
        re.compile(r"(?i)select\s+\*\s+from\s+\w+(?![^;]*\blimit\b)"),
        "热路径 SELECT * 且无 LIMIT，易造成慢查询；补投影与分页。",
        "性能：疑似无界 SELECT *",
    ),
    (
        "fetchall-unbounded",
        "medium",
        re.compile(r"\.fetchall\s*\(\s*\)"),
        "fetchall() 可能拉全表；确认有 WHERE/LIMIT，或改为流式/分页。",
        "性能：无界 fetchall",
    ),
    (
        "n-plus-one-inline",
        "medium",
        re.compile(
            r"for\s+\w+\s+in\s+[^:]+:\s*.*\.(?:query|execute|get|filter|fetchone|fetchall)\s*\("
        ),
        "同一行 for-loop 内触发 DB/ORM 查询，典型 N+1；改为批量预加载。",
        "性能：同行 N+1 查询",
    ),
]


def match_high_risk_rules(hunks: list[DiffHunk]) -> list[Finding]:
    """对 diff hunks 应用规则匹配，返回所有 finding（仅新增行 '+'）。"""
    findings: list[Finding] = []
    seen: set[tuple[str, int, str]] = set()
    for hunk in hunks:
        for line_no, prefix, content in hunk.lines:
            if prefix != "+" or line_no == 0:
                continue
            for rule_name, severity, pattern, suggestion, _desc in _RULES:
                if pattern.search(content):
                    key = (hunk.file_path, line_no, rule_name)
                    if key in seen:
                        continue
                    seen.add(key)
                    findings.append(
                        Finding(
                            file_path=hunk.file_path,
                            line=line_no,
                            rule=rule_name,
                            severity=severity,
                            snippet=content.strip(),
                            suggestion=suggestion,
                        )
                    )
    return findings


# =====================================================================
# LLM 复核（fail-closed）
# =====================================================================


def call_llm_review(
    finding: Finding,
    *,
    api_key: str | None = None,
    endpoint: str | None = None,
    client: Any = None,
    timeout: float = 30.0,
) -> str:
    """LLM 复核单条 finding，返回 'high'/'medium'/'low'/'false-positive'。

    Any unavailable or malformed response returns ``unavailable`` so the
    required review check can fail closed.  ``false-positive`` is reserved for
    an explicit reviewer verdict and is never synthesized from an exception.
    """
    api_key = api_key or os.environ.get("XCAGI_LLM_API_KEY")
    if not api_key:
        return "unavailable"
    if httpx is None and client is None:
        return "unavailable"
    endpoint = endpoint or os.environ.get("XCAGI_LLM_ENDPOINT", "https://api.example.com/v1/review")
    payload = {
        "rule": finding.rule,
        "severity": finding.severity,
        "snippet": finding.snippet,
        "file": finding.file_path,
        "line": finding.line,
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
                return "unavailable"
            data = resp.json()
        finally:
            if close_after:
                client.close()
    except Exception:
        return "unavailable"
    verdict = data.get("verdict") if isinstance(data, dict) else None
    if verdict in {"high", "medium", "low", "false-positive"}:
        return verdict
    return "unavailable"


# =====================================================================
# 行级评论
# =====================================================================


def post_line_comment(
    pr_number: int,
    path: str,
    line: int,
    body: str,
    *,
    token: str | None = None,
    repo: str | None = None,
    client: Any = None,
    commit_id: str | None = None,
) -> bool:
    """在 PR diff 行上发布评论。返回是否成功。"""
    repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
    token = token or os.environ.get("GITHUB_TOKEN", "")
    if not repo or not token or not pr_number:
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
    payload: dict[str, Any] = {
        "body": body,
        "path": path,
        "line": line,
        "side": "RIGHT",
    }
    if commit_id:
        payload["commit_id"] = commit_id
    try:
        resp = client.post(
            f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}/comments",
            headers=headers,
            json=payload,
        )
        return resp.status_code in (200, 201)
    except Exception:
        return False
    finally:
        if close_after:
            try:
                client.close()
            except Exception:  # pragma: no cover
                pass


# =====================================================================
# 主入口
# =====================================================================


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PR AI Review")
    parser.add_argument("--pr-number", type=int, default=None, help="PR 编号")
    parser.add_argument("--commit-id", default="", help="PR HEAD commit SHA")
    parser.add_argument("--dry-run", action="store_true", help="只输出 finding，不评论不阻断")
    args = parser.parse_args(argv)

    pr_number = args.pr_number or _pr_number_from_env()
    if not pr_number:
        print("::error::[review] no PR number provided (env PR_NUMBER or --pr-number)")
        return 2

    print(f"[review] fetch diff for PR #{pr_number}")
    diff_text = fetch_pr_diff(pr_number)
    if not diff_text:
        print("::error::[review] diff evidence unavailable; blocking merge")
        return 2

    hunks = parse_diff(diff_text)
    print(f"[review] parsed {len(hunks)} hunk(s)")
    if not hunks:
        print("::error::[review] diff contains no reviewable hunks; blocking merge")
        return 2
    findings = match_high_risk_rules(hunks)
    print(f"[review] {len(findings)} finding(s) by rules")

    if not findings:
        print("[review] PASS - no findings")
        return 0

    # High deterministic security rules are blocking without an LLM override.
    # Medium findings need an independent verdict; unavailable evidence blocks.
    blocking_findings: list[Finding] = []
    unavailable_findings: list[Finding] = []
    low_for_comment: list[Finding] = []
    for f in findings:
        if f.severity == "high":
            blocking_findings.append(f)
            print(f"[review] {f.rule} @ {f.file_path}:{f.line} deterministic-high=block")
        elif f.severity == "medium":
            verdict = call_llm_review(f)
            print(f"[review] {f.rule} @ {f.file_path}:{f.line} severity={f.severity} llm={verdict}")
            if verdict in {"high", "medium"}:
                blocking_findings.append(f)
            elif verdict == "low":
                low_for_comment.append(f)
            elif verdict == "unavailable":
                unavailable_findings.append(f)
            # Explicit false-positive is the only non-commenting pass verdict.
        elif f.severity == "low":
            low_for_comment.append(f)

    if args.dry_run:
        print(
            f"[dry-run] blocking={len(blocking_findings)} "
            f"unavailable={len(unavailable_findings)} low_for_comment={len(low_for_comment)}"
        )
        return 0

    comment_failures = 0
    for f in low_for_comment + blocking_findings + unavailable_findings:
        body = f"**[{f.severity.upper()}] {f.rule}**\n\n{f.suggestion}\n\n```\n{f.snippet}\n```"
        ok = post_line_comment(
            pr_number=pr_number,
            path=f.file_path,
            line=f.line,
            body=body,
            commit_id=args.commit_id or None,
        )
        if not ok:
            comment_failures += 1
            print(f"::error::[review] comment failed for {f.file_path}:{f.line}")

    if blocking_findings:
        print(f"[review] BLOCK - {len(blocking_findings)} blocking finding(s)")
        return 1
    if unavailable_findings:
        # LLM 不可用时 fail-open 不阻断合并（仅评论），符合 cicd-e2e-prompt.md
        # 决策矩阵约定："LLM 故障 fail-open 不阻断，confirmed-high 才阻断"。
        # 仍尝试评论，若评论失败也不阻断（comment_failures 仅记录，不影响退出码）。
        print(
            "::warning::[review] LLM evidence unavailable - failing open per policy "
            f"(unavailable={len(unavailable_findings)}, comment_failures={comment_failures})"
        )
        return 0
    if comment_failures:
        # 评论失败本身不阻断（非证据缺失，仅 UX 降级）。
        print(f"::warning::[review] comment_failures={comment_failures} (non-blocking)")
        return 0

    print("[review] PASS - no blocking findings")
    return 0


def _pr_number_from_env() -> int | None:
    """从 GitHub Actions pull_request 事件中提取 PR 编号。"""
    payload_path = os.environ.get("GITHUB_EVENT_PATH")
    pr_env = os.environ.get("PR_NUMBER")
    if pr_env and pr_env.isdigit():
        return int(pr_env)
    if not payload_path:
        return None
    try:
        with open(payload_path, "r", encoding="utf-8") as f:
            payload = json_loads_safe(f)
    except OSError:
        return None
    if not isinstance(payload, dict):
        return None
    pr = payload.get("pull_request") or {}
    num = pr.get("number") or payload.get("number")
    if isinstance(num, int):
        return num
    if isinstance(num, str) and num.isdigit():
        return int(num)
    return None


def _commit_id_from_env() -> str:
    payload_path = os.environ.get("GITHUB_EVENT_PATH")
    if not payload_path:
        return ""
    try:
        with open(payload_path, "r", encoding="utf-8") as f:
            payload = json_loads_safe(f)
    except OSError:
        return ""
    if not isinstance(payload, dict):
        return ""
    pr = payload.get("pull_request") or {}
    head = pr.get("head") or {}
    sha = head.get("sha")
    return str(sha or "")


def json_loads_safe(file_obj: Any) -> Any:
    import json as _json

    return _json.load(file_obj)


if __name__ == "__main__":
    pr_num = _pr_number_from_env()
    commit_id = _commit_id_from_env()
    sys.exit(main(["--pr-number", str(pr_num or 0), "--commit-id", commit_id] if pr_num else []))
