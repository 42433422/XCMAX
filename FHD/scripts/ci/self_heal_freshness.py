"""Self-Heal 过期失败过滤：只让「当前仍有效」的代码 CI 失败进入修复流程。

规则（只对 CODE_CI_STALE_FILTER 白名单内的 workflow+event 生效）：
- 来源以触发运行（workflow_run 事件 + ``GET /actions/runs/{id}``）为准，
  绝不使用自愈 workflow 自身的 ``github.sha``（workflow_run 下它指向默认分支）。
- 失败运行的 head_sha != 该 PR / 分支当前 head → 过期，跳过。
- 同一运行已有更新的 attempt，或同 workflow + 同 head_sha 有更晚的成功运行 → 跳过。
- PR 已关闭/合并、分支已删除 → 跳过（新代码由新 head 的 CI 覆盖）。
- 任一查询失败或信息不全 → 拦截（fail-closed），不派单，并留痕。
不在白名单的 workflow（部署、巡检、指定版本发布等）不做任何过滤，沿用原流程。
本模块只读：不删除旧失败记录，也不改原 CI 结论。
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

GITHUB_API = "https://api.github.com"

# workflow `name:` → 适用过期过滤的触发事件。不在此表中的 workflow / event 一律不过滤。
# "CI/CD Pipeline" 的 push / schedule / workflow_dispatch 会构建并部署发布物，只过滤 PR 代码 CI。
CODE_CI_STALE_FILTER: dict[str, frozenset[str]] = {
    "CI/CD Pipeline": frozenset({"pull_request"}),
    "CI - Backend Python": frozenset({"pull_request", "push"}),
    "Source Governance": frozenset({"pull_request", "push"}),
    "Smoke Tests": frozenset({"pull_request", "push"}),
    "Employee Smoke Gate": frozenset({"pull_request", "push"}),
    "desktop-macos-smoke": frozenset({"pull_request", "push"}),
    "ci-mobile-flutter": frozenset({"pull_request", "push"}),
}

PROCEED, SKIP, BLOCK = "proceed", "skip", "block"

# get(path, params) -> (status_code, json_or_None)；网络异常应抛出，由调用方 fail-closed。
Getter = Callable[[str, dict[str, Any]], tuple[int, Any]]


class LookupFailed(Exception):
    """GitHub 查询失败或数据不完整。"""


@dataclass(frozen=True)
class Decision:
    action: str  # proceed / skip / block
    reason: str
    workflow: str = ""
    run_id: int = 0
    run_attempt: int = 0
    source_sha: str = ""
    current_sha: str = ""

    def line(self) -> str:
        return (
            f"[freshness] {self.action}: {self.reason} | workflow={self.workflow!r} "
            f"run={self.run_id} attempt={self.run_attempt} "
            f"source_sha={self.source_sha or '-'} current_sha={self.current_sha or '-'}"
        )


def is_filtered(workflow: str, event: str) -> bool:
    return event in CODE_CI_STALE_FILTER.get(workflow, frozenset())


def event_workflow_run(event_path: str | None = None) -> dict[str, Any]:
    """读取触发事件里的 workflow_run 对象；非 workflow_run 触发时返回空 dict。"""
    path = event_path if event_path is not None else os.environ.get("GITHUB_EVENT_PATH", "")
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    run = payload.get("workflow_run") if isinstance(payload, dict) else None
    return run if isinstance(run, dict) else {}


def _get(get: Getter, path: str, params: dict[str, Any] | None = None) -> Any:
    status, data = get(path, params or {})
    if status != 200 or not isinstance(data, dict):
        raise LookupFailed(f"GET {path} -> {status}")
    return data


def _current_head(get: Getter, repo: str, run: dict[str, Any]) -> tuple[str, str]:
    """返回 (current_sha, skip_reason)；skip_reason 非空表示来源已不存在。"""
    prs = [p for p in run.get("pull_requests") or [] if isinstance(p, dict) and p.get("number")]
    if prs:
        pr = _get(get, f"/repos/{repo}/pulls/{int(prs[0]['number'])}")
        sha = str((pr.get("head") or {}).get("sha") or "")
        if not sha:
            raise LookupFailed("pull request head sha missing")
        return sha, "" if pr.get("state") == "open" else f"pr_{pr.get('state')}"
    branch = str(run.get("head_branch") or "")
    head_repo = str((run.get("head_repository") or {}).get("full_name") or repo)
    if not branch:
        raise LookupFailed("source run has no head_branch")
    status, data = get(f"/repos/{head_repo}/branches/{quote(branch, safe='')}", {})
    if status == 404:
        return "", "branch_deleted"
    if status != 200 or not isinstance(data, dict):
        raise LookupFailed(f"branch lookup -> {status}")
    sha = str((data.get("commit") or {}).get("sha") or "")
    if not sha:
        raise LookupFailed("branch head sha missing")
    return sha, ""


def _later_success(get: Getter, repo: str, run: dict[str, Any]) -> int:
    data = _get(
        get,
        f"/repos/{repo}/actions/workflows/{int(run['workflow_id'])}/runs",
        {"head_sha": run["head_sha"], "status": "success", "per_page": 50},
    )
    created = str(run.get("created_at") or "")
    for other in data.get("workflow_runs") or []:
        if other.get("id") != run.get("id") and str(other.get("created_at") or "") > created:
            return int(other["id"])
    return 0


def evaluate(
    *,
    workflow: str,
    run_id: int,
    repo: str,
    get: Getter,
    event_run: dict[str, Any] | None = None,
) -> Decision:
    """判定一次失败是否仍值得派单。纯函数 + 注入的只读 GitHub 查询。"""
    event_run = event_run or {}
    event = str(event_run.get("event") or "")
    base: dict[str, Any] = {
        "workflow": workflow,
        "run_id": run_id,
        "run_attempt": int(event_run.get("run_attempt") or 0),
        "source_sha": str(event_run.get("head_sha") or ""),
    }
    if workflow not in CODE_CI_STALE_FILTER:
        return Decision(PROCEED, "not_code_ci_whitelisted", **base)
    if event and not is_filtered(workflow, event):
        return Decision(PROCEED, f"event_not_filtered:{event}", **base)
    try:
        run = _get(get, f"/repos/{repo}/actions/runs/{int(run_id)}")
        src_attempt = int(event_run.get("run_attempt") or run.get("run_attempt") or 0)
        src_sha = str(event_run.get("head_sha") or run.get("head_sha") or "")
        base.update(run_attempt=src_attempt, source_sha=src_sha)
        if not src_sha or not run.get("workflow_id") or not src_attempt:
            raise LookupFailed("source run missing head_sha/workflow_id/run_attempt")
        if str(run.get("head_sha")) != src_sha or str(run.get("name") or workflow) != workflow:
            return Decision(BLOCK, "source_mismatch_between_event_and_api", **base)
        if not is_filtered(workflow, str(run.get("event") or "")):
            return Decision(PROCEED, f"event_not_filtered:{run.get('event')}", **base)
        latest_attempt = int(run.get("run_attempt") or 0)
        if latest_attempt > src_attempt:
            state = run.get("conclusion") or run.get("status")
            return Decision(SKIP, f"superseded_by_attempt_{latest_attempt}:{state}", **base)
        later = _later_success(get, repo, run)
        if later:
            return Decision(SKIP, f"same_sha_succeeded_in_run_{later}", **base)
        current, gone = _current_head(get, repo, run)
        base["current_sha"] = current
        if gone:
            return Decision(SKIP, gone, **base)
        if current != src_sha:
            return Decision(SKIP, "stale_head", **base)
        return Decision(PROCEED, "current_head", **base)
    except (LookupFailed, KeyError, TypeError, ValueError, OSError) as exc:
        return Decision(BLOCK, f"lookup_failed:{exc}", **base)


def source_markers(decision: Decision, *, include_source: bool = True) -> list[str]:
    """incident 正文的幂等标记：run id+attempt；代码 CI 另加 workflow@head_sha。

    部署/巡检类只用 run id+attempt，避免同一提交的再次部署失败被误判为重复。
    """
    marks = [f"Self-Heal-Run: `{decision.run_id}/{decision.run_attempt}`"]
    if include_source and decision.source_sha:
        marks.append(f"Self-Heal-Source: `{decision.workflow}@{decision.source_sha}`")
    return marks


def find_marked_issue(get: Getter, repo: str, markers: list[str]) -> str:
    """在 auto-incident issue 中查找已带相同标记的单；查询失败抛 LookupFailed。"""
    for page in range(1, 6):
        status, items = get(
            f"/repos/{repo}/issues",
            {
                "state": "all",
                "labels": "auto-incident",
                "sort": "created",
                "direction": "desc",
                "per_page": 100,
                "page": page,
            },
        )
        if status != 200 or not isinstance(items, list):
            raise LookupFailed(f"issue lookup -> {status}")
        for item in items:
            body = str(item.get("body") or "") if isinstance(item, dict) else ""
            if any(m in body for m in markers):
                return str(item.get("html_url") or "")
        if len(items) < 100:
            break
    return ""


def record(decision: Decision, summary_path: str | None = None) -> None:
    """日志 + job summary 留痕；跳过/拦截都不改原 CI 结论。"""
    level = {SKIP: "::notice::", BLOCK: "::error::"}.get(decision.action, "")
    print(level + decision.line())
    path = summary_path if summary_path is not None else os.environ.get("GITHUB_STEP_SUMMARY", "")
    if path and decision.action != PROCEED:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(
                f"- Self-Heal {decision.action}: `{decision.reason}` — workflow `{decision.workflow}`, "
                f"run `{decision.run_id}` attempt `{decision.run_attempt}`, "
                f"source `{decision.source_sha or '-'}`, current `{decision.current_sha or '-'}`\n"
            )
