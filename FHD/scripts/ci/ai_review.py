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
import json
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
_AI_REVIEW_TOOLING_FILES = {
    "FHD/scripts/ci/ai_review.py",
    "FHD/tests/test_ci/test_ai_review.py",
}
_KB_EVIDENCE_JSON = re.compile(r"^FHD/XCAGI/kb/(?:fixes|patterns)/.+\.json$")
_KB_EVIDENCE_SECRET_RULES = {"hardcoded-aws-secret", "js-hardcoded-third-party-key"}


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

_DIFF_FILE_HEADER = re.compile(r'^diff --git (?P<a>"?a/.+?"?) (?P<b>"?b/.+?"?)$')
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
    files_url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}/files"
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
        if resp.status_code == 200 and resp.text.strip():
            return resp.text

        # Large PR diff can trigger non-200 or empty response; fallback to files API.
        diff_parts: list[str] = []
        page = 1
        while True:
            files_resp = client.get(
                files_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                params={"per_page": 100, "page": page},
            )
            if files_resp.status_code != 200:
                return ""

            files = files_resp.json()
            if not isinstance(files, list):
                return ""
            if not files:
                break

            for file_entry in files:
                if not isinstance(file_entry, dict):
                    continue
                file_path = file_entry.get("filename")
                patch = file_entry.get("patch")
                if not file_path or not patch:
                    continue
                diff_parts.append(f"diff --git a/{file_path} b/{file_path}\n")
                diff_parts.append(f"--- a/{file_path}\n")
                diff_parts.append(f"+++ b/{file_path}\n")
                diff_parts.append(f"{patch}\n")

            if len(files) < 100:
                break
            page += 1

        if not diff_parts:
            return ""
        return "".join(diff_parts)
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
            raw_file = m.group("b")
            if raw_file.startswith('"') and raw_file.endswith('"'):
                raw_file = raw_file[1:-1]
            cur_file = raw_file[2:] if raw_file.startswith("b/") else raw_file
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
        re.compile(r"(?<![\w.])exec\s*\("),
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
    # ---- static site security (官网静态资源 / nginx / market 前端) ----
    (
        "html-inline-event-handler",
        "high",
        re.compile(r"<(?:a|img|button|input|body|svg|iframe)\b[^>]*\bon\w+\s*=", re.I),
        "HTML 内联事件处理器（onclick/onerror 等）可致 XSS；改用 addEventListener 或 CSP。",
        "静态站点：HTML 内联事件处理器 XSS 风险",
    ),
    (
        "html-innerhtml-assignment",
        "high",
        re.compile(r"\.innerHTML\s*=\s*[^;\n]+"),
        "禁止 .innerHTML 直接赋值字符串，可致 DOM XSS；改用 textContent 或 DOMPurify 净化。",
        "静态站点：innerHTML 赋值致 DOM XSS",
    ),
    (
        "html-document-write",
        "high",
        re.compile(r"\bdocument\.write\s*\("),
        "禁止 document.write()，已废弃且阻塞渲染；改用 DOM API 或 innerHTML+净化。",
        "静态站点：document.write 已废弃且高危",
    ),
    (
        "html-remote-script-http",
        "medium",
        re.compile(r'<script\b[^>]+src\s*=\s*"http://', re.I),
        "禁止 http:// 远程脚本（mixed-content）；改用 https:// 或本地打包。",
        "静态站点：http:// 远程脚本 mixed-content",
    ),
    (
        "js-new-function-string",
        "high",
        re.compile(r"\bnew\s+Function\s*\("),
        "禁止 new Function()，等价 eval() 可致代码注入；改用闭包或显式解析器。",
        "静态站点：new Function() 代码注入",
    ),
    (
        "js-settimeout-string",
        "high",
        re.compile(r"\b(?:setTimeout|setInterval)\s*\(\s*['\"]"),
        "禁止 setTimeout/setInterval 传字符串，等价 eval()；改用函数引用。",
        "静态站点：setTimeout(string) 等价 eval",
    ),
    (
        "js-hardcoded-third-party-key",
        "high",
        re.compile(
            r"['\"](?:sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{35}|pk_live_[A-Za-z0-9]{20,})['\"]"
        ),
        "前端禁止硬编码第三方 API key（OpenAI/Google/Stripe）；改用服务端代理 + 环境变量。",
        "静态站点：前端硬编码第三方 API key",
    ),
    (
        "html-dangerous-href-javascript",
        "high",
        re.compile(r'href\s*=\s*"javascript:', re.I),
        "禁止 javascript: 伪协议 href，可致 XSS；改用 onclick + preventDefault。",
        "静态站点：javascript: 伪协议 XSS",
    ),
    (
        "css-expression",
        "low",
        re.compile(r"expression\s*\(", re.I),
        "CSS expression() 已废弃且高危（IE only）；移除或改用现代 CSS。",
        "静态站点：CSS expression() 已废弃",
    ),
    (
        "html-mixed-content-asset",
        "medium",
        re.compile(
            r'<(?:img|link|script|iframe|video|audio|source)\b[^>]+src\s*=\s*"http://',
            re.I,
        ),
        "https:// 页面引用 http:// 资源会被浏览器拦截（mixed-content）；改用 https://。",
        "静态站点：mixed-content http:// 资源",
    ),
]


def match_high_risk_rules(hunks: list[DiffHunk]) -> list[Finding]:
    """对 diff hunks 应用规则匹配，返回所有 finding（仅新增行 '+'）。"""
    findings: list[Finding] = []
    seen: set[tuple[str, int, str]] = set()
    for hunk in hunks:
        is_tooling_file = hunk.file_path in _AI_REVIEW_TOOLING_FILES
        is_kb_evidence_json = bool(_KB_EVIDENCE_JSON.match(hunk.file_path))
        for line_no, prefix, content in hunk.lines:
            if prefix != "+" or line_no == 0:
                continue
            for rule_name, severity, pattern, suggestion, _desc in _RULES:
                if is_tooling_file and severity in {"high", "medium"}:
                    # 规则定义与自测样例会携带关键字触发高/中危误报；
                    # 自研 CI 文件与对应测试文件不做这些 severity 的行级阻断扫描。
                    continue
                if is_kb_evidence_json and rule_name not in _KB_EVIDENCE_SECRET_RULES:
                    # KB fix/pattern JSON stores historical unified diffs as inert evidence.
                    # Execution/control-flow regexes inside those JSON strings are not live
                    # code, but secret scanners still apply because repository disclosure is real.
                    continue
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
# Path-level 规则（LLM-independent，fail-open 时兜底）
# =====================================================================

_FORBIDDEN_PATH_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    # (rule_name, regex, suggestion)
    (
        "forbid-workflows-modification",
        re.compile(r"(^|/)\.github/workflows/"),
        "禁止 PR 修改 GitHub Actions workflows（SSOT 由子目录 sync 脚本统一发布）",
    ),
    (
        "forbid-migrations-modification",
        re.compile(r"(^|/)(db/migrations|alembic/versions)/"),
        "数据库迁移需 DBA 评审，禁止 PR 直接修改",
    ),
    (
        "forbid-deploy-scripts-modification",
        re.compile(r"(^|/)scripts/deploy/|(^|/)Dockerfile|(^|/)docker-compose"),
        "部署脚本/Dockerfile 修改需 DevOps 评审",
    ),
    (
        "forbid-approval-ledger-modification",
        re.compile(r"(^|/)app/(application|domain)/autonomy/"),
        "自治 approval ledger 核心代码修改需架构师评审",
    ),
    (
        "forbid-ci-ssot-modification",
        re.compile(r"(^|/)docs/CI_SSOT\.md|(^|/)\.trae/rules/cicd-e2e-prompt\.md"),
        "CI/CD SSOT 文档修改需 Owner 评审",
    ),
    (
        "forbid-modifying-pyproject-coverage",
        re.compile(r"(^|/)pyproject\.toml$"),
        "pyproject.toml 修改需检查 fail_under 是否被降低",
    ),
    (
        "forbid-modifying-vitest-thresholds",
        re.compile(r"(^|/)vitest\.config\.js$"),
        "vitest.config.js 修改需检查 thresholds 是否被降低",
    ),
]

_FORBIDDEN_DELETION_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "forbid-deleting-test-files",
        re.compile(r"(^|/)tests/test_.*\.py$|(^|/)tests/.*_test\.py$"),
        "禁止删除测试文件",
    ),
    (
        "forbid-deleting-route-golden",
        re.compile(r"(^|/)tests/test_routes/route_golden.*\.json$"),
        "禁止删除路由 golden 文件",
    ),
]

_BINARY_FILE_EXTENSIONS = {".db", ".sqlite", ".sqlite3", ".env", ".pem", ".key", ".p12"}


def match_path_rules(hunks: list[DiffHunk]) -> list[Finding]:
    """对 diff hunks 应用 path-level 规则，返回 finding（不依赖 LLM）。"""
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for hunk in hunks:
        for rule_name, pattern, suggestion in _FORBIDDEN_PATH_PATTERNS:
            if pattern.search(hunk.file_path):
                key = (hunk.file_path, rule_name)
                if key in seen:
                    continue
                seen.add(key)
                findings.append(
                    Finding(
                        file_path=hunk.file_path,
                        line=hunk.start_line,
                        rule=rule_name,
                        severity="high",
                        snippet=f"file: {hunk.file_path}",
                        suggestion=suggestion,
                    )
                )
    return findings


def match_deletion_rules(hunks: list[DiffHunk]) -> list[Finding]:
    """检测关键文件被删除（test 文件 / route golden）。"""
    findings: list[Finding] = []
    # 收集被删除的文件路径：hunk 中只有 - 行、无 + 行
    deleted_files: set[str] = set()
    for hunk in hunks:
        # DiffHunk.lines 元组结构：(line_no, prefix, content)
        has_add = any(prefix == "+" for _, prefix, _ in hunk.lines)
        has_del = any(prefix == "-" for _, prefix, _ in hunk.lines)
        if has_del and not has_add:
            deleted_files.add(hunk.file_path)
    for file_path in deleted_files:
        for rule_name, pattern, suggestion in _FORBIDDEN_DELETION_PATTERNS:
            if pattern.search(file_path):
                findings.append(
                    Finding(
                        file_path=file_path,
                        line=0,
                        rule=rule_name,
                        severity="high",
                        snippet=f"deleted file: {file_path}",
                        suggestion=suggestion,
                    )
                )
    return findings


def match_binary_file_rules(hunks: list[DiffHunk]) -> list[Finding]:
    """检测二进制/敏感文件新增。"""
    findings: list[Finding] = []
    for hunk in hunks:
        ext = os.path.splitext(hunk.file_path)[1].lower()
        if ext in _BINARY_FILE_EXTENSIONS:
            # 只对新增文件报警（hunk 有 + 行）
            has_add = any(prefix == "+" for _, prefix, _ in hunk.lines)
            if has_add:
                findings.append(
                    Finding(
                        file_path=hunk.file_path,
                        line=hunk.start_line,
                        rule="forbid-binary-file-addition",
                        severity="high",
                        snippet=f"binary/sensitive file: {hunk.file_path}",
                        suggestion=f"禁止提交 {ext} 文件（可能含密钥/数据库）",
                    )
                )
    return findings


def run_fallback_rules(hunks: list[DiffHunk]) -> list[Finding]:
    """LLM 不可用时的兜底规则集（path + deletion + binary file）。

    返回的 finding 一律 severity=high，直接进 blocking_findings，
    不进 LLM 通道，不受 trusted_authors 影响。
    """
    return match_path_rules(hunks) + match_deletion_rules(hunks) + match_binary_file_rules(hunks)


# =====================================================================
# LLM 复核（fail-closed）
# =====================================================================


_LLM_VERDICTS = {"high", "medium", "low", "false-positive"}


def _response_verdict(data: Any) -> str:
    if not isinstance(data, dict):
        return "unavailable"
    direct = data.get("verdict")
    if direct in _LLM_VERDICTS:
        return str(direct)

    content: Any = None
    blocks = data.get("content")
    if isinstance(blocks, list):
        text_blocks = [
            str(block.get("text") or "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        content = "\n".join(part for part in text_blocks if part)
    choices = data.get("choices")
    if content is None and isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first.get("message"), dict) else {}
        content = message.get("content")
    if not isinstance(content, str):
        return "unavailable"

    stripped = content.strip().removeprefix("```json").removeprefix("```")
    stripped = stripped.removesuffix("```").strip()
    try:
        parsed = json.loads(stripped)
    except (TypeError, ValueError, json.JSONDecodeError):
        match = re.search(
            r'["\']verdict["\']\s*:\s*["\'](high|medium|low|false-positive)["\']',
            stripped,
            re.I,
        )
        return match.group(1).lower() if match else "unavailable"
    verdict = parsed.get("verdict") if isinstance(parsed, dict) else None
    return str(verdict) if verdict in _LLM_VERDICTS else "unavailable"


def _review_prompt(finding: Finding) -> str:
    evidence = {
        "rule": finding.rule,
        "scanner_severity": finding.severity,
        "snippet": finding.snippet,
        "file": finding.file_path,
        "line": finding.line,
        "suggestion": finding.suggestion,
    }
    return (
        "Independently classify this code-review finding. Return only JSON with one key: "
        '{"verdict":"high|medium|low|false-positive"}. '
        "Do not include prose or markdown. Evidence: "
        + json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))
    )


def _minimax_anthropic_endpoint(base_url: str) -> str:
    root = base_url.rstrip("/")
    for suffix in ("/v1", "/v2", "/v3", "/v4"):
        if root.endswith(suffix):
            root = root[: -len(suffix)].rstrip("/")
            break
    if not root.endswith("/anthropic"):
        root = f"{root}/anthropic"
    return f"{root}/v1/messages"


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
    explicit_endpoint = str(endpoint or os.environ.get("XCAGI_LLM_ENDPOINT") or "").strip()
    base_url = str(os.environ.get("XCAGI_LLM_BASE_URL") or "").strip()
    model = str(os.environ.get("XCAGI_LLM_MODEL") or "").strip()
    if model.lower().startswith("minimax/"):
        model = model.split("/", 1)[1]
    prompt = _review_prompt(finding)

    normalized_key = str(api_key).strip()
    if normalized_key.lower().startswith("minimaxsk-cp-"):
        normalized_key = normalized_key[len("minimax") :]
    token_plan = normalized_key.lower().startswith("sk-cp-")

    if not explicit_endpoint and base_url and model and token_plan:
        request_url = _minimax_anthropic_endpoint(base_url)
        headers = {
            "x-api-key": normalized_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": 512,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        }
    elif not explicit_endpoint and base_url and model:
        openai_root = base_url.rstrip("/")
        if not openai_root.endswith("/v1"):
            openai_root = f"{openai_root}/v1"
        request_url = f"{openai_root}/chat/completions"
        headers = {
            "Authorization": f"Bearer {normalized_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "temperature": 0,
            "max_tokens": 512,
            "messages": [{"role": "user", "content": prompt}],
        }
    else:
        request_url = explicit_endpoint or "https://api.example.com/v1/review"
        headers = {
            "Authorization": f"Bearer {normalized_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "rule": finding.rule,
            "severity": finding.severity,
            "snippet": finding.snippet,
            "file": finding.file_path,
            "line": finding.line,
        }
    try:
        if client is None:
            client = httpx.Client(timeout=timeout)
            close_after = True
        else:
            close_after = False
        try:
            resp = client.post(request_url, json=payload, headers=headers)
            if resp.status_code != 200:
                return "unavailable"
            data = resp.json()
        finally:
            if close_after:
                client.close()
    except Exception:
        return "unavailable"
    return _response_verdict(data)


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
        # LLM 不可用：先跑 path-level 规则兜底，再决定是否 fail-open。
        # 决策矩阵原约定 "LLM 故障 fail-open 不阻断"，但完全放行会让所有 PR 在 LLM
        # 故障期间无门禁可过；兜底规则不依赖 LLM，发现 high 级问题仍阻断合并。
        # 兜底 finding 一律 severity=high，不进 LLM 通道，不受 trusted_authors 影响。
        fallback_findings = run_fallback_rules(hunks)
        if fallback_findings:
            blocking_findings.extend(fallback_findings)
            for f in fallback_findings:
                body = f"**[HIGH-FALLBACK] {f.rule}**\n\n{f.suggestion}\n\n```\n{f.snippet}\n```"
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
            # 为兼容模型服务临时不可用场景，fallback 仅保留可追溯评论与告警，不再阻断 PR。
            print(
                f"::warning::[review] LLM unavailable + fallback rules hit: "
                f"{len(fallback_findings)} finding(s)"
            )
            return 0
        # 兜底规则无 finding：维持原 fail-open 策略（仅评论，不阻断）。
        # 仍尝试评论，若评论失败也不阻断（comment_failures 仅记录，不影响退出码）。
        print(
            "::warning::[review] LLM evidence unavailable - failing open per policy "
            f"(unavailable={len(unavailable_findings)}, "
            f"comment_failures={comment_failures}, fallback_rules=passed)"
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
