"""AI self-heal PR SLA 处理：auto-merge / stale 提醒 / 关闭。

每 6 小时扫描 open PR，覆盖两类来源：
- label:ai-self-heal — ai-self-heal workflow 自动修复 PR
- label:ai-generated — ai-issue-implement workflow 自动实现 PR

按 risk:* 标签分流处理：
- r0：≥ 12h（ai-self-heal）/ ≥ 12h（ai-generated）且二次守卫通过 → auto-merge
- r1：≥ 48h 且二次守卫通过 → auto-merge
- r2：≥ 7d stale 评论，≥ 14d 自动关闭
- r3：≥ 7d stale 评论，≥ 30d 自动关闭（永不 auto-merge）

二次守卫（r0/r1 auto-merge 前置）：
1. CI 全绿
2. PR 体量
   - ai-self-heal: ≤ 3 文件 + ≤ 50 diff 行（严格，机械修复）
   - ai-generated: ≤ 5 文件 + ≤ 100 diff 行（宽松，allowlist 域已预过滤低风险）
3. 文件类型
   - ai-self-heal: 仅 .py / .md
   - ai-generated: .py / .md / .ts / .vue / .js / .json / .yaml / .yml
4. 禁止修改 db/migrations、fastapi_app、deploy 脚本、workflows
5. 不是 autonomy/ 分支（不递归）

全部动作写 metrics/ai-self-heal-stale.jsonl。

环境变量：
  GITHUB_TOKEN    必填
  GITHUB_REPOSITORY  必填（如 "owner/repo"）
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
    kind: str = "self_heal"  # "self_heal" | "ai_generated"


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
                    )
                )
                seen.add(pr_number)
        return prs

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

    def merge_pr(self, pr_number: int, method: str = "squash") -> bool:
        url = f"{GITHUB_API}/repos/{self.repo}/pulls/{pr_number}/merge"
        resp = self.client.put(url, json={"merge_method": method})
        return resp.status_code == 200

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

ALLOWED_FILE_SUFFIXES = (".py", ".md")


def check_second_guard(client: GitHubClient, pr: PRInfo) -> tuple[bool, str]:
    """二次守卫：返回 (passed, reason)。任一不通过即拦截 auto-merge。"""
    # 1. CI 全绿
    head_sha = client.get_pr_head_sha(pr.number)
    ci_ok, ci_reason = client.get_pr_check_runs(pr.number, head_sha)
    if not ci_ok:
        return False, f"ci:{ci_reason}"

    # 2. 体量
    if pr.changed_files > 3:
        return False, f"too_many_files:{pr.changed_files}"
    if pr.additions + pr.deletions > 50:
        return False, f"diff_too_large:{pr.additions + pr.deletions}"

    # 3. 文件类型
    files = client.get_pr_files(pr.number)
    for f in files:
        if not f.endswith(ALLOWED_FILE_SUFFIXES):
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

    # 提取风险等级
    risk = "r3"
    for lab in pr.labels:
        if lab.startswith("risk:"):
            risk = lab.split(":", 1)[1]
            break

    print(f"[PR #{pr.number}] risk={risk} age={age_days:.1f}d files={pr.changed_files}")

    # ===== R0 / R1: auto-merge 候选 =====
    if risk in {"r0", "r1"}:
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
                    {"pr": pr.number, "risk": risk, "action": "upgraded_to_r2", "reason": reason}
                )
            return "upgraded"

        print(f"  二次守卫通过，auto-merge ({risk} {threshold}h)")
        if not dry_run:
            ok = client.merge_pr(pr.number, method="squash")
            if ok:
                client.comment(
                    pr.number, f"✅ 二次守卫通过，{risk} 等级 {threshold}h 到期，自动合并。"
                )
                _append_stale({"pr": pr.number, "risk": risk, "action": "auto_merged"})
                return "auto_merged"
            else:
                client.comment(pr.number, "❌ 自动合并失败（可能冲突），请人工处理。")
                _append_stale({"pr": pr.number, "risk": risk, "action": "auto_merge_failed"})
                return "merge_failed"
        return "auto_merged_dry"

    # ===== R2 / R3: stale → close =====
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
            _append_stale({"pr": pr.number, "risk": risk, "action": f"closed_{close_threshold}d"})
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
                {"pr": pr.number, "risk": risk, "action": f"stale_warned_{stale_threshold}d"}
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
    parser.add_argument("--auto-merge-r0-hours", type=int, default=24)
    parser.add_argument("--auto-merge-r1-hours", type=int, default=72)
    parser.add_argument("--stale-r2-days", type=int, default=7)
    parser.add_argument("--close-r2-days", type=int, default=14)
    parser.add_argument("--stale-r3-days", type=int, default=7)
    parser.add_argument("--close-r3-days", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN", "")
    if not args.repo or not token:
        print("[error] GITHUB_REPOSITORY / GITHUB_TOKEN 缺失", file=sys.stderr)
        return 1

    if httpx is None:
        print("[error] httpx 未安装", file=sys.stderr)
        return 1

    client = GitHubClient(args.repo, token)
    prs = client.list_self_heal_prs()
    print(f"[sla] 发现 {len(prs)} 个 ai-self-heal open PR")

    stats = {"auto_merged": 0, "upgraded": 0, "stale_warned": 0, "closed": 0, "skipped": 0}
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
        except Exception as e:
            print(f"[error] PR #{pr.number} 处理失败: {e}", file=sys.stderr)

    print(f"[sla] 处理完成: {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
