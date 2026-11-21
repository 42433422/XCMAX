"""Promote only original PR candidates with verified isolated publication authority."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts.autonomy import publish_para_candidate as publication
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
    run_attempt: int = 0  # Legacy intents remain readable; only a fresh exact attempt can write.


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
        source.run_attempt,
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
                or type(target.run_attempt) is not int
                or target.run_attempt < 0
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


def _bound_publication(proof, target, candidate):
    gate = publication.require_live_publication(proof)
    if (
        gate.get("pull_request") != target.number
        or gate.get("source_sha") != target.old_sha
        or gate.get("source_run_id") != target.run_id
        or gate.get("source_run_attempt") != target.run_attempt
        or target.run_attempt < 1
        or gate.get("candidate_commit_sha") != candidate
        or proof.manifest.get("commit_sha") != candidate
        or proof.manifest.get("base_sha") != target.old_sha
        or proof.manifest.get("branch") == target.branch
        or not proof.isolation_artifact_id
    ):
        raise ValueError("original_pr_publication_target_mismatch")
    return gate


def verify_publication(
    state, target, candidate, *, repo, control_task_id, para_task_id, github_run_id, token
):
    request_id = str(uuid.UUID(control_task_id))
    env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_REPOSITORY": repo,
        "GITHUB_RUN_ID": str(github_run_id),
        "GITHUB_SHA": state.get("controller_sha", ""),
        "PARA_GITHUB_REQUEST_ID": request_id,
    }
    process_env = publication.clean_git_env(
        {"PATH": os.environ.get("PATH", os.defpath), "GH_TOKEN": token}
    )

    def gh(path, binary=False):
        return publication.run_command(["gh", "api", path], env=process_env, binary=binary)

    proof = publication.verify_original_publication(
        state,
        env,
        lambda path: json.loads(gh(path)),
        lambda artifact_id: gh(f"/repos/{repo}/actions/artifacts/{artifact_id}/zip", binary=True),
        allow_finished=True,
    )
    gate = _bound_publication(proof, target, candidate)
    if gate["repository"] != repo or gate["task_id"] != para_task_id:
        raise ValueError("original_pr_publication_task_mismatch")
    return proof


def worker_resume(repo, event, get, read_status, read_task, *, token):
    """Bind a completed native worker to its original approved PR; names only locate evidence."""
    notice = event.get("workflow_run") or {}
    if (
        event.get("action") != "completed"
        or (event.get("repository") or {}).get("full_name") != repo
        or type(notice.get("id")) is not int
        or notice["id"] < 1
        or type(notice.get("run_attempt")) is not int
        or notice["run_attempt"] != 1
    ):
        raise ValueError("worker_completion_event_mismatch")
    worker = _get(get, f"/repos/{repo}/actions/runs/{notice['id']}")
    if (
        any(
            worker.get(key) != notice.get(key)
            for key in (
                "id",
                "run_attempt",
                "workflow_id",
                "head_sha",
                "head_branch",
                "event",
                "status",
                "conclusion",
            )
        )
        or type(worker.get("workflow_id")) is not int
        or worker["workflow_id"] < 1
        or worker.get("status") != "completed"
        or worker.get("conclusion") != "success"
        or worker.get("head_branch") != "main"
        or worker.get("event") != "workflow_dispatch"
        or worker.get("path") != ".github/workflows/fhd-para-github-worker.yml"
        or not re.fullmatch(r"[0-9a-f]{40}", str(worker.get("head_sha") or ""))
        or (worker.get("repository") or {}).get("full_name") != repo
    ):
        raise ValueError("worker_completion_native_run_mismatch")
    title = str(worker.get("display_title") or "")
    request = str(uuid.UUID(title.removeprefix("para-workspace-")))
    if title != f"para-workspace-{request}":
        raise ValueError("worker_completion_request_mismatch")
    control_id = uuid.UUID(request).hex
    state = read_status(control_id)
    if (
        state.get("request_id") != request
        or state.get("repository") != repo
        or state.get("run_id") != worker["id"]
    ):
        raise ValueError("worker_completion_original_request_mismatch")
    if state.get("kind") != publication.ORIGINAL_PR_REPAIR:
        return None  # Other existing worker kinds keep their own completion path.
    if state.get("controller_sha") != worker["head_sha"] or any(
        type(state.get(key)) is not int or state[key] < 1
        for key in ("issue_number", "pull_request", "source_run_id", "source_run_attempt")
    ):
        raise ValueError("worker_completion_original_source_mismatch")
    task = read_task(control_id)
    candidate = state.get("publication_candidate") or {}
    if (
        task.get("id") != control_id
        or task.get("executor") != publication.ORIGINAL_PR_REPAIR
        or task.get("github_run_id") != worker["id"]
        or not task.get("para_task_id")
        or task["para_task_id"] != candidate.get("task_id")
    ):
        raise ValueError("worker_completion_original_task_mismatch")
    pr = _get(get, f"/repos/{repo}/pulls/{state['pull_request']}")
    branch = str((pr.get("head") or {}).get("ref") or "")
    comments = list(freshness.pages(get, f"/repos/{repo}/issues/{state['issue_number']}/comments"))
    intent = prior_intent(repo, state["issue_number"], branch, comments)
    applied = False
    if intent:
        target, head, original_id, para_id, run_id = intent
        applied = (
            (original_id, para_id, run_id) == (control_id, task["para_task_id"], worker["id"])
            and (target.number, target.old_sha, target.run_id, target.run_attempt)
            == (
                state["pull_request"],
                state["source_sha"],
                state["source_run_id"],
                state["source_run_attempt"],
            )
            and head == candidate.get("commit_sha") == (pr.get("head") or {}).get("sha")
        )
        if applied:
            open_pr(repo, target, head, get, authorize=False)
    proof = None
    if not applied:
        target = publication.authorized_original_pr(state, repo, get)
        proof = verify_publication(
            state,
            target,
            candidate.get("commit_sha"),
            repo=repo,
            control_task_id=control_id,
            para_task_id=task["para_task_id"],
            github_run_id=worker["id"],
            token=token,
        )
    return {
        "issue_number": state["issue_number"],
        "base_branch": branch,
        "control_task_id": control_id,
        "_worker_resume_proof": proof,
    }


def advance(
    remote: str,
    target: Target,
    candidate: str,
    token: str,
    *,
    before_write,
    authorization=None,
    command=publication.run_command,
) -> int:
    """Use an inert bare repository and ordinary fast-forward; unknown ACKs are read back once."""
    gate = _bound_publication(authorization, target, candidate)
    if (
        remote != f"https://github.com/{gate['repository']}.git"
        or not BRANCH.fullmatch(target.branch)
        or target.branch == "main"
        or ".." in target.branch
        or not token
    ):
        raise ValueError("original_pr_write_identity_mismatch")
    env = publication.clean_git_env({"PATH": os.environ.get("PATH", os.defpath), "GH_TOKEN": token})
    with tempfile.TemporaryDirectory(prefix="para-original-pr-") as temporary:
        root = Path(temporary)
        prefix = [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "protocol.ext.allow=never",
            "-c",
            "credential.helper=",
            "-c",
            "credential.helper=!gh auth git-credential",
        ]

        def git(*args):
            return command(prefix + list(args), cwd=root, env=env)

        git("init", "--bare")
        git(
            "fetch",
            "--no-tags",
            remote,
            f"refs/heads/{target.branch}:refs/heads/original",
            f"refs/heads/{authorization.manifest['branch']}:refs/heads/candidate",
        )
        if (
            git("rev-parse", "refs/heads/original^{commit}").strip() != target.old_sha
            or git("rev-parse", "refs/heads/candidate^{commit}").strip() != candidate
        ):
            raise ValueError("original_pr_or_candidate_head_changed")
        git("merge-base", "--is-ancestor", target.old_sha, candidate)
        git("fsck", "--strict", "--no-reflogs", candidate)
        count = _check_diff(git, target.old_sha, candidate)
        # Persist original intent, then independently re-read authorization.
        renewed = before_write()
        fresh = _bound_publication(renewed, target, candidate)
        if (
            any(fresh[key] != gate[key] for key in gate if key not in {"expires_at"})
            or renewed.artifact_id != authorization.artifact_id
            or renewed.artifact_digest != authorization.artifact_digest
            or renewed.isolation_artifact_id != authorization.isolation_artifact_id
            or renewed.isolation_artifact_digest != authorization.isolation_artifact_digest
        ):
            raise ValueError("original_pr_publication_authority_changed")
        expected = f"{candidate}\trefs/heads/{target.branch}"
        current = git("ls-remote", "--heads", remote, f"refs/heads/{target.branch}").strip()
        if current == expected:
            return count
        if current != f"{target.old_sha}\trefs/heads/{target.branch}":
            raise ValueError("original_pr_head_changed_before_write")
        publication.require_live_publication(renewed)
        try:
            git("push", remote, f"{candidate}:refs/heads/{target.branch}")
        except (OSError, subprocess.SubprocessError):
            if (
                git("ls-remote", "--heads", remote, f"refs/heads/{target.branch}").strip()
                != expected
            ):
                raise ValueError("original_pr_update_unconfirmed") from None
        if git("ls-remote", "--heads", remote, f"refs/heads/{target.branch}").strip() != expected:
            raise ValueError("original_pr_update_unconfirmed")
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
