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
   （标签仅作展示，不能替代当前 head 的成功证据）
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

合并后主干验证：
- `GITHUB_TOKEN` 合并不会触发普通 `push` workflow；合并成功后必须用
  独立 `WORKFLOW_DISPATCH_TOKEN` 显式 workflow_dispatch FHD CI/CD 与
  MODstore 主干 CI；两者均绑定实际合并 SHA，不代替正式发布编排
- 合并前将派发意图保存到机器人 PR 评论；pending 标签允许关闭后继续恢复。
  原生 run ID 与精确 SHA 的 run-name 用于对账；未知响应持续观测至期限，
  只有明确未被接受的请求才有界重试，不能用暂未查到 run 证明派发不存在。
  CI 成功只记 ci_passed，不能把“已派发 / CI 通过”冒充“已发布”。

全部动作写 metrics/ai-self-heal-stale.jsonl。

环境变量：
  GITHUB_TOKEN    必填
  GITHUB_REPOSITORY  必填（如 "owner/repo"）
  BRANCH_UPDATE_TOKEN  behind PR 更新专用 token（CI 使用 CI_COMMIT_TOKEN）
  WORKFLOW_DISPATCH_TOKEN  主干 CI 派发专用 token（CI 使用 CI_COMMIT_TOKEN）
  REQUIRE_INDEPENDENT_WORKFLOW_DISPATCH_TOKEN=1 时缺 token 即 fail closed
  MERGEABILITY_POLL_ATTEMPTS  GitHub mergeable=null 时的最大查询次数（默认 6）
  MERGEABILITY_POLL_BASE_SECONDS  mergeable 重查退避基数秒（默认 1，最大 8 秒）
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

# When this file is executed by path, Python only adds ``scripts/ci`` to
# ``sys.path``.  Keep the FHD package root importable regardless of the
# caller's working directory (including GitHub Actions' ``working-directory``).
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]


GITHUB_API = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
API_MAX_PAGES = 10
METRICS_DIR = ROOT / "metrics"
STALE_JSONL = METRICS_DIR / "ai-self-heal-stale.jsonl"

# allowlist 文件默认路径：<repo_root>/config/auto-implement-allowlist.yaml
REPO_ROOT = ROOT.parent
DEFAULT_ALLOWLIST_PATH = REPO_ROOT / "config" / "auto-implement-allowlist.yaml"

# ai-review workflow 名称（与 FHD/.github/workflows/ai-review.yml `name:` 字段对齐）
AI_REVIEW_WORKFLOW_NAME = "AI Review"
AI_REVIEW_WORKFLOW_PATH = ".github/workflows/fhd-ai-review.yml"
AI_REVIEW_PASSED_LABEL = "ai-review: passed"
HOLD_MERGE_LABEL = "hold-merge"
NEEDS_HUMAN_LABEL = "needs-human"
# 合并失败评论去重标记（勿改文案前缀，否则会再次刷屏）
MERGE_FAIL_COMMENT_MARKER = "❌ 自动合并失败"
POST_MERGE_DISPATCH_FAIL_MARKER = "❌ 自动合并后发布派发失败"

POST_MERGE_WORKFLOWS = ("fhd-ci-cd.yml", "modstore-ci-backend-python.yml")
POST_MERGE_RUN_TITLES = ("CI/CD", "CI - Backend Python")
DELIVERY_LABEL = "post-merge:pending"
DELIVERY_MARKER = "<!-- xcmax-post-merge:v1 -->"
DELIVERY_MAX_ATTEMPTS = 3
DELIVERY_MAX_AGE_SECONDS = 72 * 3600
DELIVERY_VISIBILITY_SECONDS = 10 * 60
DISPATCH_REJECTED_REASONS = frozenset(
    {
        "workflow_dispatch_token_missing",
        "http_400",
        "http_401",
        "http_403",
        "http_404",
        "http_422",
    }
)

# ai-self-heal / ai-generated 标签（用于区分普通 PR）
AI_PR_LABELS = ("ai-self-heal", "ai-generated")

# 最终策略：r2/r3 永不进入 auto-merge 分支（仅 stale→close / 人工）
MANUAL_MERGE_RISK_LEVELS = frozenset({"r2", "r3"})
AUTO_MERGE_RISK_LEVELS = frozenset({"r0", "r1"})
MERGEABILITY_POLL_ATTEMPTS = max(
    1,
    int(os.environ.get("MERGEABILITY_POLL_ATTEMPTS", "6")),
)
MERGEABILITY_POLL_BASE_SECONDS = max(
    0.1,
    float(os.environ.get("MERGEABILITY_POLL_BASE_SECONDS", "1")),
)
MERGEABILITY_POLL_MAX_SECONDS = 8.0


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
    draft: bool = False
    base_branch: str = "main"


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
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
        )
        branch_update_token = (os.environ.get("BRANCH_UPDATE_TOKEN") or "").strip()
        self.branch_update_client = (
            httpx.Client(
                timeout=30.0,
                headers={
                    "Authorization": f"Bearer {branch_update_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": GITHUB_API_VERSION,
                },
            )
            if branch_update_token
            else None
        )
        workflow_dispatch_token = (os.environ.get("WORKFLOW_DISPATCH_TOKEN") or "").strip()
        self.require_independent_workflow_dispatch = (
            os.environ.get("REQUIRE_INDEPENDENT_WORKFLOW_DISPATCH_TOKEN") == "1"
        )
        self.workflow_dispatch_client = (
            httpx.Client(
                timeout=30.0,
                headers={
                    "Authorization": f"Bearer {workflow_dispatch_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": GITHUB_API_VERSION,
                },
            )
            if workflow_dispatch_token
            else None
        )

    def _pages(
        self,
        path: str,
        *,
        key: str = "",
        params: dict[str, Any] | None = None,
        expected_sha: str = "",
    ) -> list[dict[str, Any]]:
        """Read the complete REST collection, or fail closed at the API bound."""
        items: list[dict[str, Any]] = []
        for page in range(1, API_MAX_PAGES + 1):
            response = self.client.get(
                f"{GITHUB_API}/repos/{self.repo}/{path}",
                params={**(params or {}), "per_page": 100, "page": page},
            )
            if response.status_code != 200:
                raise ValueError(f"api_error_{response.status_code}:{path}")
            payload = response.json()
            if expected_sha and payload.get("sha") != expected_sha:
                raise ValueError("response_sha_mismatch")
            batch = payload.get(key) if key else payload
            if not isinstance(batch, list) or any(not isinstance(x, dict) for x in batch):
                raise ValueError(f"invalid_collection:{path}")
            items.extend(batch)
            total = payload.get("total_count") if isinstance(payload, dict) else None
            has_next = "next" in response.links
            if not has_next and (total is not None and len(items) >= total or len(batch) < 100):
                if total is not None and len(items) < total:
                    raise ValueError(f"incomplete_collection:{path}")
                return items
        raise ValueError(f"pagination_limit:{path}")

    def get_pr(self, pr_number: int) -> dict[str, Any]:
        response = self.client.get(f"{GITHUB_API}/repos/{self.repo}/pulls/{pr_number}")
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _pr_info(data: dict[str, Any], kind: str) -> PRInfo:
        return PRInfo(
            number=data["number"],
            title=data["title"],
            url=data["html_url"],
            head_branch=data["head"]["ref"],
            created_at=_parse_iso(data["created_at"]),
            labels=[label["name"] for label in data.get("labels", [])],
            changed_files=data.get("changed_files", 0),
            additions=data.get("additions", 0),
            deletions=data.get("deletions", 0),
            kind=kind,
            author=_extract_login(data.get("user")),
            head_sha=data["head"].get("sha", ""),
            draft=data.get("draft", True),
            base_branch=data.get("base", {}).get("ref", ""),
        )

    def list_self_heal_prs(self) -> list[PRInfo]:
        """Issues labels are AND filters, so combine the two complete collections."""
        prs: dict[int, PRInfo] = {}
        for label, kind in (
            ("ai-self-heal", "self_heal"),
            ("ai-generated", "ai_generated"),
        ):
            for item in self._pages("issues", params={"labels": label, "state": "open"}):
                number = item["number"]
                if "pull_request" in item and number not in prs:
                    prs[number] = self._pr_info(self.get_pr(number), kind)
        return list(prs.values())

    def list_regular_prs(self) -> list[PRInfo]:
        return [
            self._pr_info(data, "regular")
            for data in self._pages("pulls", params={"state": "open", "sort": "created"})
            if not any(label["name"] in AI_PR_LABELS for label in data.get("labels", []))
        ]

    def get_workflow_run_conclusion(self, head_sha: str, workflow_name: str) -> tuple[bool, str]:
        """检查指定 head SHA 上某 workflow 的最近一次 run 是否 conclusion=success。

        GitHub Actions API：list workflow runs by head_sha 过滤 name 字段。
        返回 (passed, reason)。
        """
        if not head_sha:
            return False, "no_head_sha"
        try:
            runs = self._pages("actions/runs", key="workflow_runs", params={"head_sha": head_sha})
        except RECOVERABLE_ERRORS as exc:
            return False, f"workflow_runs_{exc}"
        matched = [
            r
            for r in runs
            if r.get("name") == workflow_name
            and r.get("head_sha") == head_sha
            and r.get("event") == "pull_request"
            and str(r.get("path", "")).split("@", 1)[0] == AI_REVIEW_WORKFLOW_PATH
            and (not r.get("repository") or r["repository"].get("full_name") == self.repo)
        ]
        if not matched:
            return False, f"no_workflow_run:{workflow_name}"
        # 取最新一条（GitHub 默认按 created_at desc 返回，但显式排序更稳）
        latest = max(
            matched,
            key=lambda r: (
                r.get("created_at", ""),
                r.get("id", 0),
                r.get("run_attempt", 1),
            ),
        )
        status = latest.get("status", "")
        conclusion = latest.get("conclusion")
        if status != "completed":
            return False, f"workflow_not_completed:{workflow_name}:{status}"
        if conclusion != "success":
            return False, f"workflow_failed:{workflow_name}:{conclusion}"
        return True, "ok"

    def get_pr_files(self, pr_number: int) -> list[str]:
        return [item["filename"] for item in self._pages(f"pulls/{pr_number}/files")]

    def get_pr_check_runs(self, pr_number: int, head_sha: str) -> tuple[bool, str]:
        """Require complete, current-head checks and legacy commit statuses."""
        if not head_sha:
            return False, "no_head_sha"
        try:
            runs = self._pages(
                f"commits/{head_sha}/check-runs",
                key="check_runs",
                params={"filter": "latest"},
            )
            if not runs:
                return False, "no_check_runs"
            for run in runs:
                if run.get("head_sha") != head_sha:
                    return False, "check_head_mismatch"
                if run.get("status") != "completed" or run.get("conclusion") not in (
                    "success",
                    "neutral",
                    "skipped",
                ):
                    return False, f"ci_not_green:{run.get('name')}"
            statuses = self._pages(
                f"commits/{head_sha}/status", key="statuses", expected_sha=head_sha
            )
            if any(status.get("state") != "success" for status in statuses):
                return False, "commit_status_not_green"
        except RECOVERABLE_ERRORS as exc:
            return False, f"checks:{exc}"
        return True, "ok"

    def get_pr_head_sha(self, pr_number: int) -> str:
        return self.get_pr(pr_number)["head"]["sha"]

    def check_merge_snapshot(self, pr: PRInfo) -> tuple[bool, str]:
        """Re-read vetoes immediately before mutation; REST merge also guards SHA."""
        data = self.get_pr(pr.number)
        fresh = self._pr_info(data, pr.kind)
        if data.get("state") != "open" or fresh.head_sha != pr.head_sha:
            return False, "pr_closed_or_head_changed"
        if fresh.author != pr.author or any(
            (label in fresh.labels) != (label in pr.labels) for label in AI_PR_LABELS
        ):
            return False, "pr_author_or_kind_changed"
        if sorted(x for x in fresh.labels if x.startswith("risk:")) != sorted(
            x for x in pr.labels if x.startswith("risk:")
        ):
            return False, "risk_changed"
        return _merge_veto(fresh)

    def get_pr_mergeability(self, pr_number: int) -> tuple[bool | None, str]:
        """查询 PR 是否可合并。

        返回 (mergeable, reason)：
        - (True, "ok")：可合并
        - (True, "behind")：无冲突但落后主干，应先 update-branch 并重跑检查
        - (False, "conflict")：有冲突
        - (None, reason)：GitHub 仍在计算 / API 异常，调用方应跳过本轮

        GitHub 会在首次读取 PR 后异步计算 ``mergeable``，因此全绿 PR 可能
        短暂返回 null。这里做有界指数退避；仍未知时 fail closed，绝不把
        unknown 当作可合并。
        """
        url = f"{GITHUB_API}/repos/{self.repo}/pulls/{pr_number}"
        for attempt in range(1, MERGEABILITY_POLL_ATTEMPTS + 1):
            resp = self.client.get(url)
            if resp.status_code != 200:
                return None, f"mergeability_api_error_{resp.status_code}"
            data = resp.json()
            mergeable = data.get("mergeable")
            if mergeable is True:
                branch_state = str(data.get("mergeable_state") or "").lower()
                if branch_state == "behind":
                    return True, "behind"
                if branch_state in ("blocked", "dirty", "draft", "unknown"):
                    return None, f"branch_gate:{branch_state}"
                return True, "ok"
            if mergeable is False:
                return False, "conflict"
            if attempt < MERGEABILITY_POLL_ATTEMPTS:
                delay = min(
                    MERGEABILITY_POLL_BASE_SECONDS * (2 ** (attempt - 1)),
                    MERGEABILITY_POLL_MAX_SECONDS,
                )
                time.sleep(delay)
        return None, f"unknown_after_{MERGEABILITY_POLL_ATTEMPTS}_attempts"

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
        except RECOVERABLE_ERRORS:
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

    def merge_pr(
        self, pr_number: int, *, expected_head_sha: str, method: str = "squash"
    ) -> tuple[bool, str, str]:
        """尝试 squash/merge。返回 (ok, reason, merge_sha)。

        reason 取值：ok / conflict / permission / http_<code>:<message>
        """
        url = f"{GITHUB_API}/repos/{self.repo}/pulls/{pr_number}/merge"
        if not _valid_sha(expected_head_sha):
            return False, "invalid_head_sha", ""
        resp = self.client.put(url, json={"merge_method": method, "sha": expected_head_sha})
        if resp.status_code == 200:
            try:
                if resp.json().get("merged") is not True:
                    return False, "merge_not_confirmed", ""
                merge_sha = str((resp.json() or {}).get("sha") or "").strip()
            except RECOVERABLE_ERRORS:
                merge_sha = ""
            if not _valid_sha(merge_sha):
                return True, "ok_missing_merge_sha", ""
            return True, "ok", merge_sha
        message = ""
        try:
            message = str((resp.json() or {}).get("message") or "")
        except RECOVERABLE_ERRORS:
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
    ) -> tuple[bool, str, int]:
        """Request native run details; a legacy 204 still requires reconciliation."""

        url = f"{GITHUB_API}/repos/{self.repo}/actions/workflows/{workflow_file}/dispatches"
        payload: dict[str, Any] = {"ref": ref, "return_run_details": True}
        if inputs:
            payload["inputs"] = inputs
        dispatch_client = getattr(self, "workflow_dispatch_client", None)
        if dispatch_client is None:
            if getattr(
                self,
                "require_independent_workflow_dispatch",
                False,
            ):
                return False, "workflow_dispatch_token_missing", 0
            dispatch_client = self.client
        resp = dispatch_client.post(url, json=payload)
        if resp.status_code in (200, 204):
            run_id = resp.json().get("workflow_run_id", 0) if resp.status_code == 200 else 0
            return (
                True,
                "accepted",
                run_id if isinstance(run_id, int) and run_id > 0 else 0,
            )
        try:
            message = str((resp.json() or {}).get("message") or "")
        except RECOVERABLE_ERRORS:
            message = (resp.text or "")[:200]
        detail = message.replace("\n", " ").strip() or "no_message"
        return False, f"http_{resp.status_code}:{detail[:160]}", 0

    def load_delivery(self, pr_number: int) -> dict[str, Any] | None:
        """Only our GitHub Actions bot may supply a durable receipt."""
        comments = self._pages(f"issues/{pr_number}/comments")
        for comment in reversed(comments):
            body = str(comment.get("body") or "")
            if _extract_login(comment.get("user")) != "github-actions[bot]" or not body.startswith(
                DELIVERY_MARKER
            ):
                continue
            state = json.loads(body.split("```json\n", 1)[1].split("\n```", 1)[0])
            if (
                state.get("version") != 1
                or state.get("pr") != pr_number
                or not _valid_sha(state.get("head_sha", ""))
                or set(state.get("workflows", {})) != set(POST_MERGE_WORKFLOWS)
            ):
                raise ValueError("invalid_delivery_receipt")
            state["comment_id"] = comment["id"]
            return state
        return None

    @staticmethod
    def _delivery_body(state: dict[str, Any]) -> str:
        return (
            DELIVERY_MARKER
            + "\n```json\n"
            + json.dumps(state, ensure_ascii=False, indent=2)
            + "\n```\n主干 CI 回执；ci_passed 仅表示对应 SHA 的 CI 通过，生产发布与运行验收仍需独立证据。"
        )

    def save_delivery(self, state: dict[str, Any]) -> None:
        state["updated_at"] = time.time()
        state["deployment_verified"] = False
        response = self.client.patch(
            f"{GITHUB_API}/repos/{self.repo}/issues/comments/{state['comment_id']}",
            json={"body": self._delivery_body(state)},
        )
        response.raise_for_status()

    def prepare_delivery(self, pr: PRInfo) -> None:
        """Persist discovery label and intent before the irreversible merge."""
        if not _valid_sha(pr.head_sha):
            raise ValueError("invalid_delivery_head_sha")
        state = self.load_delivery(pr.number)
        if state and state["head_sha"] == pr.head_sha:
            if state.get("status") != "pending":
                raise ValueError("delivery_receipt_requires_manual_reset")
        else:
            state = {
                "version": 1,
                "pr": pr.number,
                "head_sha": pr.head_sha,
                "merge_sha": "",
                "created_at": time.time(),
                "status": "pending",
                "deployment_verified": False,
                "workflows": {
                    name: {"status": "pending", "attempts": 0} for name in POST_MERGE_WORKFLOWS
                },
            }
        # GitHub labels are repository resources; create only if absent.
        url = f"{GITHUB_API}/repos/{self.repo}/labels"
        response = self.client.get(f"{url}/{DELIVERY_LABEL}")
        if response.status_code == 404:
            response = self.client.post(url, json={"name": DELIVERY_LABEL, "color": "fbca04"})
        response.raise_for_status()
        if not self.add_labels(pr.number, [DELIVERY_LABEL]):
            raise ValueError("delivery_label_not_persisted")
        if "comment_id" not in state:
            response = self.client.post(
                f"{GITHUB_API}/repos/{self.repo}/issues/{pr.number}/comments",
                json={"body": self._delivery_body(state)},
            )
            response.raise_for_status()
            if not isinstance(response.json().get("id"), int):
                raise ValueError("delivery_comment_not_persisted")

    def list_pending_deliveries(self) -> list[int]:
        items = self._pages(
            "issues",
            params={
                "labels": DELIVERY_LABEL,
                "state": "all",
                "sort": "updated",
                "direction": "asc",
            },
        )
        # Interrupted pre-merge preparations must not starve already merged PRs.
        return [
            item["number"]
            for item in sorted(items, key=lambda item: item.get("state") != "closed")
            if "pull_request" in item
        ]

    @staticmethod
    def _delivery_run_matches(run: dict[str, Any], workflow: str, sha: str) -> bool:
        prefix = POST_MERGE_RUN_TITLES[POST_MERGE_WORKFLOWS.index(workflow)]
        return (
            run.get("event") == "workflow_dispatch"
            and run.get("head_branch") == "main"
            and str(run.get("path", "")).split("@", 1)[0] == f".github/workflows/{workflow}"
            and str(run.get("display_title", "")).strip() == f"{prefix} {sha}"
        )

    def find_delivery_run(
        self, workflow: str, sha: str, receipt: dict[str, Any], since: float
    ) -> dict[str, Any] | None:
        if receipt.get("run_id"):
            response = self.client.get(
                f"{GITHUB_API}/repos/{self.repo}/actions/runs/{int(receipt['run_id'])}"
            )
            if response.status_code != 404:
                response.raise_for_status()
                run = response.json()
                if not self._delivery_run_matches(run, workflow, sha):
                    raise ValueError("delivery_run_identity_mismatch")
                return run
        runs = self._pages(
            f"actions/workflows/{workflow}/runs",
            key="workflow_runs",
            params={
                "event": "workflow_dispatch",
                "branch": "main",
                "created": ">=" + datetime.fromtimestamp(since, UTC).isoformat(),
            },
        )
        matched = [run for run in runs if self._delivery_run_matches(run, workflow, sha)]
        # Never dispatch over an already observed active or successful run.
        return (
            max(
                matched,
                key=lambda run: (
                    run.get("conclusion") == "success",
                    run.get("status") != "completed",
                    run.get("id", 0),
                ),
            )
            if matched
            else None
        )

    def reconcile_delivery(self, pr_number: int, *, expected_merge_sha: str = "") -> str:
        """Recover after merge/POST/crash; serialized by the existing workflow concurrency."""
        state = self.load_delivery(pr_number)
        pr = self.get_pr(pr_number)
        if pr.get("state") == "open":
            return "pending"
        if state is None:
            # A runner can stop between creating the index label and the receipt.
            # Recently merged comments may also be briefly absent from list APIs.
            if pr.get("merged"):
                if time.time() - _parse_iso(pr["merged_at"]) < DELIVERY_VISIBILITY_SECONDS:
                    return "pending"
                if not self.add_labels(pr_number, [NEEDS_HUMAN_LABEL]):
                    raise ValueError("delivery_escalation_not_persisted")
            if not self.remove_label(pr_number, DELIVERY_LABEL):
                raise ValueError("delivery_label_not_cleared")
            return "blocked" if pr.get("merged") else "not_merged"
        if not pr.get("merged"):
            state["status"] = "not_merged"
        else:
            actual_sha = pr.get("merge_commit_sha", "")
            if (
                not _valid_sha(actual_sha)
                or pr.get("head", {}).get("sha") != state["head_sha"]
                or pr.get("base", {}).get("ref") != "main"
                or state.get("merge_sha") not in ("", actual_sha)
                or expected_merge_sha not in ("", actual_sha)
            ):
                state.update(status="blocked", error="merged_pr_identity_mismatch")
            elif state["status"] == "pending":
                state["merge_sha"] = actual_sha
                self.save_delivery(state)
                try:
                    self._reconcile_delivery_workflows(state, _parse_iso(pr["merged_at"]))
                except ValueError as exc:
                    if str(exc) != "delivery_run_identity_mismatch":
                        raise
                    state.update(status="blocked", error=str(exc))
        self.save_delivery(state)
        if state["status"] != "pending":
            if state["status"] == "blocked" and not self.add_labels(pr_number, [NEEDS_HUMAN_LABEL]):
                raise ValueError("delivery_escalation_not_persisted")
            if not self.remove_label(pr_number, DELIVERY_LABEL):
                raise ValueError("delivery_label_not_cleared")
        if state["status"] == "pending" and any(
            receipt.get("error") and receipt["status"] in ("pending", "dispatching")
            for receipt in state["workflows"].values()
        ):
            return "dispatch_failed"
        return state["status"]

    def _reconcile_delivery_workflows(self, state: dict[str, Any], merged_at: float) -> None:
        now = time.time()
        for workflow, receipt in state["workflows"].items():
            if receipt["status"] == "blocked":
                continue
            if now - merged_at >= DELIVERY_MAX_AGE_SECONDS:
                receipt.update(status="blocked", error="delivery_deadline_exceeded")
                continue
            run = self.find_delivery_run(workflow, state["merge_sha"], receipt, merged_at)
            if run:
                receipt.update(
                    run_id=run["id"],
                    run_url=run.get("html_url", ""),
                    dispatch_head_sha=run.get("head_sha", ""),
                )
                receipt["status"] = (
                    ("succeeded" if run.get("conclusion") == "success" else "failed")
                    if run.get("status") == "completed"
                    else "running"
                )
                receipt["conclusion"] = run.get("conclusion")
                receipt["error"] = (
                    f"ci_failed:{workflow}:{run.get('conclusion')}"
                    if receipt["status"] == "failed"
                    else ""
                )
                self.save_delivery(state)
                continue
            if (
                receipt.get("run_id")
                or receipt.get("observed_run")
                or receipt["status"] in ("running", "succeeded", "failed")
            ):
                # An accepted/observed run that temporarily disappears is not a
                # license to start it again. Retain its identity until the deadline.
                receipt.update(
                    status="unavailable",
                    observed_run=True,
                    error="observed_run_unavailable",
                )
                continue
            if receipt["attempts"] and (
                receipt["status"] != "pending"
                or str(receipt.get("error", "")).split(":", 1)[0] not in DISPATCH_REJECTED_REASONS
            ):
                # No idempotency key exists for workflow_dispatch. An unknown
                # response or absent run is never evidence that POST was rejected.
                continue
            if now - receipt.get("requested_at", 0) < DELIVERY_VISIBILITY_SECONDS:
                continue
            if receipt["attempts"] >= DELIVERY_MAX_ATTEMPTS:
                receipt.update(status="blocked", error="dispatch_attempts_exhausted")
                continue
            receipt.update(status="dispatching", requested_at=now, attempts=receipt["attempts"] + 1)
            # Durable intent precedes POST. A crash after POST is reconciled by run title.
            self.save_delivery(state)
            try:
                ok, reason, run_id = self.dispatch_workflow(
                    workflow, inputs={"release_sha": state["merge_sha"]}
                )
                receipt.update(
                    status=(
                        "accepted"
                        if ok
                        else (
                            "pending"
                            if reason.split(":", 1)[0] in DISPATCH_REJECTED_REASONS
                            else "dispatching"
                        )
                    ),
                    error=reason,
                )
                if run_id:
                    receipt["run_id"] = run_id
            except RECOVERABLE_ERRORS as exc:
                receipt.update(status="dispatching", error=f"response_unknown:{exc}")
            self.save_delivery(state)
        statuses = [receipt["status"] for receipt in state["workflows"].values()]
        if all(status == "succeeded" for status in statuses):
            state["status"] = "ci_passed"
        elif all(status in ("succeeded", "failed", "blocked") for status in statuses):
            state["status"] = "blocked"
            state["error"] = "; ".join(
                receipt["error"] for receipt in state["workflows"].values() if receipt.get("error")
            )

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
        return resp.status_code in (200, 204, 404)


def _valid_sha(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(ch in "0123456789abcdef" for ch in value)
    )


def _merge_veto(pr: PRInfo) -> tuple[bool, str]:
    if pr.draft:
        return False, "veto:draft"
    if pr.base_branch != "main":
        return False, "veto:base_branch"
    if HOLD_MERGE_LABEL in pr.labels:
        return False, f"veto:{HOLD_MERGE_LABEL}"
    risks = {label.removeprefix("risk:") for label in pr.labels if label.startswith("risk:")}
    if len(risks) > 1 or risks - AUTO_MERGE_RISK_LEVELS:
        return False, "veto:manual_or_ambiguous_risk"
    if pr.head_branch.startswith("autonomy/") and not pr.head_branch.startswith(
        "autonomy/self-heal-"
    ):
        return False, "veto:autonomy_branch"
    return True, "ok"


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
    except RECOVERABLE_ERRORS as ex:
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

    snapshot_ok, snapshot_reason = client.check_merge_snapshot(pr)
    if not snapshot_ok:
        print(f"  skip: merge snapshot changed ({snapshot_reason})")
        return "skipped"

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

    client.prepare_delivery(pr)
    snapshot_ok, snapshot_reason = client.check_merge_snapshot(pr)
    if not snapshot_ok:
        print(f"  skip: merge snapshot changed ({snapshot_reason})")
        return "skipped"
    ok, reason, merge_sha = client.merge_pr(
        pr.number, expected_head_sha=pr.head_sha, method="squash"
    )
    if ok:
        delivery = client.reconcile_delivery(pr.number, expected_merge_sha=merge_sha)
        failed = delivery in ("blocked", "dispatch_failed")
        action = "post_merge_dispatch_failed" if failed else success_action
        client.comment(
            pr.number,
            success_comment + f" 主干 CI 回执：`{delivery}`；尚未证明生产发布与运行验收。",
        )
        _append_stale(
            {
                "pr": pr.number,
                "kind": pr.kind,
                "author": pr.author,
                "action": action,
                "merge_sha": merge_sha,
                "ci_delivery": delivery,
                "deployment_verified": False,
                **(metric_extra or {}),
            }
        )
        return "post_merge_dispatch_failed" if failed else "auto_merged"

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
            import yaml
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
    except RECOVERABLE_ERRORS:
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
        "allowed_suffixes": (
            ".py",
            ".md",
            ".ts",
            ".vue",
            ".js",
            ".json",
            ".yaml",
            ".yml",
        ),
    },
}


def check_second_guard(client: GitHubClient, pr: PRInfo) -> tuple[bool, str]:
    """二次守卫：返回 (passed, reason)。任一不通过即拦截 auto-merge。"""
    config = GUARD_CONFIG.get(pr.kind, GUARD_CONFIG["self_heal"])

    allowed, reason = _merge_veto(pr)
    if not allowed:
        return False, reason
    pr.head_sha = pr.head_sha or client.get_pr_head_sha(pr.number)
    head_sha = pr.head_sha
    reviewed, reason = client.get_workflow_run_conclusion(head_sha, AI_REVIEW_WORKFLOW_NAME)
    if not reviewed:
        return False, f"ai_review:{reason}"

    # Complete CI evidence belongs to the same immutable PR head.
    ci_ok, ci_reason = client.get_pr_check_runs(pr.number, head_sha)
    if not ci_ok:
        return False, f"ci:{ci_reason}"

    # 2. 体量
    if pr.changed_files > config["max_changed_files"]:
        return False, f"too_many_files:{pr.changed_files}>{config['max_changed_files']}"
    if pr.additions + pr.deletions > config["max_diff_lines"]:
        return (
            False,
            f"diff_too_large:{pr.additions + pr.deletions}>{config['max_diff_lines']}",
        )

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
    allowed, reason = _merge_veto(pr)
    if not allowed:
        return False, reason
    pr.head_sha = pr.head_sha or client.get_pr_head_sha(pr.number)
    head_sha = pr.head_sha
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
        if not dry_run:
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
    if pr.draft or HOLD_MERGE_LABEL in pr.labels:
        print(f"  skip: draft 或 {HOLD_MERGE_LABEL}，不自动合并/关闭")
        if not dry_run:
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
    errors = 0
    # Closed PRs remain discoverable. Recovery runs even when ordinary PR scanning
    # is disabled, and never depends on a runner-local metrics commit surviving.
    try:
        pending_deliveries = client.list_pending_deliveries()
        for number in pending_deliveries[:50]:
            if args.dry_run:
                print(f"[delivery] PR #{number}: dry run, recovery deferred")
                continue
            try:
                result = client.reconcile_delivery(number)
                print(f"[delivery] PR #{number}: {result}; production not verified")
                errors += result in ("blocked", "dispatch_failed")
            except BOUNDARY_ERRORS as exc:
                errors += 1
                print(f"[error] PR #{number} delivery recovery: {exc}", file=sys.stderr)
    except BOUNDARY_ERRORS as exc:
        print(f"[error] delivery discovery: {exc}", file=sys.stderr)
        # Do not merge more PRs while the durable recovery index is unreadable.
        return 1

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
        except BOUNDARY_ERRORS as e:
            errors += 1
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
                except BOUNDARY_ERRORS as e:
                    errors += 1
                    print(f"[error] 普通 PR #{pr.number} 处理失败: {e}", file=sys.stderr)
            print(f"[sla] 普通 PR 处理完成: {regular_stats}")

    dispatch_failures = stats.get("post_merge_dispatch_failed", 0) + regular_stats.get(
        "post_merge_dispatch_failed", 0
    )
    if dispatch_failures or errors:
        print(
            f"[error] {dispatch_failures} 个新合并 PR 派发失败；{errors} 个处理/恢复错误",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
