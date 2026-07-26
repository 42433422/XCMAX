"""AI self-heal PR SLA 处理：auto-merge / stale 提醒 / 关闭。

扫描 open PR，覆盖三类来源：
- label:ai-self-heal — ai-self-heal workflow 自动修复 PR
- label:ai-generated — ai-issue-implement workflow 自动实现 PR
- 普通 PR（--scan-regular-prs 启用）：无上述 label 的 PR

按 risk:* 标签分流处理：
- r0：≥ 12h（ai-self-heal）/ ≥ 12h（ai-generated）且二次守卫通过 → auto-merge
- r1：≥ 48h 且二次守卫通过 → auto-merge
- r2：≥ 7d stale 评论，≥ 14d 自动关闭（最终策略：维持人工合并，永不 auto-merge）
- r3：≥ 7d stale 评论，≥ 30d 自动关闭（最终策略：维持人工合并，永不 auto-merge）
- 说明：r2/r3 人工合并是正式策略而非临时缺口；若要对子集全自动须另设白名单，不得默认放开

二次守卫（r0/r1 auto-merge 前置）：
1. CI 全绿
2. PR 体量
   - ai-self-heal: ≤ 3 文件 + ≤ 50 diff 行（严格，机械修复）
   - ai-generated: ≤ 5 文件 + ≤ 100 diff 行（仅显式 r0/r1 候选可进入）
3. 文件类型
   - ai-self-heal: 仅 .py / .md
   - ai-generated: .py / .md / .ts / .vue / .js / .json / .yaml / .yml
4. 禁止修改 db/migrations、fastapi_app、deploy 脚本、workflows
5. 不是 autonomy/ 分支（不递归）

普通 PR 三重门禁（--scan-regular-prs，2026-07-20 新增）：
1. ai-review: passed — "AI Review" workflow 在 PR head SHA 上 conclusion=success
   （兼容：若 PR 标 `ai-review: passed` label 则直接视为通过）
2. ci: passed — PR head SHA 所有 check runs 全绿（success/neutral/skipped）
3. author: trusted-author-allowlist — PR author ∈ config/auto-implement-allowlist.yaml:trusted_authors

Veto（任一PR类型）：PR 标 `hold-merge` label 时不自动合并。

合并失败处理（2026-07-25）：
- 合并前先查 mergeable；冲突 / 403 / 其它 HTTP 错误分开文案，不再笼统写「权限不足」
- 失败评论按 `❌ 自动合并失败` 去重，避免 schedule 每 30 分钟刷屏
- 冲突时自动打 `needs-human` + `hold-merge`

严格分支保护恢复（2026-07-26）：
- mergeable=true 但 mergeable_state=behind 时，调用 GitHub update-branch API
- 更新后停止本轮合并，等待新 head SHA 的 AI Review + CI 全量重跑
- expected_head_sha 防止并发覆盖；更新失败 fail closed，不绕过 required checks
- update-branch 必须使用独立 `BRANCH_UPDATE_TOKEN`，避免 `GITHUB_TOKEN`
  触发的 PR 更新进入需要人工批准的 workflow 状态

合并后发布闭环（2026-07-26）：
- `GITHUB_TOKEN` 合并不会触发普通 `push` workflow；合并成功后必须显式
  workflow_dispatch FHD CI/CD 与 MODstore 主干 CI
- 任一派发失败都记为 `post_merge_dispatch_failed`、标记 `needs-human`，
  并让本次 SLA workflow 失败，禁止把“已合并”冒充“已发布”

全部动作写 metrics/ai-self-heal-stale.jsonl。

环境变量：
  GITHUB_TOKEN    必填
  GITHUB_REPOSITORY  必填（如 "owner/repo"）
  BRANCH_UPDATE_TOKEN  behind PR 更新专用 token（CI 使用 CI_COMMIT_TOKEN）
  AUTO_IMPLEMENT_ALLOWLIST_PATH  可选，覆盖 allowlist 路径（默认 <repo_root>/config/auto-implement-allowlist.yaml）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]


GITHUB_API = "https://api.github.com"
ROOT = Path(__file__).resolve().parents[2]
METRICS_DIR = ROOT / "metrics"
STALE_JSONL = METRICS_DIR / "ai-self-heal-stale.jsonl"

# allowlist 文件默认路径：<repo_root>/config/auto-implement-allowlist.yaml
REPO_ROOT = ROOT.parent
DEFAULT_ALLOWLIST_PATH = REPO_ROOT / "config" / "auto-implement-allowlist.yaml"

# ai-review workflow 名称（与 FHD/.github/workflows/ai-review.yml `name:` 字段对齐）
AI_REVIEW_WORKFLOW_NAME = "AI Review"
AI_REVIEW_PASSED_LABEL = "ai-review: passed"
HOLD_MERGE_LABEL = "hold-merge"
NEEDS_HUMAN_LABEL = "needs-human"
# 合并失败评论去重标记（勿改文案前缀，否则会再次刷屏）
MERGE_FAIL_COMMENT_MARKER = "❌ 自动合并失败"
POST_MERGE_DISPATCH_FAIL_MARKER = "❌ 自动合并后发布派发失败"

POST_MERGE_WORKFLOWS: tuple[tuple[str, dict[str, str]], ...] = (
    (
        "fhd-ci-cd.yml",
        {
            "release_channel": "stable",
            "push_to_cvm": "true",
            "push_image_tar": "false",
        },
    ),
    ("modstore-ci-backend-python.yml", {}),
)

# ai-self-heal / ai-generated 标签（用于区分普通 PR）
AI_PR_LABELS = ("ai-self-heal", "ai-generated")

# 最终策略：r2/r3 永不进入 auto-merge 分支（仅 stale→close / 人工）
MANUAL_MERGE_RISK_LEVELS = frozenset({"r2", "r3"})
AUTO_MERGE_RISK_LEVELS = frozenset({"r0", "r1"})


# =====================================================================
# 数据模型
# =====================================================================


@dataclass
class PRInfo:
    """GitHub PR 摘要。"""

    number: int
    title: str
    url: str
    head_branch: str
    created_at: float  # UNIX 秒
    labels: list[str]
    changed_files: int = 0
    additions: int = 0
    deletions: int = 0
    kind: str = "self_heal"  # "self_heal" | "ai_generated" | "regular"
    author: str = ""
    head_sha: str = ""


# =====================================================================
# GitHub API 客户端
# =====================================================================


class GitHubClient:
    def __init__(self, repo: str, token: str):
        self.repo = repo
        self.token = token
        if httpx is None:
            raise RuntimeError("httpx 未安装：pip install httpx")
        self.client = httpx.Client(
            timeout=30.0,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
        )
        branch_update_token = (os.environ.get("BRANCH_UPDATE_TOKEN") or "").strip()
        self.branch_update_client = (
            httpx.Client(
                timeout=30.0,
                headers={
                    "Authorization": f"Bearer {branch_update_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            if branch_update_token
            else None
        )

    def list_self_heal_prs(self) -> list[PRInfo]:
        """列出所有 open PR + label:ai-self-heal 或 label:ai-generated。

        GitHub Issues API 的 labels 参数是 AND 关系，因此分两次查询再合并去重。
        返回的 PRInfo.kind 标记来源（self_heal / ai_generated）。
        """
        seen: set[int] = set()
        prs: list[PRInfo] = []
        for label, kind in (("ai-self-heal", "self_heal"), ("ai-generated", "ai_generated")):
            url = f"{GITHUB_API}/repos/{self.repo}/issues"
            resp = self.client.get(url, params={"labels": label, "state": "open", "per_page": 100})
            resp.raise_for_status()
            for item in resp.json():
                if "pull_request" not in item:
                    continue
                pr_number = item.get("number")
                if pr_number in seen:
                    continue
                pr_url = item["pull_request"]["url"]
                pr_resp = self.client.get(pr_url)
                pr_resp.raise_for_status()
                pr_data = pr_resp.json()
                prs.append(
                    PRInfo(
                        number=pr_data["number"],
                        title=pr_data["title"],
                        url=pr_data["html_url"],
                        head_branch=pr_data["head"]["ref"],
                        created_at=_parse_iso(pr_data["created_at"]),
                        labels=[lab["name"] for lab in pr_data.get("labels", [])],
                        changed_files=pr_data.get("changed_files", 0),
                        additions=pr_data.get("additions", 0),
                        deletions=pr_data.get("deletions", 0),
                        kind=kind,
                        author=_extract_login(pr_data.get("user")),
                        head_sha=pr_data.get("head", {}).get("sha", "") or "",
                    )
                )
                seen.add(pr_number)
        return prs

    def list_regular_prs(self) -> list[PRInfo]:
        """列出所有 open PR，排除带 ai-self-heal / ai-generated label 的 PR。

        普通 PR 由本函数专门处理，不走 risk 分级；走三重门禁。
        """
        url = f"{GITHUB_API}/repos/{self.repo}/pulls"
        prs: list[PRInfo] = []
        page = 1
        while True:
            resp = self.client.get(
                url,
                params={
                    "state": "open",
                    "per_page": 100,
                    "page": page,
                    "sort": "created",
                    "direction": "desc",
                },
            )
            resp.raise_for_status()
            items = resp.json()
            if not items:
                break
            for pr_data in items:
                labels = [lab["name"] for lab in pr_data.get("labels", [])]
                # 排除 ai-self-heal / ai-generated PR（由 list_self_heal_prs 处理）
                if any(lab in AI_PR_LABELS for lab in labels):
                    continue
                prs.append(
                    PRInfo(
                        number=pr_data["number"],
                        title=pr_data["title"],
                        url=pr_data["html_url"],
                        head_branch=pr_data["head"]["ref"],
                        created_at=_parse_iso(pr_data["created_at"]),
                        labels=labels,
                        changed_files=pr_data.get("changed_files", 0),
                        additions=pr_data.get("additions", 0),
                        deletions=pr_data.get("deletions", 0),
                        kind="regular",
                        author=_extract_login(pr_data.get("user")),
                        head_sha=pr_data.get("head", {}).get("sha", "") or "",
                    )
                )
            if len(items) < 100:
                break
            page += 1
            # 安全上限：避免极端情况下无限翻页
            if page > 10:
                break
        return prs

    def get_workflow_run_conclusion(self, head_sha: str, workflow_name: str) -> tuple[bool, str]:
        """检查指定 head SHA 上某 workflow 的最近一次 run 是否 conclusion=success。

        GitHub Actions API：list workflow runs by head_sha 过滤 name 字段。
        返回 (passed, reason)。
        """
        if not head_sha:
            return False, "no_head_sha"
        url = f"{GITHUB_API}/repos/{self.repo}/actions/runs"
        resp = self.client.get(url, params={"head_sha": head_sha, "per_page": 100})
        if resp.status_code != 200:
            return False, f"workflow_runs_api_error_{resp.status_code}"
        runs = resp.json().get("workflow_runs", []) or []
        matched = [r for r in runs if r.get("name") == workflow_name]
        if not matched:
            return False, f"no_workflow_run:{workflow_name}"
        # 取最新一条（GitHub 默认按 created_at desc 返回，但显式排序更稳）
        latest = max(matched, key=lambda r: r.get("created_at", ""))
        status = latest.get("status", "")
        conclusion = latest.get("conclusion")
        if status != "completed":
            return False, f"workflow_not_completed:{workflow_name}:{status}"
        if conclusion != "success":
            return False, f"workflow_failed:{workflow_name}:{conclusion}"
        return True, "ok"

    def get_pr_files(self, pr_number: int) -> list[str]:
        url = f"{GITHUB_API}/repos/{self.repo}/pulls/{pr_number}/files"
        resp = self.client.get(url)
        resp.raise_for_status()
        return [f["filename"] for f in resp.json()]

    def get_pr_check_runs(self, pr_number: int, head_sha: str) -> tuple[bool, str]:
        """检查 PR head commit 的所有 check runs 是否全绿。"""
        url = f"{GITHUB_API}/repos/{self.repo}/commits/{head_sha}/check-runs"
        resp = self.client.get(url)
        if resp.status_code != 200:
            return False, f"check_runs_api_error_{resp.status_code}"
        runs = resp.json().get("check_runs", [])
        if not runs:
            return False, "no_check_runs"
        for run in runs:
            if run.get("conclusion") not in ("success", "neutral", "skipped"):
                return False, f"ci_not_green:{run.get('name')}"
        return True, "ok"

    def get_pr_head_sha(self, pr_number: int) -> str:
        url = f"{GITHUB_API}/repos/{self.repo}/pulls/{pr_number}"
        resp = self.client.get(url)
        resp.raise_for_status()
        return resp.json()["head"]["sha"]

    def get_pr_mergeability(self, pr_number: int) -> tuple[bool | None, str]:
        """查询 PR 是否可合并。

        返回 (mergeable, reason)：
        - (True, "ok")：可合并
        - (True, "behind")：无冲突但落后主干，应先 update-branch 并重跑检查
        - (False, "conflict")：有冲突
        - (None, "unknown")：GitHub 仍在计算 / API 异常，调用方应跳过本轮
        """
        url = f"{GITHUB_API}/repos/{self.repo}/pulls/{pr_number}"
        resp = self.client.get(url)
        if resp.status_code != 200:
            return None, f"mergeability_api_error_{resp.status_code}"
        data = resp.json()
        mergeable = data.get("mergeable")
        if mergeable is True:
            if str(data.get("mergeable_state") or "").lower() == "behind":
                return True, "behind"
            return True, "ok"
        if mergeable is False:
            return False, "conflict"
        return None, "unknown"

    def update_pr_branch(self, pr_number: int, expected_head_sha: str) -> tuple[bool, str]:
        """让 GitHub 把 base 合入 PR 分支；不绕过保护规则。

        expected_head_sha 是并发守卫：PR head 已变化时 GitHub 会拒绝本次更新，
        治理器下一轮重新读取新 head 后再评估。
        """
        if self.branch_update_client is None:
            return False, "branch_update_token_missing"
        url = f"{GITHUB_API}/repos/{self.repo}/pulls/{pr_number}/update-branch"
        resp = self.branch_update_client.put(url, json={"expected_head_sha": expected_head_sha})
        if resp.status_code == 202:
            return True, "ok"
        try:
            message = str((resp.json() or {}).get("message") or "")
        except Exception:
            message = (resp.text or "")[:200]
        lowered = message.lower()
        if resp.status_code == 409 or "conflict" in lowered:
            return False, "conflict"
        if (
            resp.status_code == 403
            or "resource not accessible" in lowered
            or "permission" in lowered
        ):
            return False, "permission"
        detail = message.replace("\n", " ").strip() or "no_message"
        return False, f"http_{resp.status_code}:{detail[:160]}"

    def merge_pr(self, pr_number: int, method: str = "squash") -> tuple[bool, str, str]:
        """尝试 squash/merge。返回 (ok, reason, merge_sha)。

        reason 取值：ok / conflict / permission / http_<code>:<message>
        """
        url = f"{GITHUB_API}/repos/{self.repo}/pulls/{pr_number}/merge"
        resp = self.client.put(url, json={"merge_method": method})
        if resp.status_code == 200:
            try:
                merge_sha = str((resp.json() or {}).get("sha") or "").strip()
            except Exception:
                merge_sha = ""
            if len(merge_sha) != 40 or any(ch not in "0123456789abcdef" for ch in merge_sha):
                return True, "ok_missing_merge_sha", ""
            return True, "ok", merge_sha
        message = ""
        try:
            message = str((resp.json() or {}).get("message") or "")
        except Exception:
            message = (resp.text or "")[:200]
        lowered = message.lower()
        if resp.status_code in (405, 409) or "conflict" in lowered:
            return False, "conflict", ""
        if (
            resp.status_code == 403
            or "resource not accessible" in lowered
            or "permission" in lowered
        ):
            return False, "permission", ""
        detail = message.replace("\n", " ").strip() or "no_message"
        return False, f"http_{resp.status_code}:{detail[:160]}", ""

    def dispatch_workflow(
        self,
        workflow_file: str,
        *,
        ref: str = "main",
        inputs: dict[str, str] | None = None,
    ) -> tuple[bool, str]:
        """显式派发 workflow_dispatch，绕过 GITHUB_TOKEN push 事件抑制。"""

        url = f"{GITHUB_API}/repos/{self.repo}/actions/workflows/{workflow_file}/dispatches"
        payload: dict[str, Any] = {"ref": ref}
        if inputs:
            payload["inputs"] = inputs
        resp = self.client.post(url, json=payload)
        if resp.status_code == 204:
            return True, "ok"
        try:
            message = str((resp.json() or {}).get("message") or "")
        except Exception:
            message = (resp.text or "")[:200]
        detail = message.replace("\n", " ").strip() or "no_message"
        return False, f"http_{resp.status_code}:{detail[:160]}"

    def has_issue_comment_containing(self, pr_number: int, needle: str) -> bool:
        """是否已有包含 needle 的 issue/PR 评论（用于合并失败评论去重）。"""
        if not needle:
            return False
        url = f"{GITHUB_API}/repos/{self.repo}/issues/{pr_number}/comments"
        page = 1
        while page <= 5:
            resp = self.client.get(url, params={"per_page": 100, "page": page})
            if resp.status_code != 200:
                return False
            items = resp.json() or []
            if not items:
                break
            for item in items:
                body = str(item.get("body") or "")
                if needle in body:
                    return True
            if len(items) < 100:
                break
            page += 1
        return False

    def close_pr(self, pr_number: int) -> bool:
        url = f"{GITHUB_API}/repos/{self.repo}/pulls/{pr_number}"
        resp = self.client.patch(url, json={"state": "closed"})
        return resp.status_code == 200

    def comment(self, pr_number: int, body: str) -> bool:
        url = f"{GITHUB_API}/repos/{self.repo}/issues/{pr_number}/comments"
        resp = self.client.post(url, json={"body": body})
        return resp.status_code in (200, 201)

    def add_labels(self, pr_number: int, labels: list[str]) -> bool:
        url = f"{GITHUB_API}/repos/{self.repo}/issues/{pr_number}/labels"
        resp = self.client.post(url, json={"labels": labels})
        return resp.status_code in (200, 201)

    def remove_label(self, pr_number: int, label: str) -> bool:
        url = f"{GITHUB_API}/repos/{self.repo}/issues/{pr_number}/labels/{label}"
        resp = self.client.delete(url)
        return resp.status_code in (200, 204)


def _parse_iso(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def _extract_login(user: Any) -> str:
    """从 GitHub API user 字段提取 login（兼容 None / 缺字段）。"""
    if not isinstance(user, dict):
        return ""
    return str(user.get("login") or "")


def _merge_failure_comment(reason: str) -> str:
    """按失败原因生成准确评论（避免把冲突误报成权限不足）。"""
    if reason == "conflict":
        return (
            f"{MERGE_FAIL_COMMENT_MARKER}：PR 存在合并冲突（非权限问题）。"
            f"请 rebase/解决冲突后去掉 `{NEEDS_HUMAN_LABEL}` 再重试。"
        )
    if reason == "permission":
        return (
            f"{MERGE_FAIL_COMMENT_MARKER}：GitHub token 权限不足（403）。"
            "请检查 Actions `contents: write` / branch protection / fine-grained token 权限。"
        )
    if reason == "unknown":
        return f"{MERGE_FAIL_COMMENT_MARKER}：GitHub 尚未算出 mergeable 状态，本轮跳过。"
    return f"{MERGE_FAIL_COMMENT_MARKER}：{reason}，请人工处理。"


def _notify_merge_failure_once(
    client: GitHubClient,
    pr: PRInfo,
    reason: str,
    *,
    extra_labels: list[str] | None = None,
) -> None:
    """合并失败时：准确评论（去重）+ 打 needs-human，避免每 30 分钟刷屏。"""
    body = _merge_failure_comment(reason)
    already = False
    try:
        already = client.has_issue_comment_containing(pr.number, MERGE_FAIL_COMMENT_MARKER)
    except Exception as ex:  # noqa: BLE001 — 去重失败不应阻断打标
        print(f"  warn: comment dedup check failed: {ex}")
    if already:
        print(f"  skip comment: already notified merge failure on #{pr.number}")
    else:
        client.comment(pr.number, body)
    labels = [NEEDS_HUMAN_LABEL]
    if extra_labels:
        labels.extend(extra_labels)
    # 冲突时额外 hold，防止门禁仍绿却反复尝试 merge
    if reason == "conflict" and HOLD_MERGE_LABEL not in labels:
        labels.append(HOLD_MERGE_LABEL)
    client.add_labels(pr.number, labels)


def _try_auto_merge(
    client: GitHubClient,
    pr: PRInfo,
    *,
    success_comment: str,
    success_action: str,
    failure_action: str,
    metric_extra: dict[str, Any] | None = None,
) -> str:
    """统一 auto-merge 路径：先查 mergeable/behind，再 merge。

    返回 auto_merged / branch_updated / post_merge_dispatch_failed /
    merge_failed / skipped。
    """
    mergeable, mreason = client.get_pr_mergeability(pr.number)
    if mergeable is None:
        print(f"  skip: mergeable 未知 ({mreason})")
        _append_stale(
            {
                "pr": pr.number,
                "kind": pr.kind,
                "author": pr.author,
                "action": "mergeability_unknown",
                "reason": mreason,
                **(metric_extra or {}),
            }
        )
        return "skipped"
    if mergeable is False:
        print(f"  merge blocked: {mreason}")
        _notify_merge_failure_once(client, pr, mreason)
        _append_stale(
            {
                "pr": pr.number,
                "kind": pr.kind,
                "author": pr.author,
                "action": failure_action,
                "reason": mreason,
                **(metric_extra or {}),
            }
        )
        return "merge_failed"

    if mreason == "behind":
        expected_head_sha = pr.head_sha or client.get_pr_head_sha(pr.number)
        if not expected_head_sha:
            print("  skip: behind 但缺少 expected_head_sha")
            _append_stale(
                {
                    "pr": pr.number,
                    "kind": pr.kind,
                    "author": pr.author,
                    "action": "branch_update_failed",
                    "reason": "missing_head_sha",
                    **(metric_extra or {}),
                }
            )
            return "skipped"
        updated, update_reason = client.update_pr_branch(pr.number, expected_head_sha)
        if updated:
            print(
                f"  branch update requested: head={expected_head_sha}; "
                "等待新 head 的 AI Review + CI"
            )
            _append_stale(
                {
                    "pr": pr.number,
                    "kind": pr.kind,
                    "author": pr.author,
                    "action": "branch_update_requested",
                    "previous_head_sha": expected_head_sha,
                    **(metric_extra or {}),
                }
            )
            return "branch_updated"
        print(f"  branch update failed: {update_reason}")
        _append_stale(
            {
                "pr": pr.number,
                "kind": pr.kind,
                "author": pr.author,
                "action": "branch_update_failed",
                "previous_head_sha": expected_head_sha,
                "reason": update_reason,
                **(metric_extra or {}),
            }
        )
        # 并发 head 变化或 GitHub 瞬时错误均由下一轮重新读取状态后重试；
        # 不把 behind 误报为代码冲突，也不自动添加 hold-merge。
        return "skipped"

    ok, reason, merge_sha = client.merge_pr(pr.number, method="squash")
    if ok:
        dispatch_failures: list[str] = []
        if not merge_sha:
            dispatch_failures.append(f"merge_sha:{reason}")
        else:
            for workflow_file, inputs in POST_MERGE_WORKFLOWS:
                dispatched, dispatch_reason = client.dispatch_workflow(
                    workflow_file,
                    ref="main",
                    inputs=inputs,
                )
                if not dispatched:
                    dispatch_failures.append(f"{workflow_file}:{dispatch_reason}")

        if dispatch_failures:
            failure_summary = "; ".join(dispatch_failures)
            client.comment(
                pr.number,
                f"{POST_MERGE_DISPATCH_FAIL_MARKER}\n\n"
                f"合并已完成，但主干 CI/CD 未全部派发：`{failure_summary}`。"
                "已标记 `needs-human`；不得把本次动作计为生产闭环。",
            )
            client.add_labels(pr.number, [NEEDS_HUMAN_LABEL])
            _append_stale(
                {
                    "pr": pr.number,
                    "kind": pr.kind,
                    "author": pr.author,
                    "action": "post_merge_dispatch_failed",
                    "merge_sha": merge_sha,
                    "reason": failure_summary,
                    **(metric_extra or {}),
                }
            )
            return "post_merge_dispatch_failed"

        client.comment(pr.number, success_comment)
        _append_stale(
            {
                "pr": pr.number,
                "kind": pr.kind,
                "author": pr.author,
                "action": success_action,
                "merge_sha": merge_sha,
                "dispatched_workflows": [item[0] for item in POST_MERGE_WORKFLOWS],
                **(metric_extra or {}),
            }
        )
        return "auto_merged"

    print(f"  merge failed: {reason}")
    _notify_merge_failure_once(client, pr, reason)
    _append_stale(
        {
            "pr": pr.number,
            "kind": pr.kind,
            "author": pr.author,
            "action": failure_action,
            "reason": reason,
            **(metric_extra or {}),
        }
    )
    return "merge_failed"


# =====================================================================
# allowlist 加载
# =====================================================================


def _allowlist_path() -> Path:
    override = (os.environ.get("AUTO_IMPLEMENT_ALLOWLIST_PATH") or "").strip()
    return Path(override) if override else DEFAULT_ALLOWLIST_PATH


def _parse_allowlist_fallback(text: str) -> dict[str, Any]:
    """无 PyYAML 时的极简解析：只认 enabled / trusted_authors 列表项。"""
    enabled = True
    authors: list[str] = []
    in_authors = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("enabled:"):
            val = stripped.split(":", 1)[1].strip().lower()
            enabled = val in ("true", "1", "yes")
            in_authors = False
            continue
        if stripped.startswith("trusted_authors:"):
            in_authors = True
            continue
        if in_authors and stripped.startswith("- "):
            item = stripped[2:].strip().strip("\"'")
            if item:
                authors.append(item)
            continue
        if not line.startswith((" ", "\t")):
            in_authors = False
    return {"enabled": enabled, "trusted_authors": authors}


def load_trusted_authors(path: Path | None = None) -> list[str]:
    """读取 config/auto-implement-allowlist.yaml 的 trusted_authors 列表。

    文件缺失 / enabled=false / 字段缺失 → 返回空列表（禁用普通 PR auto-merge）。
    """
    cfg_path = path or _allowlist_path()
    if not cfg_path.is_file():
        return []
    try:
        text = cfg_path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        try:
            import yaml  # type: ignore
        except ImportError:
            data = _parse_allowlist_fallback(text)
        else:
            data = yaml.safe_load(text) or {}
        if not isinstance(data, dict) or not data.get("enabled", True):
            return []
        authors = data.get("trusted_authors") or []
        if not isinstance(authors, list):
            return []
        return [str(a).strip() for a in authors if str(a).strip()]
    except Exception:  # noqa: BLE001 — 配置解析失败 fail-safe 禁用
        return []


# =====================================================================
# 二次守卫
# =====================================================================


FORBIDDEN_PATH_PREFIXES = (
    "app/db/migrations/",
    "app/fastapi_app/",
    "scripts/deploy/",
    ".github/workflows/",
    "FHD/.github/workflows/",
)

# 各 PR kind 的二次守卫配置
GUARD_CONFIG = {
    "self_heal": {
        "max_changed_files": 3,
        "max_diff_lines": 50,
        "allowed_suffixes": (".py", ".md"),
    },
    "ai_generated": {
        "max_changed_files": 5,  # allowlist 域已预过滤低风险，放宽
        "max_diff_lines": 100,
        "allowed_suffixes": (".py", ".md", ".ts", ".vue", ".js", ".json", ".yaml", ".yml"),
    },
}


def check_second_guard(client: GitHubClient, pr: PRInfo) -> tuple[bool, str]:
    """二次守卫：返回 (passed, reason)。任一不通过即拦截 auto-merge。"""
    config = GUARD_CONFIG.get(pr.kind, GUARD_CONFIG["self_heal"])

    # 1. CI 全绿（优先用 PRInfo.head_sha，避免再发请求）
    head_sha = pr.head_sha or client.get_pr_head_sha(pr.number)
    ci_ok, ci_reason = client.get_pr_check_runs(pr.number, head_sha)
    if not ci_ok:
        return False, f"ci:{ci_reason}"

    # 2. 体量
    if pr.changed_files > config["max_changed_files"]:
        return False, f"too_many_files:{pr.changed_files}>{config['max_changed_files']}"
    if pr.additions + pr.deletions > config["max_diff_lines"]:
        return False, f"diff_too_large:{pr.additions + pr.deletions}>{config['max_diff_lines']}"

    # 3. 文件类型
    files = client.get_pr_files(pr.number)
    for f in files:
        if not f.endswith(config["allowed_suffixes"]):
            return False, f"forbidden_file_type:{f}"

    # 4. 禁止路径
    for f in files:
        for prefix in FORBIDDEN_PATH_PREFIXES:
            if f.startswith(prefix):
                return False, f"forbidden_path:{f}"

    # 5. autonomy 分支不递归
    if pr.head_branch.startswith("autonomy/self-heal-"):
        # 这是 self-heal 自己创建的，允许；但禁止对其他 autonomy 分支的 PR
        pass
    elif pr.head_branch.startswith("autonomy/"):
        return False, f"autonomy_branch:{pr.head_branch}"

    return True, "ok"


# =====================================================================
# 普通 PR 三重门禁（--scan-regular-prs）
# =====================================================================


def check_regular_pr_gates(
    client: GitHubClient,
    pr: PRInfo,
    trusted_authors: list[str],
) -> tuple[bool, str]:
    """普通 PR auto-merge 三重门禁 + hold-merge veto。

    顺序：hold-merge veto → ai-review → ci → author
    任一不通过即拦截。返回 (passed, reason)。
    """
    # 0. hold-merge veto（最高优先级，强制人工 hold）
    if HOLD_MERGE_LABEL in pr.labels:
        return False, f"veto:{HOLD_MERGE_LABEL}"

    # 1. ai-review: passed
    #    优先认 label（人工或自动化打的），其次查 workflow run conclusion
    if AI_REVIEW_PASSED_LABEL in pr.labels:
        ai_review_ok = True
        ai_review_reason = "label:ai-review:passed"
    else:
        head_sha = pr.head_sha or client.get_pr_head_sha(pr.number)
        ai_review_ok, ai_review_reason = client.get_workflow_run_conclusion(
            head_sha, AI_REVIEW_WORKFLOW_NAME
        )
    if not ai_review_ok:
        return False, f"ai_review:{ai_review_reason}"

    # 2. ci: passed
    head_sha = pr.head_sha or client.get_pr_head_sha(pr.number)
    ci_ok, ci_reason = client.get_pr_check_runs(pr.number, head_sha)
    if not ci_ok:
        return False, f"ci:{ci_reason}"

    # 3. author: trusted-author-allowlist
    if not trusted_authors:
        return False, "trusted_authors:empty_allowlist"
    if pr.author not in trusted_authors:
        return False, f"author:not_trusted:{pr.author or 'unknown'}"

    return True, "ok"


def process_regular_pr(
    client: GitHubClient,
    pr: PRInfo,
    trusted_authors: list[str],
    *,
    dry_run: bool = False,
) -> str:
    """处理单个普通 PR：通过三重门禁 → squash merge；否则 skip。

    返回动作：auto_merged / branch_updated / auto_merged_dry / skipped /
    merge_failed。
    不做 stale/close（普通 PR 由人工 review 兜底）。
    """
    print(
        f"[PR #{pr.number}] kind=regular author={pr.author or 'unknown'} "
        f"files={pr.changed_files} labels={pr.labels}"
    )

    passed, reason = check_regular_pr_gates(client, pr, trusted_authors)
    if not passed:
        print(f"  skip: 三重门禁未通过 ({reason})")
        _append_stale(
            {
                "pr": pr.number,
                "kind": "regular",
                "author": pr.author,
                "action": "regular_skipped",
                "reason": reason,
            }
        )
        return "skipped"

    print(f"  三重门禁通过 ({reason})，auto-merge (squash)")
    if not dry_run:
        return _try_auto_merge(
            client,
            pr,
            success_comment=(
                "✅ 三重门禁通过（ai-review:passed + ci:passed + author:trusted），"
                "自动 squash merge。"
            ),
            success_action="regular_auto_merged",
            failure_action="regular_auto_merge_failed",
        )
    return "auto_merged_dry"


# =====================================================================
# SLA 处理
# =====================================================================


def _append_stale(entry: dict[str, Any]) -> None:
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    entry["ts"] = time.time()
    entry["ts_iso"] = datetime.now(UTC).isoformat()
    with STALE_JSONL.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def process_pr(
    client: GitHubClient,
    pr: PRInfo,
    *,
    r0_hours: int,
    r1_hours: int,
    r2_stale_days: int,
    r2_close_days: int,
    r3_stale_days: int,
    r3_close_days: int,
    dry_run: bool = False,
) -> str:
    """按 SLA 处理单个 PR，返回动作（auto_merged / stale_warned / closed / skipped）。"""
    now = time.time()
    age_hours = (now - pr.created_at) / 3600
    age_days = age_hours / 24

    # 缺少显式风险标签时 fail closed。域预授权只授权执行，不能证明
    # 任意 LLM 代码是可自动合并的机械变更。
    risk = ""
    for lab in pr.labels:
        if lab.startswith("risk:"):
            risk = lab.split(":", 1)[1]
            break
    if not risk:
        risk = "r2" if pr.kind == "ai_generated" else "r3"

    print(
        f"[PR #{pr.number}] kind={pr.kind} risk={risk} age={age_days:.1f}d files={pr.changed_files}"
    )

    # ===== hold-merge veto（人工强制 hold，普适）=====
    if HOLD_MERGE_LABEL in pr.labels:
        print(f"  skip: 标 {HOLD_MERGE_LABEL} label，不自动合并/关闭")
        _append_stale(
            {
                "pr": pr.number,
                "kind": pr.kind,
                "risk": risk,
                "action": "hold_merge_vetoed",
            }
        )
        return "skipped"

    # ===== R0 / R1: auto-merge 候选 =====
    if risk in AUTO_MERGE_RISK_LEVELS:
        threshold = r0_hours if risk == "r0" else r1_hours
        if age_hours < threshold:
            print(f"  skip: 未达 {threshold}h 阈值 ({age_hours:.1f}h)")
            return "skipped"

        passed, reason = check_second_guard(client, pr)
        if not passed:
            print(f"  二次守卫拦截: {reason}，升级到 r2")
            if not dry_run:
                client.remove_label(pr.number, f"risk:{risk}")
                client.add_labels(pr.number, ["risk:r2", "needs-human"])
                client.comment(
                    pr.number,
                    f"⚠️ 二次守卫未通过（`{reason}`），自动升级为 `risk:r2`，"
                    f"转 stale→close 流程（7d 提醒 / 14d 关闭）。",
                )
                _append_stale(
                    {
                        "pr": pr.number,
                        "kind": pr.kind,
                        "risk": risk,
                        "action": "upgraded_to_r2",
                        "reason": reason,
                    }
                )
            return "upgraded"

        print(f"  二次守卫通过，auto-merge ({pr.kind} {risk} {threshold}h)")
        if not dry_run:
            return _try_auto_merge(
                client,
                pr,
                success_comment=(
                    f"✅ 二次守卫通过，{pr.kind} {risk} 等级 {threshold}h 到期，自动合并。"
                ),
                success_action="auto_merged",
                failure_action="auto_merge_failed",
                metric_extra={"risk": risk},
            )
        return "auto_merged_dry"

    # ===== R2 / R3: 人工合并最终策略（永不 auto-merge）=====
    if risk not in MANUAL_MERGE_RISK_LEVELS:
        print(f"  skip: unknown risk={risk!r}（非 r0/r1/r2/r3）")
        return "skipped"
    stale_threshold = r2_stale_days if risk == "r2" else r3_stale_days
    close_threshold = r2_close_days if risk == "r2" else r3_close_days

    if age_days >= close_threshold:
        print(f"  超 {close_threshold}d，自动关闭")
        if not dry_run:
            client.comment(
                pr.number,
                f"🔒 自动关闭：{close_threshold} 天未人工 review（risk:{risk}）。"
                f"指纹已记录，如需重新触发请推送新提交。",
            )
            client.close_pr(pr.number)
            _append_stale(
                {
                    "pr": pr.number,
                    "kind": pr.kind,
                    "risk": risk,
                    "action": f"closed_{close_threshold}d",
                }
            )
        return "closed"

    if age_days >= stale_threshold:
        print(f"  超 {stale_threshold}d，发 stale 提醒")
        if not dry_run:
            client.comment(
                pr.number,
                f"⏰ 该 PR 已 stale {int(age_days)} 天（risk:{risk}），"
                f"将于 {close_threshold} 天后自动关闭，请尽快 review。",
            )
            _append_stale(
                {
                    "pr": pr.number,
                    "kind": pr.kind,
                    "risk": risk,
                    "action": f"stale_warned_{stale_threshold}d",
                }
            )
        return "stale_warned"

    print(f"  skip: 未达 stale 阈值 ({age_days:.1f}d < {stale_threshold}d)")
    return "skipped"


# =====================================================================
# main
# =====================================================================


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ai-self-heal PR SLA 处理")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--auto-merge-r0-hours", type=int, default=12)
    parser.add_argument("--auto-merge-r1-hours", type=int, default=48)
    parser.add_argument("--stale-r2-days", type=int, default=7)
    parser.add_argument("--close-r2-days", type=int, default=14)
    parser.add_argument("--stale-r3-days", type=int, default=7)
    parser.add_argument("--close-r3-days", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--scan-regular-prs",
        action="store_true",
        help="同时扫描普通 PR（无 ai-self-heal / ai-generated label），"
        "走三重门禁（ai-review + ci + trusted-author）+ hold-merge veto",
    )
    parser.add_argument(
        "--allowlist-path",
        default="",
        help="覆盖 config/auto-implement-allowlist.yaml 路径（默认 <repo_root>/config/...）",
    )
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN", "")
    if not args.repo or not token:
        print("[error] GITHUB_REPOSITORY / GITHUB_TOKEN 缺失", file=sys.stderr)
        return 1

    if httpx is None:
        print("[error] httpx 未安装", file=sys.stderr)
        return 1

    client = GitHubClient(args.repo, token)

    # ===== ai-self-heal / ai-generated PR: risk 分级 SLA =====
    prs = client.list_self_heal_prs()
    by_kind = {"self_heal": 0, "ai_generated": 0}
    for pr in prs:
        by_kind[pr.kind] = by_kind.get(pr.kind, 0) + 1
    print(
        f"[sla] 发现 {len(prs)} 个 open AI PR "
        f"(ai-self-heal={by_kind['self_heal']} ai-generated={by_kind['ai_generated']})"
    )

    stats = {
        "auto_merged": 0,
        "branch_updated": 0,
        "post_merge_dispatch_failed": 0,
        "upgraded": 0,
        "stale_warned": 0,
        "closed": 0,
        "skipped": 0,
    }
    for pr in prs:
        try:
            action = process_pr(
                client,
                pr,
                r0_hours=args.auto_merge_r0_hours,
                r1_hours=args.auto_merge_r1_hours,
                r2_stale_days=args.stale_r2_days,
                r2_close_days=args.close_r2_days,
                r3_stale_days=args.stale_r3_days,
                r3_close_days=args.close_r3_days,
                dry_run=args.dry_run,
            )
            stats[action] = stats.get(action, 0) + 1
        except Exception as e:  # noqa: BLE001 - 远端 PR 处理需要兜底
            print(f"[error] PR #{pr.number} 处理失败: {e}", file=sys.stderr)

    print(f"[sla] AI PR 处理完成: {stats}")

    # ===== 普通 PR: 三重门禁 auto-merge（opt-in）=====
    regular_stats: dict[str, int] = {}
    if args.scan_regular_prs:
        allowlist_path = Path(args.allowlist_path) if args.allowlist_path else None
        trusted_authors = load_trusted_authors(allowlist_path)
        if not trusted_authors:
            print(
                "[sla] --scan-regular-prs 启用但 trusted_authors 为空 "
                "(config/auto-implement-allowlist.yaml:trusted_authors 未配置)，"
                "跳过普通 PR 扫描（安全无副作用）"
            )
        else:
            regular_prs = client.list_regular_prs()
            print(
                f"[sla] 发现 {len(regular_prs)} 个 open 普通 PR "
                f"(trusted_authors={len(trusted_authors)})"
            )
            regular_stats = {
                "auto_merged": 0,
                "branch_updated": 0,
                "post_merge_dispatch_failed": 0,
                "skipped": 0,
                "merge_failed": 0,
            }
            for pr in regular_prs:
                try:
                    action = process_regular_pr(
                        client,
                        pr,
                        trusted_authors,
                        dry_run=args.dry_run,
                    )
                    regular_stats[action] = regular_stats.get(action, 0) + 1
                except Exception as e:  # noqa: BLE001 - 远端 PR 处理需要兜底
                    print(f"[error] 普通 PR #{pr.number} 处理失败: {e}", file=sys.stderr)
            print(f"[sla] 普通 PR 处理完成: {regular_stats}")

    dispatch_failures = stats.get("post_merge_dispatch_failed", 0) + regular_stats.get(
        "post_merge_dispatch_failed", 0
    )
    if dispatch_failures:
        print(
            f"[error] {dispatch_failures} 个已合并 PR 未完成主干发布派发",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
