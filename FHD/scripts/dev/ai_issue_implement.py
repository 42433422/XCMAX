"""AI Issue Implement — 决策矩阵承诺兑现脚本。

约束（来自 .trae/rules/cicd-e2e-prompt.md）：
  - owner 评论「确认」才执行
  - 预估变更 >5 文件拒做
  - 实现后创建 PR 标 `needs-human` 待人工合并

使用方式（本地 dry-run）:
    python scripts/dev/ai_issue_implement.py \\
        --issue-number 123 \\
        --repo owner/repo \\
        --token $GITHUB_TOKEN \\
        --dry-run

CI 中（实际执行）:
    python scripts/dev/ai_issue_implement.py \\
        --issue-number "$ISSUE_NUMBER" \\
        --repo "$GITHUB_REPOSITORY" \\
        --token "$GITHUB_TOKEN" \\
        --llm-api-key "${XCAGI_LLM_API_KEY:-}" \\
        --apply

退出码:
  0  成功（已创建 PR 或 dry-run 通过）
  2  owner 未确认（等待 confirmation）
  3  拒做（预估 >5 文件）
  4  issue 不存在或无 ai-implement 标签
  5  LLM 不可用，无法实现
  6  分支创建/提交/PR 失败
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPORT_DIR = Path(__file__).resolve().parents[2] / "test_reports"
MAX_CHANGED_FILES = 5  # 决策矩阵硬阈值
BRANCH_PREFIX = "ai-impl"
CONFIRM_KEYWORDS = ("确认", "confirm", "approved", "approve", "+1", "OK", "go")


@dataclass
class ImplementResult:
    """实现结果，写入 test_reports/ai_issue_implement_<n>.json"""

    issue_number: int
    repo: str
    started_at: str
    finished_at: str = ""
    ok: bool = False
    status: str = "init"  # init | waiting_confirmation | rejected_too_large | no_label | llm_unavailable | pr_created | dry_run | failed
    reason: str = ""
    issue_title: str = ""
    issue_url: str = ""
    owner_confirmed: bool = False
    estimated_files: int = 0
    changed_files: list[str] = field(default_factory=list)
    branch: str = ""
    pr_url: str = ""
    pr_number: int = 0
    llm_used: bool = False
    duration_ms: int = 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_report(result: ImplementResult) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"ai_issue_implement_{result.issue_number}.json"
    path.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


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
    return any(str(lb.get("name") or "").strip() == "ai-implement" for lb in labels if isinstance(lb, dict))


def _owner_confirmed(issue: dict[str, Any], comments: list[dict[str, Any]], repo: str) -> tuple[bool, str]:
    """决策矩阵要求：owner 评论「确认」才执行。

    判定：
      - issue author 视为 owner
      - author 自己在评论中写「确认」/「confirm」/「approved」/「+1」/「OK」/「go」
      - 不区分大小写
    """
    author = (issue.get("user") or {}).get("login") or ""
    if not author:
        return False, "issue.author 未解析到"
    for c in comments:
        cauthor = (c.get("user") or {}).get("login") or ""
        if cauthor != author:
            continue
        body = str(c.get("body") or "").strip().lower()
        if any(kw.lower() in body for kw in CONFIRM_KEYWORDS):
            return True, f"owner @{author} 已在评论中确认"
    # issue 本身 body 含确认也算
    body = str(issue.get("body") or "").strip().lower()
    if any(kw in body for kw in CONFIRM_KEYWORDS):
        return True, f"owner @{author} 在 issue body 中确认"
    return False, f"owner @{author} 未在评论中确认（关键词：{CONFIRM_KEYWORDS}）"


def _estimate_files(issue_title: str, issue_body: str) -> int:
    """根据 issue 内容粗估变更文件数。

    估算规则（保守偏严）：
      - issue 提及 N 个明确文件路径 → 计入 N
      - 提及 "新增"/"add" + 模块名 → 计 2（模块 + manifest）
      - 提及 "测试"/"test" → 计 1
      - 最低 1，最高 99（>5 时拒做）
    """
    text = f"{issue_title}\n{issue_body}"
    # 明确文件路径
    paths = re.findall(r"`?([a-zA-Z0-9_./-]+\.(?:py|ts|vue|js|json|md|yml|yaml))`?", text)
    explicit = set(p for p in paths if "/" in p or p.startswith(("FHD", "app", "src", "tests")))
    count = len(explicit)
    if re.search(r"新增|新建|add new|create new|scaffold", text, re.IGNORECASE):
        count += 2
    if re.search(r"测试|test|spec", text, re.IGNORECASE):
        count += 1
    return max(1, count)


def _call_llm(prompt: str, api_key: str) -> dict[str, Any]:
    """调用 LLM 生成实现建议。使用与项目一致的 DeepSeek/兼容客户端。

    失败时返回 ok=False；上层据此跳过自动实现，避免误操作。
    """
    if not api_key:
        return {"ok": False, "error": "LLM_API_KEY 未配置"}
    base = os.environ.get("XCAGI_LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    model = os.environ.get("XCAGI_LLM_MODEL", "deepseek-chat")
    import urllib.request

    body = json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是 XCMAX 项目的代码实现助手。"
                        "根据 issue 输出最小可行的文件变更清单："
                        "返回 JSON 对象 {\"files\": [{\"path\": \"...\", \"action\": \"create|modify\", "
                        "\"content_summary\": \"...\", \"rationale\": \"...\"}], "
                        "\"estimated_files\": N, \"cannot_automate\": bool, \"reason\": \"...\"}。"
                        "禁止生成超过 5 个文件；禁止触碰 _local_secrets/、payment_*.py、.env。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 2000,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        # 容错：模型可能返回带 markdown 包裹的 JSON
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            return {"ok": False, "error": "LLM 响应未包含 JSON"}
        plan = json.loads(m.group(0))
        plan["ok"] = True
        return plan
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"LLM 调用失败：{exc}"}


def _git(*args: str, cwd: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=check, capture_output=True, text=True
    )


def _create_branch(base: str, issue_number: int) -> str:
    branch = f"{BRANCH_PREFIX}/{issue_number}-{int(time.time())}"
    _git("checkout", "-b", branch, cwd=base)
    return branch


def _apply_files(base: Path, files: list[dict[str, Any]]) -> list[str]:
    """应用 LLM 生成的文件清单到磁盘。

    本实现仅做「create」类型的安全写入；「modify」类型需人工 review，不自动应用。
    返回实际写入的文件路径列表。
    """
    written: list[str] = []
    for f in files or []:
        action = str(f.get("action") or "").strip().lower()
        rel = str(f.get("path") or "").strip()
        if not rel or action != "create":
            continue
        # 安全闸：禁止路径穿越与敏感文件
        if ".." in rel or rel.startswith("/"):
            continue
        if any(seg in rel for seg in ("_local_secrets", ".env", "payment_", "secrets")):
            continue
        content = str(f.get("content") or f.get("content_summary") or "")
        if not content:
            continue
        dest = (base / rel).resolve()
        try:
            dest.relative_to(base.resolve())
        except ValueError:
            continue
        if dest.exists():
            continue  # create 不覆盖
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        written.append(rel)
    return written


def _commit_and_pr(
    base: Path,
    branch: str,
    issue_number: int,
    issue_title: str,
    files: list[str],
    repo: str,
    token: str,
) -> tuple[str, int]:
    _git("add", *files, cwd=str(base))
    _git(
        "commit",
        "-m",
        f"ai(issue #{issue_number}): {issue_title[:60]}\n\n"
        f"Generated by ai-issue-implement workflow.\n"
        f"Ref: #{issue_number}\n\n"
        f"Files: {len(files)}",
        cwd=str(base),
    )
    _git("push", "origin", branch, cwd=str(base))
    pr_body = (
        f"## 关联 issue\n\nCloses #{issue_number}\n\n"
        f"## 变更文件 ({len(files)})\n\n" + "\n".join(f"- `{f}`" for f in files) + "\n\n"
        f"## 审核\n\n"
        f"- [ ] 业务语义正确\n"
        f"- [ ] 测试已补\n"
        f"- [ ] 安全/敏感信息无泄漏\n\n"
        f"_本 PR 由 ai-issue-implement workflow 生成，标 `needs-human` 待人工合并。_"
    )
    pr = _gh_post(
        f"https://api.github.com/repos/{repo}/pulls",
        token,
        {
            "title": f"ai(issue #{issue_number}): {issue_title[:60]}",
            "head": branch,
            "base": "main",
            "body": pr_body,
        },
    )
    pr_url = pr.get("html_url") or ""
    pr_number = int(pr.get("number") or 0)
    # 打 needs-human 标签
    if pr_number:
        _gh_post(
            f"https://api.github.com/repos/{repo}/issues/{pr_number}/labels",
            token,
            {"labels": ["needs-human", "ai-generated"]},
        )
    return pr_url, pr_number


def run(args: argparse.Namespace) -> ImplementResult:
    started = _utc_now()
    start_ts = time.time()
    repo = args.repo
    issue_number = int(args.issue_number)
    result = ImplementResult(
        issue_number=issue_number,
        repo=repo,
        started_at=started,
    )

    try:
        issue = _fetch_issue(repo, issue_number, args.token)
    except Exception as exc:  # noqa: BLE001
        result.status = "failed"
        result.reason = f"获取 issue 失败：{exc}"
        result.finished_at = _utc_now()
        result.duration_ms = int((time.time() - start_ts) * 1000)
        _write_report(result)
        logger.error(result.reason)
        sys.exit(6)

    result.issue_title = str(issue.get("title") or "")
    result.issue_url = str(issue.get("html_url") or "")

    if not _has_aimplement_label(issue):
        result.status = "no_label"
        result.reason = f"issue #{issue_number} 无 ai-implement 标签"
        result.finished_at = _utc_now()
        result.duration_ms = int((time.time() - start_ts) * 1000)
        _write_report(result)
        logger.warning(result.reason)
        sys.exit(4)

    try:
        comments = _fetch_issue_comments(repo, issue_number, args.token)
    except Exception as exc:  # noqa: BLE001
        comments = []
        logger.warning("fetch comments failed: %s", exc)

    confirmed, confirm_reason = _owner_confirmed(issue, comments, repo)
    result.owner_confirmed = confirmed
    if not confirmed:
        result.status = "waiting_confirmation"
        result.reason = confirm_reason
        result.finished_at = _utc_now()
        result.duration_ms = int((time.time() - start_ts) * 1000)
        _write_report(result)
        logger.warning(result.reason)
        # 在 issue 上评论提示 owner 需确认
        _gh_post(
            f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments",
            args.token,
            {
                "body": (
                    "🤖 `ai-issue-implement` 已收到 `ai-implement` 标签。\n\n"
                    "等待 owner 在本 issue 评论「确认」/「confirm」/「approved」后开始执行。\n\n"
                    "约束：预估变更 >5 文件时将自动拒做。"
                )
            },
        )
        sys.exit(2)

    body = str(issue.get("body") or "")
    est = _estimate_files(result.issue_title, body)
    result.estimated_files = est
    if est > MAX_CHANGED_FILES:
        result.status = "rejected_too_large"
        result.reason = f"预估变更 {est} 文件 > 阈值 {MAX_CHANGED_FILES}；拒做"
        result.finished_at = _utc_now()
        result.duration_ms = int((time.time() - start_ts) * 1000)
        _write_report(result)
        logger.warning(result.reason)
        _gh_post(
            f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments",
            args.token,
            {"body": f"🚫 {result.reason}\n\n请将 issue 拆分为多个 ≤5 文件的子 issue。"},
        )
        sys.exit(3)

    # 调 LLM 生成实现计划
    prompt = (
        f"项目：XCMAX（Python FastAPI + Vue 3 + Electron）\n"
        f"Issue #{issue_number}: {result.issue_title}\n\n"
        f"{body[:4000]}\n\n"
        f"输出最小可行实现（≤{MAX_CHANGED_FILES} 文件）。"
    )
    plan = _call_llm(prompt, args.llm_api_key)
    if not plan.get("ok"):
        result.status = "llm_unavailable"
        result.reason = str(plan.get("error") or "LLM 不可用")
        result.finished_at = _utc_now()
        result.duration_ms = int((time.time() - start_ts) * 1000)
        _write_report(result)
        logger.error(result.reason)
        sys.exit(5)

    result.llm_used = True
    files = plan.get("files") or []
    result.changed_files = [str(f.get("path") or "") for f in files if f.get("path")]

    if args.dry_run:
        result.status = "dry_run"
        result.ok = True
        result.reason = "dry-run 模式：未应用变更、未创建 PR"
        result.finished_at = _utc_now()
        result.duration_ms = int((time.time() - start_ts) * 1000)
        _write_report(result)
        logger.info("dry-run ok: %s", result.changed_files)
        sys.exit(0)

    # 实际执行：创建分支、写文件、提 PR
    repo_root = Path(__file__).resolve().parents[3]
    base_dir = repo_root / "FHD"
    try:
        branch = _create_branch(str(repo_root), issue_number)
        result.branch = branch
        written = _apply_files(base_dir, files)
        result.changed_files = written
        if not written:
            result.status = "failed"
            result.reason = "无文件被实际写入（可能全是 modify 类型，需人工）"
            _git("checkout", "main", cwd=str(repo_root))
            _git("branch", "-D", branch, cwd=str(repo_root))
            result.finished_at = _utc_now()
            result.duration_ms = int((time.time() - start_ts) * 1000)
            _write_report(result)
            sys.exit(6)
        pr_url, pr_num = _commit_and_pr(
            base_dir, branch, issue_number, result.issue_title, written, repo, args.token
        )
        result.pr_url = pr_url
        result.pr_number = pr_num
        result.status = "pr_created"
        result.ok = True
        result.reason = f"PR #{pr_num} 已创建，标 needs-human 待人工合并"
        _gh_post(
            f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments",
            args.token,
            {"body": f"✅ 已创建 PR #{pr_num}: {pr_url}\n\n待人工 review 后合并。"},
        )
    except subprocess.CalledProcessError as exc:
        result.status = "failed"
        result.reason = f"git 操作失败：{exc.stderr or exc.stdout}"
        logger.exception("git failed")
    except Exception as exc:  # noqa: BLE001
        result.status = "failed"
        result.reason = f"实现异常：{exc}"
        logger.exception("implement failed")

    result.finished_at = _utc_now()
    result.duration_ms = int((time.time() - start_ts) * 1000)
    _write_report(result)
    sys.exit(0 if result.ok else 6)


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Issue Implement")
    parser.add_argument("--issue-number", required=True, help="GitHub issue 编号")
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--llm-api-key", default=os.environ.get("XCAGI_LLM_API_KEY", ""))
    parser.add_argument("--dry-run", action="store_true", help="不实际写文件、不创建 PR")
    parser.add_argument("--apply", action="store_true", help="实际写文件并创建 PR")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(args)


if __name__ == "__main__":
    main()
