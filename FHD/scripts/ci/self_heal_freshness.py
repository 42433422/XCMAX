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
import re
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
    # Contract-only release gate runs are repairable only for a current PR; its
    # push/workflow_dispatch runs remain unfiltered release evidence.
    "Release gate CI": frozenset({"pull_request"}),
    "desktop-macos-smoke": frozenset({"pull_request", "push"}),
    "ci-mobile-flutter": frozenset({"pull_request", "push"}),
}
CODE_CI_PATHS = {
    ".github/workflows/fhd-ci-cd.yml": "CI/CD Pipeline",
    ".github/workflows/modstore-ci-backend-python.yml": "CI - Backend Python",
    ".github/workflows/source-governance.yml": "Source Governance",
    ".github/workflows/fhd-test.yml": "Smoke Tests",
    ".github/workflows/fhd-employee-smoke-gate.yml": "Employee Smoke Gate",
    ".github/workflows/fhd-release-gate-ci.yml": "Release gate CI",
    ".github/workflows/desktop-macos-smoke.yml": "desktop-macos-smoke",
    ".github/workflows/fhd-ci-mobile-flutter.yml": "ci-mobile-flutter",
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
    workflow_path: str = ""
    workflow_id: int = 0
    event: str = ""
    head_branch: str = ""
    head_repo: str = ""
    disposition: str = "unresolved"

    def line(self) -> str:
        return (
            f"[freshness] {self.action}: {self.reason} | workflow={self.workflow!r} "
            f"run={self.run_id} attempt={self.run_attempt} "
            f"source_sha={self.source_sha or '-'} current_sha={self.current_sha or '-'} "
            f"identity={self.workflow_id}:{self.workflow_path} disposition={self.disposition}"
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


def pages(get: Getter, path: str, params: dict[str, Any] | None = None, *, key: str = ""):
    """One bounded REST pagination policy; a truncated read never proves absence."""
    for page in range(1, 11):
        status, data = get(path, {**(params or {}), "per_page": 100, "page": page})
        rows = data.get(key) if key and isinstance(data, dict) else data
        if (
            status != 200
            or not isinstance(rows, list)
            or any(not isinstance(r, dict) for r in rows)
        ):
            raise LookupFailed(f"GET {path} page {page} -> {status}: invalid collection")
        yield from rows
        if len(rows) < 100:
            return
    raise LookupFailed(f"GET {path}: pagination limit reached")


def workflow_identity(run: dict[str, Any]) -> tuple[int, str]:
    """Only the source run API establishes identity; display titles are not keys."""
    workflow_id, path = int(run.get("workflow_id") or 0), str(run.get("path") or "")
    if workflow_id <= 0 or not re.fullmatch(r"\.github/workflows/[\w.-]+\.ya?ml", path):
        raise LookupFailed("source run missing or invalid workflow_id/path")
    return workflow_id, path


def incident_fields(body: str) -> dict[str, str]:
    # Logs and extracted errors are untrusted evidence, never routing metadata.
    header = body.split("\n###", 1)[0]
    return dict(re.findall(r"^- ([\w /-]+): `([^`\n]+)`\s*$", header, flags=re.M))


def reconcile_source(issue: dict[str, Any], repo: str, get: Getter) -> Decision:
    """Read-only disposition; superseded is distinct from a proven recovery."""
    fields = incident_fields(str(issue.get("body") or ""))
    try:
        run_id = int(fields.get("Run ID", "0"))
        marker = fields.get("Self-Heal-Run", "")
        marked_run, attempt = map(int, marker.split("/"))
        if not run_id or run_id != marked_run or attempt < 1:
            raise ValueError("source marker mismatch")
    except ValueError:
        return Decision(BLOCK, "incident_source_missing_or_mismatched")
    decision = evaluate(
        workflow=fields.get("Workflow", ""),
        run_id=run_id,
        repo=repo,
        get=get,
        event_run={"run_attempt": attempt},
    )
    if decision.action != BLOCK and (
        fields.get("Branch") != decision.head_branch
        or fields.get("Head Repository", repo).casefold() != decision.head_repo.casefold()
        or (
            fields.get("Self-Heal-Workflow")
            and fields["Self-Heal-Workflow"] != f"{decision.workflow_id}@{decision.workflow_path}"
        )
    ):
        return Decision(BLOCK, "incident_source_branch_or_repository_mismatch", run_id=run_id)
    return decision


def _current_head(get: Getter, repo: str, run: dict[str, Any]) -> tuple[str, str]:
    """返回 (current_sha, skip_reason)；skip_reason 非空表示来源已不存在。"""
    prs = [p for p in run.get("pull_requests") or [] if isinstance(p, dict) and p.get("number")]
    if prs:
        pr = _get(get, f"/repos/{repo}/pulls/{int(prs[0]['number'])}")
        sha = str((pr.get("head") or {}).get("sha") or "")
        if not sha:
            raise LookupFailed("pull request head sha missing")
        if pr.get("state") not in {"open", "closed"}:
            raise LookupFailed("pull request state missing")
        return sha, "" if pr["state"] == "open" else "pr_closed"
    branch = str(run.get("head_branch") or "")
    head_repo = str((run.get("head_repository") or {}).get("full_name") or repo)
    if not branch:
        raise LookupFailed("source run has no head_branch")
    status, data = get(f"/repos/{head_repo}/branches/{quote(branch, safe='')}", {})
    if status == 404:
        if head_repo.casefold() != repo.casefold():
            raise LookupFailed("fork branch 404 does not prove deletion")
        return "", "branch_deleted"
    if status != 200 or not isinstance(data, dict):
        raise LookupFailed(f"branch lookup -> {status}")
    sha = str((data.get("commit") or {}).get("sha") or "")
    if not sha:
        raise LookupFailed("branch head sha missing")
    return sha, ""


def _later_success(get: Getter, repo: str, run: dict[str, Any]) -> int:
    runs = pages(
        get,
        f"/repos/{repo}/actions/workflows/{int(run['workflow_id'])}/runs",
        {"head_sha": run["head_sha"], "status": "success"},
        key="workflow_runs",
    )
    created = str(run.get("created_at") or "")
    if not created:
        raise LookupFailed("source run created_at missing")
    for other in runs:
        if (
            other.get("id") != run.get("id")
            and str(other.get("created_at") or "") > created
            and other.get("head_sha") == run["head_sha"]
            and other.get("workflow_id") == run["workflow_id"]
            and other.get("event") == run["event"]
            and other.get("status") == "completed"
            and other.get("conclusion") == "success"
        ):
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
    base: dict[str, Any] = {
        "workflow": workflow,
        "run_id": run_id,
    }
    try:
        run = _get(get, f"/repos/{repo}/actions/runs/{int(run_id)}")
        workflow_id, path = workflow_identity(run)
        src_attempt = int(event_run.get("run_attempt") or run.get("run_attempt") or 0)
        src_sha = str(event_run.get("head_sha") or run.get("head_sha") or "")
        event = str(run.get("event") or "")
        canonical_name = CODE_CI_PATHS.get(path, str(run.get("name") or ""))
        base.update(
            workflow=canonical_name,
            workflow_path=path,
            workflow_id=workflow_id,
            run_attempt=src_attempt,
            source_sha=src_sha,
            event=event,
            head_branch=str(run.get("head_branch") or ""),
            head_repo=str((run.get("head_repository") or {}).get("full_name") or repo),
        )
        if (
            not re.fullmatch(r"[0-9a-f]{40}", src_sha)
            or src_attempt < 1
            or not event
            or run.get("status")
            not in {
                "completed",
                "queued",
                "in_progress",
                "waiting",
                "requested",
                "pending",
            }
            or (run.get("status") == "completed" and not run.get("conclusion"))
        ):
            raise LookupFailed("source run missing head_sha/event/run_attempt")
        if (
            run.get("id") != run_id
            or str(run.get("head_sha")) != src_sha
            or any(
                event_run.get(k) is not None and event_run[k] != run.get(k)
                for k in ("id", "workflow_id", "path", "event", "head_branch")
            )
            or (
                workflow
                and workflow not in {run.get("name"), run.get("display_title"), canonical_name}
            )
        ):
            return Decision(BLOCK, "source_mismatch_between_event_and_api", **base)
        if path not in CODE_CI_PATHS:
            if workflow in CODE_CI_STALE_FILTER or any(
                re.fullmatch(re.escape(name) + r" [0-9a-f]{40}", workflow)
                for name in ("CI/CD", *CODE_CI_STALE_FILTER)
            ):
                raise LookupFailed("unrecognized code workflow identity")
            return Decision(PROCEED, "not_code_ci_whitelisted", disposition="unfiltered", **base)
        if not is_filtered(canonical_name, event):
            return Decision(
                PROCEED, f"event_not_filtered:{event}", disposition="unfiltered", **base
            )
        latest_attempt = int(run.get("run_attempt") or 0)
        if latest_attempt > src_attempt:
            state = run.get("conclusion") or run.get("status")
            if run.get("status") != "completed" or run.get("conclusion") != "success":
                # The newer failure may already have been deduplicated onto this
                # incident. Without a successor receipt it must remain tracked.
                return Decision(BLOCK, f"newer_attempt_unresolved:{latest_attempt}:{state}", **base)
            return Decision(
                SKIP,
                f"superseded_by_attempt_{latest_attempt}:{state}",
                disposition="recovered",
                **base,
            )
        if latest_attempt != src_attempt:
            raise LookupFailed("source attempt ahead of API")
        if run["status"] != "completed":
            raise LookupFailed("source run not completed")
        if run.get("conclusion") == "success":
            return Decision(SKIP, "source_run_succeeded", disposition="recovered", **base)
        later = _later_success(get, repo, run)
        if later:
            return Decision(
                SKIP,
                f"same_sha_succeeded_in_run_{later}",
                disposition="recovered",
                **base,
            )
        current, gone = _current_head(get, repo, run)
        base["current_sha"] = current
        if gone:
            return Decision(SKIP, gone, disposition="superseded", **base)
        if current != src_sha:
            return Decision(SKIP, "stale_head", disposition="superseded", **base)
        return Decision(PROCEED, "current_head", disposition="current", **base)
    except (LookupFailed, KeyError, TypeError, ValueError, OSError) as exc:
        return Decision(BLOCK, f"lookup_failed:{exc}", **base)


def source_markers(decision: Decision, *, include_source: bool = True) -> list[str]:
    """incident 正文的幂等标记：run id+attempt；代码 CI 另加 workflow@head_sha。

    部署/巡检类只用 run id+attempt，避免同一提交的再次部署失败被误判为重复。
    """
    marks = [f"Self-Heal-Run: `{decision.run_id}/{decision.run_attempt}`"]
    if decision.workflow_path:
        marks.append(f"Self-Heal-Workflow: `{decision.workflow_id}@{decision.workflow_path}`")
    if include_source and decision.source_sha:
        marks.append(
            f"Self-Heal-Source: `{decision.workflow_path or decision.workflow}@{decision.source_sha}`"
        )
    return marks


def find_marked_issue(get: Getter, repo: str, markers: list[str]) -> str:
    """在 auto-incident issue 中查找已带相同标记的单；查询失败抛 LookupFailed。"""
    # Workflow identity is shared by many sources; it must never deduplicate by itself.
    identities = [m for m in markers if not m.startswith("Self-Heal-Workflow:")]
    for item in pages(
        get,
        f"/repos/{repo}/issues",
        {
            "state": "open",
            "labels": "auto-incident",
            "sort": "created",
            "direction": "desc",
        },
    ):
        if (
            not item.get("pull_request")
            and item.get("state") != "closed"
            and any(m in str(item.get("body") or "") for m in identities)
        ):
            if item.get("state") != "open" or not item.get("html_url"):
                raise LookupFailed("matching incident state/url missing")
            return str(item["html_url"])
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
