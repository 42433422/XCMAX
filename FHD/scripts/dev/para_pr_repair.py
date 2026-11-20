"""Promote a Para repair to its original PR using an ordinary, leased Git push."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts.autonomy.publish_para_candidate import clean_git_env, run_command
from scripts.ci import self_heal_freshness as freshness
from scripts.ci.ai_self_heal_sla import (
    AUTO_MERGE_RISK_LEVELS,
    FORBIDDEN_PATH_PREFIXES,
    GUARD_CONFIG,
    HOLD_MERGE_LABEL,
    NEEDS_HUMAN_LABEL,
    load_trusted_authors,
)

INTENT_MARKER = "<!-- para-pr-update:v1 "
GIT_ERRORS = (subprocess.CalledProcessError, subprocess.TimeoutExpired)
SHA = re.compile(r"[0-9a-f]{40}")
BRANCH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]{0,199}")
TASK_BRANCH = re.compile(r"devfleet/[A-Za-z0-9_./-]{1,160}")
SKIP_CI = re.compile(
    r"\[(?:skip ci|ci skip|no ci|skip actions|actions skip)\]|^skip-checks\s*:\s*true\s*$",
    re.I | re.M,
)


@dataclass(frozen=True)
class Target:
    number: int
    branch: str
    old_sha: str
    run_id: int
    workflow_id: int
    workflow_path: str


def _bot(item: dict) -> bool:
    return (item.get("user") or {}).get("login") == "github-actions[bot]" and (
        item.get("user") or {}
    ).get("type") == "Bot"


def _labels(item: dict) -> set[str]:
    return {row["name"] for row in item.get("labels", []) if isinstance(row, dict)}


def is_repair_incident(issue: dict) -> bool:
    fields = freshness.incident_fields(str(issue.get("body") or ""))
    return (
        fields.get("Branch") not in (None, "main")
        and fields.get("Self-Heal-Workflow", "").partition("@")[2] in freshness.CODE_CI_PATHS
        and _bot(issue)
        and "auto-incident" in _labels(issue)
    )


def _get(get, path: str) -> dict:
    status, data = get(path, {})
    if status != 200 or not isinstance(data, dict):
        raise ValueError(f"GitHub PR repair read rejected: HTTP {status}")
    return data


def authorized_pr(pr: dict, authors: list[str]) -> bool:
    labels = _labels(pr)
    risks = {name.removeprefix("risk:") for name in labels if name.startswith("risk:")}
    return (
        pr.get("state") == "open"
        and pr.get("draft") is False
        and not labels.intersection({HOLD_MERGE_LABEL, NEEDS_HUMAN_LABEL})
        and len(risks) <= 1
        and risks <= AUTO_MERGE_RISK_LEVELS
        and (pr.get("user") or {}).get("login") in authors
    )


def open_pr(
    repo: str, target: Target, expected_sha: str | None, get, *, authorize: bool = True
) -> dict:
    pr = _get(get, f"/repos/{repo}/pulls/{target.number}")
    head, base = pr.get("head") or {}, pr.get("base") or {}
    if (
        pr.get("number") != target.number
        or head.get("ref") != target.branch
        or (head.get("repo") or {}).get("full_name", "").casefold() != repo.casefold()
        or base.get("ref") != "main"
        or (base.get("repo") or {}).get("full_name", "").casefold() != repo.casefold()
        or not SHA.fullmatch(str(head.get("sha") or ""))
        or (expected_sha is not None and head.get("sha") != expected_sha)
    ):
        raise ValueError("original PR identity or HEAD changed")
    if authorize and not authorized_pr(pr, load_trusted_authors()):
        raise ValueError("original PR lacks automatic repair authorization")
    return pr


def select_target(repo: str, issue: dict, branch: str, get) -> Target | None:
    if not BRANCH.fullmatch(branch) or ".." in branch or branch == "main":
        raise ValueError("invalid original PR branch")
    source = freshness.reconcile_source(issue, repo, get)
    if source.action == freshness.PROCEED and source.disposition == "unfiltered":
        return None
    if (
        source.action != freshness.PROCEED
        or source.disposition != "current"
        or source.head_branch != branch
        or source.head_repo.casefold() != repo.casefold()
    ):
        raise ValueError("incident no longer identifies a current same-repository CI failure")
    run = _get(get, f"/repos/{repo}/actions/runs/{source.run_id}")
    if run.get("id") != source.run_id or run.get("conclusion") != "failure":
        raise ValueError("original CI run did not report failure")
    associated = run.get("pull_requests") or []
    if not associated:
        associated = list(
            freshness.pages(
                get,
                f"/repos/{repo}/pulls",
                {
                    "head": f"{repo.split('/', maxsplit=1)[0]}:{branch}",
                    "base": "main",
                    "state": "open",
                },
            )
        )
    if not associated and source.event != "pull_request":
        return None
    if (
        len(associated) != 1
        or not isinstance(associated[0], dict)
        or type(associated[0].get("number")) is not int
        or associated[0]["number"] < 1
    ):
        raise ValueError("original CI run does not identify one PR")
    target = Target(
        associated[0]["number"],
        branch,
        source.source_sha,
        source.run_id,
        source.workflow_id,
        source.workflow_path,
    )
    open_pr(repo, target, target.old_sha, get)
    return target


def prior_intent(repo: str, number: int, branch: str, comments: list[dict]):
    intents = []
    for comment in comments:
        body = str(comment.get("body") or "")
        if _bot(comment) and body.startswith(INTENT_MARKER):
            raw, _, _ = body.removeprefix(INTENT_MARKER).partition(" -->")
            data = json.loads(raw)
            target = Target(**data["target"])
            head = data["new_sha"]
            control_task_id, para_task_id = data["control_task_id"], data["para_task_id"]
            github_run_id = data.get("github_run_id", 0)
            if (
                data["repository"] != repo
                or data["issue_number"] != number
                or target.branch != branch
                or branch == "main"
                or not BRANCH.fullmatch(branch)
                or ".." in branch
                or not SHA.fullmatch(target.old_sha)
                or not SHA.fullmatch(head)
                or head == target.old_sha
                or target.workflow_path not in freshness.CODE_CI_PATHS
                or min(target.number, target.run_id, target.workflow_id) < 1
                or type(github_run_id) is not int
                or github_run_id < 0
                or any(
                    not isinstance(value, str) or not value
                    for value in (control_task_id, para_task_id)
                )
            ):
                raise ValueError("original PR write intent identity mismatch")
            intents.append((target, head, control_task_id, para_task_id, github_run_id))
    if len(intents) > 1:
        raise ValueError("ambiguous original PR write intent")
    return intents[0] if intents else None


def intent_body(
    repo: str,
    issue_number: int,
    target: Target,
    new_sha: str,
    *,
    control_task_id: str,
    para_task_id: str,
    github_run_id: int = 0,
) -> str:
    return (
        INTENT_MARKER
        + json.dumps(
            {
                "repository": repo,
                "issue_number": issue_number,
                "target": asdict(target),
                "new_sha": new_sha,
                "control_task_id": control_task_id,
                "para_task_id": para_task_id,
                "github_run_id": github_run_id,
            },
            sort_keys=True,
        )
        + " -->\n原 PR 更新准备记录。请根据 GitHub HEAD 和 CI 回读确认结果。"
    )


def candidate_belongs_to_task(branch: str, execution: dict, target: Target) -> bool:
    return (
        branch != target.branch
        and TASK_BRANCH.fullmatch(branch) is not None
        and ".." not in branch
        and any(
            isinstance(task, dict) and task.get("branch_name") == branch
            for task in execution.get("subtasks") or []
        )
    )


def _check_diff(git, old: str, new: str) -> int:
    lines = git("diff", "--no-renames", "--numstat", "-z", old, new).split("\0")[:-1]
    policy = GUARD_CONFIG["ai_generated"]
    if not 0 < len(lines) <= policy["max_changed_files"]:
        raise ValueError("repair exceeds the authorized file count or has no changes")
    size = 0
    for change in lines:
        additions, deletions, path = change.split("\t", 2)
        if (
            not additions.isdecimal()
            or not deletions.isdecimal()
            or not path.endswith(policy["allowed_suffixes"])
            or ".github" in path.split("/")
            or path.removeprefix("FHD/").startswith(
                (
                    *FORBIDDEN_PATH_PREFIXES,
                    "scripts/ci/",
                    "scripts/dev/para_",
                    "scripts/dev/ai_issue_implement.py",
                    "scripts/autonomy/publish_para_candidate.py",
                    "scripts/autonomy/runtime_tools/",
                    "config/auto-implement-allowlist",
                )
            )
        ):
            raise ValueError("repair changes a protected CI path or unsupported file")
        size += int(additions) + int(deletions)
    if size > policy["max_diff_lines"] or SKIP_CI.search(
        git("log", "--format=%B", f"{old}..{new}")
    ):
        raise ValueError("repair exceeds authorized size or suppresses GitHub CI")
    return len(lines)


def advance(remote: str, target: Target, candidate: str, token: str, *, before_write) -> int:
    """Git checks ancestry and the hook checks the advertised old value before transfer."""
    if not SHA.fullmatch(candidate) or candidate == target.old_sha:
        raise ValueError("invalid repair commit")
    with tempfile.TemporaryDirectory(prefix="para-pr-fast-forward-") as temporary:
        root = Path(temporary)
        hooks = root / "hooks"
        hooks.mkdir()
        env = clean_git_env({**os.environ, "GH_TOKEN": token})
        options = [
            "git",
            "-c",
            f"core.hooksPath={hooks}",
            "-c",
            "protocol.ext.allow=never",
            "-c",
            "credential.helper=",
            "-c",
            "credential.helper=!gh auth git-credential",
            "-c",
            "http.followRedirects=false",
        ]

        def git(*args):
            return run_command([*options, *args], cwd=root, env=env)

        git("init", "--bare", "--template=")
        ref = f"refs/heads/{target.branch}"
        git("check-ref-format", ref)
        git("fetch", "--no-tags", "--no-recurse-submodules", "--depth=1", remote, target.old_sha)
        git("update-ref", "refs/para/original", target.old_sha)
        git("fetch", "--no-tags", "--no-recurse-submodules", remote, candidate)
        git("merge-base", "--is-ancestor", target.old_sha, candidate)
        count = _check_diff(git, target.old_sha, candidate)
        hook = hooks / "pre-push"
        hook.write_text(
            "#!/bin/sh\n"
            "IFS=' ' read -r source actual destination previous || exit 1\n"
            '[ "$actual" = "$PARA_REPAIR_NEW" ] && [ "$destination" = "$PARA_REPAIR_REF" ] && '
            '[ "$previous" = "$PARA_REPAIR_OLD" ] || exit 1\n'
            "if read -r unexpected; then exit 1; fi\n",
            encoding="utf-8",
        )
        hook.chmod(0o700)
        env.update(
            PARA_REPAIR_NEW=candidate,
            PARA_REPAIR_REF=ref,
            PARA_REPAIR_OLD=target.old_sha,
        )
        before_write(count)
        git("push", "--porcelain", remote, f"{candidate}:{ref}")
        return count


def new_ci_run(repo: str, target: Target, head: str, get) -> int:
    for out in freshness.pages(
        get,
        f"/repos/{repo}/actions/workflows/{target.workflow_id}/runs",
        {"head_sha": head, "event": "pull_request"},
        key="workflow_runs",
    ):
        if (
            type(out.get("id")) is int
            and out["id"] > 0
            and out["id"] != target.run_id
            and out.get("head_sha") == head
            and out.get("head_branch") == target.branch
            and out.get("workflow_id") == target.workflow_id
            and out.get("path") == target.workflow_path
            and out.get("event") == "pull_request"
            and (out.get("head_repository") or {}).get("full_name", "").casefold()
            == repo.casefold()
            and (
                not out.get("pull_requests")
                or any(pr.get("number") == target.number for pr in out["pull_requests"])
            )
        ):
            return out["id"]
    return 0
