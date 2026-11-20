"""Publish inert Git objects using GitHub Actions artifacts, Git and the existing PR helper.

Runs only in the trusted publisher VM. Never checks out or executes candidate code.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

SCHEMA = "para-github-candidate/v1"
MAX_BUNDLE = 64 * 1024 * 1024
ORIGINAL_PR_REPAIR = "original_pr_repair"
REPAIR_CREDENTIAL_BLOCK = "original_pr_repair_requires_non_exportable_model_credentials"
CUSTOMER_FEEDBACK_REPAIR = "customer_feedback_repair"
CUSTOMER_CREDENTIAL_BLOCK = "customer_feedback_requires_non_exportable_model_credentials"
GITLEAKS_VERSION = "8.18.4"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("management_redirect_rejected")


def read_management(request, *, timeout):
    return build_opener(NoRedirect()).open(request, timeout=timeout)


def safe_artifact(data, digest):
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest or ""):
        raise ValueError("artifact_digest_missing")
    if len(data) > MAX_BUNDLE or "sha256:" + hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("artifact_digest_mismatch")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        if sorted(m.filename for m in members) != ["candidate.bundle", "manifest.json"]:
            raise ValueError("artifact_unexpected_paths")
        for member in members:
            mode = member.external_attr >> 16
            if (
                member.is_dir()
                or (stat.S_IFMT(mode) not in {0, stat.S_IFREG})
                or member.flag_bits & 1
            ):
                raise ValueError("artifact_non_regular_file")
            limit = MAX_BUNDLE if member.filename == "candidate.bundle" else 16384
            if member.file_size > limit:
                raise ValueError("artifact_expansion_limit")
        manifest = json.loads(archive.read("manifest.json"))
        bundle = archive.read("candidate.bundle")
    if not isinstance(manifest, dict) or hashlib.sha256(bundle).hexdigest() != manifest.get(
        "bundle_sha256"
    ):
        raise ValueError("candidate_bundle_digest_mismatch")
    return manifest, bundle


def validate_binding(manifest, state, run, env):
    expected = state.get("publication_candidate")
    if not isinstance(expected, dict) or manifest != expected:
        raise ValueError("candidate_original_receipt_mismatch")
    repo, run_id, request = (
        env["GITHUB_REPOSITORY"],
        env["GITHUB_RUN_ID"],
        env["PARA_GITHUB_REQUEST_ID"],
    )
    branch = manifest.get("branch", "")
    repair = state.get("kind") == ORIGINAL_PR_REPAIR
    base_sha = state.get("source_sha") if repair else env["GITHUB_SHA"]
    if (
        env.get("GITHUB_ACTIONS") != "true"
        or env.get("GITHUB_RUN_ATTEMPT") != "1"
        or env.get("GITHUB_REF") != "refs/heads/main"
        or state.get("request_id") != request
        or str(state.get("run_id")) != run_id
        or state.get("repository") != repo
        or state.get("finished") is True
        or type(state.get("issue_number")) is not int
        or state["issue_number"] < 1
        or manifest.get("schema") != SCHEMA
        or manifest.get("request_id") != request
        or manifest.get("run_id") != run_id
        or manifest.get("repository") != repo
        or (repair and not re.fullmatch(r"[0-9a-f]{40}", base_sha or ""))
        or manifest.get("base_sha") != base_sha
        or manifest.get("pushed") is not False
        or manifest.get("publication") != "artifact_pending"
        or not re.fullmatch(r"[0-9a-f]{40}", manifest.get("commit_sha", ""))
        or manifest["commit_sha"] == manifest["base_sha"]
        or not re.fullmatch(r"devfleet/[A-Za-z0-9_./-]{1,160}", branch)
        or ".." in branch
        or branch.endswith(".lock")
        or run.get("head_sha") != env["GITHUB_SHA"]
        or run.get("head_branch") != "main"
        or str(run.get("id")) != run_id
        or run.get("run_attempt") != 1
        or run.get("event") != "workflow_dispatch"
        or run.get("path") != ".github/workflows/fhd-para-github-worker.yml"
        or run.get("display_title") != f"para-workspace-{request}"
        or run.get("repository", {}).get("full_name") != repo
    ):
        raise ValueError("publication_dispatch_binding_mismatch")


def clean_git_env(env):
    # Neither the artifact nor the executor's git config, hooks or HOME cross this VM boundary.
    result = {k: v for k, v in env.items() if not k.startswith("GIT_")}
    result.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
    return result


def run_command(args, *, cwd=None, env=None, binary=False, input_data=None):
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        input=input_data,
        check=True,
        capture_output=True,
        text=not binary,
        timeout=180,
    ).stdout


def scan_candidate(repository, base, target, *, env, command=run_command):
    """Scan every added commit, including merge resolutions and commit messages.

    Pinned Gitleaks (MIT) runs outside the candidate with its built-in rules. This
    detects known secret forms; it does not make model credentials non-exportable.
    """
    with tempfile.TemporaryDirectory(prefix="para-secret-scan-") as temporary:
        root = Path(temporary)
        config, ignore = root / "gitleaks.toml", root / ".gitleaksignore"
        config.write_text("[extend]\nuseDefault = true\n", encoding="utf-8")
        ignore.touch()
        # The scanner receives neither publisher credentials nor candidate/global
        # config. Explicit flags also disable inline allow comments and ignore files.
        scan_env = clean_git_env({"PATH": env.get("PATH", os.defpath), "HOME": temporary})
        options = [
            "gitleaks",
            "detect",
            "--config",
            str(config),
            "--gitleaks-ignore-path",
            str(ignore),
            "--ignore-gitleaks-allow",
            "--redact=100",
            "--no-banner",
            "--exit-code=1",
        ]
        commits = f"{base}..{target}"
        try:
            if command(["gitleaks", "version"], cwd=root, env=scan_env).strip() != GITLEAKS_VERSION:
                raise ValueError("candidate_secret_scan_unavailable_or_rejected")
            # A NUL byte must not hide otherwise recognizable secrets as a binary diff.
            command(
                options
                + [
                    "--source",
                    str(repository),
                    "--log-opts",
                    f"{commits} --full-history --diff-merges=first-parent --no-renames "
                    "--no-ext-diff --no-textconv --text",
                ],
                cwd=root,
                env=scan_env,
            )
            messages = command(
                ["git", "-C", str(repository), "log", "--format=%B", commits],
                cwd=root,
                env=scan_env,
            )
            command(options + ["--pipe"], cwd=root, env=scan_env, input_data=messages)
        except (OSError, subprocess.SubprocessError, UnicodeError):
            # Subprocess diagnostics may contain secret material. Never echo them.
            raise ValueError("candidate_secret_scan_unavailable_or_rejected") from None


def import_candidate(directory, manifest, bundle, *, env, command=run_command):
    git = [
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
    repository = directory / "objects.git"
    command(git + ["init", "--bare", str(repository)], env=env)
    call = lambda *args, **kw: command(git + list(args), cwd=repository, env=env, **kw)
    remote = f"https://github.com/{manifest['repository']}.git"
    call("fetch", "--no-tags", "--depth=1", remote, manifest["base_sha"])
    path = directory / "candidate.bundle"
    path.write_bytes(bundle)
    call("bundle", "verify", str(path))
    heads = call("bundle", "list-heads", str(path)).strip().splitlines()
    if heads != [f"{manifest['commit_sha']} refs/heads/{manifest['branch']}"]:
        raise ValueError("candidate_bundle_refs_mismatch")
    call(
        "-c",
        "protocol.file.allow=always",
        "fetch",
        "--no-tags",
        str(path),
        f"refs/heads/{manifest['branch']}:refs/heads/candidate",
    )
    actual = call("rev-parse", "--verify", "refs/heads/candidate^{commit}").strip()
    if actual != manifest["commit_sha"]:
        raise ValueError("candidate_commit_mismatch")
    call("merge-base", "--is-ancestor", manifest["base_sha"], actual)
    call("fsck", "--strict", "--no-reflogs", actual)
    # A same-repository PAT push starts Actions before PR review. Candidates may
    # change product code, but may not replace the workflow/controller boundary
    # that keeps that code away from repository secrets and write-capable tokens.
    # Use raw NUL-delimited paths and include both sides of renames/deletions.
    changed = call(
        "diff", "--no-renames", "--name-only", "-z", manifest["base_sha"], actual, binary=True
    )
    if any(b".github" in path.split(b"/") for path in changed.split(b"\0") if path):
        raise ValueError("candidate_actions_control_change_requires_review")
    source = call("archive", "--format=tar", actual, binary=True)
    if hashlib.sha256(source).hexdigest() != manifest["archive_sha256"]:
        raise ValueError("candidate_archive_digest_mismatch")
    scan_candidate(repository, manifest["base_sha"], actual, env=env, command=command)
    return call, remote


def authorized_original_pr(state, repo, get):
    from scripts.dev import para_pr_repair

    _, issue = get(f"/repos/{repo}/issues/{state['issue_number']}", {})
    if issue.get("state") != "open" or not para_pr_repair.is_repair_incident(issue):
        raise ValueError("original_pr_repair_incident_closed_or_changed")
    if "ai-implement" not in {label.get("name") for label in issue.get("labels", [])}:
        raise ValueError("original_pr_repair_incident_revoked")
    branch = para_pr_repair.freshness.incident_fields(issue.get("body") or "").get("Branch", "")
    target = para_pr_repair.select_target(repo, issue, branch, get)
    if (
        not target
        or target.number != state.get("pull_request")
        or target.old_sha != state.get("source_sha")
        or target.run_id != state.get("source_run_id")
    ):
        raise ValueError("original_pr_repair_target_changed")
    return target


def _publication_receipt(env, artifact, branch, target, pr_url, *, original_pr):
    receipt = {
        "schema": SCHEMA,
        "request_id": env["PARA_GITHUB_REQUEST_ID"],
        "run_id": env["GITHUB_RUN_ID"],
        "artifact_id": artifact["id"],
        "artifact_digest": artifact["digest"],
        "commit_sha": target,
        "branch": branch,
        "pull_request_url": pr_url,
        "status": "awaiting_original_pr_update" if original_pr else "published_for_review",
        "delivered": False,
    }
    path = Path(env["RUNNER_TEMP"]) / "para-publication.json"
    path.write_text(json.dumps(receipt) + "\n")
    if env.get("GITHUB_OUTPUT"):
        with open(env["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"original_pr={'true' if original_pr else 'false'}\n")
    return receipt


def publish(env=os.environ, *, command=run_command, opener=read_management):
    if not env.get("GH_TOKEN") or any(
        env.get(k) for k in ("CODEX_API_KEY", "DEVFLEET_DEVICE_TOKEN")
    ):
        raise ValueError("publisher_credentials_not_isolated")
    repo, run_id = env["GITHUB_REPOSITORY"], env["GITHUB_RUN_ID"]
    request = env["PARA_GITHUB_REQUEST_ID"]
    if (
        not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo)
        or not run_id.isdigit()
        or not re.fullmatch(r"[0-9a-f-]{36}", request)
    ):
        raise ValueError("invalid_publisher_identity")
    execution_env = clean_git_env(env)

    def gh(*args, binary=False):
        return command(["gh", *args], env=execution_env, binary=binary)

    def api(path):
        return json.loads(gh("api", path))

    def get(path, params):
        return 200, api(path + ("?" + urlencode(params) if params else ""))

    state_request = Request(
        f"https://xiu-ci.com/api/service/mac-control/github-runs/{request}",
        headers={"Authorization": "Bearer " + env["MODSTORE_PARA_DISPATCH_TOKEN"]},
    )
    with opener(state_request, timeout=30) as response:
        state = json.load(response)
    run = api(f"/repos/{repo}/actions/runs/{run_id}")
    artifacts = api(f"/repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100")
    expected_name = f"para-candidate-{request}"
    matches = [a for a in artifacts.get("artifacts", []) if a.get("name") == expected_name]
    if artifacts.get("total_count", 0) > 100 or len(matches) != 1:
        raise ValueError("ambiguous_publication_artifact")
    artifact = matches[0]
    if (
        artifact.get("expired")
        or not isinstance(artifact.get("id"), int)
        or artifact.get("size_in_bytes", MAX_BUNDLE + 1) > MAX_BUNDLE
        or str(artifact.get("workflow_run", {}).get("id")) != run_id
    ):
        raise ValueError("artifact_run_binding_mismatch")
    data = gh("api", f"/repos/{repo}/actions/artifacts/{artifact['id']}/zip", binary=True)
    manifest, bundle = safe_artifact(data, artifact.get("digest"))
    validate_binding(manifest, state, run, env)
    branch, target = manifest["branch"], manifest["commit_sha"]
    customer_repair = state.get("kind") == CUSTOMER_FEEDBACK_REPAIR
    original = None
    if state.get("kind") == ORIGINAL_PR_REPAIR:
        original = authorized_original_pr(state, repo, get)
    with tempfile.TemporaryDirectory(prefix="para-publisher-") as temporary:
        git, remote = import_candidate(
            Path(temporary), manifest, bundle, env=execution_env, command=command
        )
        if original:
            from scripts.dev.para_pr_repair import _check_diff

            if branch == original.branch:
                raise ValueError("original_pr_candidate_is_not_isolated")
            _check_diff(git, original.old_sha, target)
            with opener(state_request, timeout=30) as response:
                latest = json.load(response)
            validate_binding(manifest, latest, run, env)
            if authorized_original_pr(latest, repo, get) != original:
                raise ValueError("original_pr_repair_target_changed")
        existing = git("ls-remote", "--heads", remote, f"refs/heads/{branch}").strip()
        if existing and existing != f"{target}\trefs/heads/{branch}":
            raise ValueError("publication_branch_already_diverged")
        if not existing:
            if original or customer_repair:
                raise ValueError(
                    CUSTOMER_CREDENTIAL_BLOCK if customer_repair else REPAIR_CREDENTIAL_BLOCK
                )
            # No force update, no main branch writes. Ambiguous responses are reconciled by exact ref.
            git("push", remote, f"{target}:refs/heads/{branch}")
        if (
            git("ls-remote", "--heads", remote, f"refs/heads/{branch}").strip()
            != f"{target}\trefs/heads/{branch}"
        ):
            raise ValueError("publication_push_unconfirmed")
        if original:
            return _publication_receipt(
                env,
                artifact,
                branch,
                target,
                f"https://github.com/{repo}/pull/{original.number}",
                original_pr=True,
            )
        pulls = json.loads(
            gh(
                "pr",
                "list",
                "--repo",
                repo,
                "--head",
                branch,
                "--state",
                "all",
                "--json",
                "number,url,headRefOid,baseRefName,body,state",
                "--limit",
                "100",
            )
        )
        if pulls:
            if (
                len(pulls) != 1
                or pulls[0]["headRefOid"] != target
                or pulls[0]["baseRefName"] != "main"
                or not re.search(rf"(?m)^Refs #{state['issue_number']}\s*$", pulls[0]["body"])
                or pulls[0]["state"] == "CLOSED"
            ):
                raise ValueError("publication_existing_pr_mismatch")
            pr = pulls[0]
        else:
            if customer_repair:
                raise ValueError(CUSTOMER_CREDENTIAL_BLOCK)
            # Import only the helper checked out at the trusted workflow SHA; never artifact code.
            helper = Path(__file__).resolve().parent / "runtime_tools" / "pushed_branch_pr.mjs"
            script = """import {execFileSync} from 'node:child_process';
const h = await import(process.argv[1]);
const task = JSON.parse(process.argv[2]);
const result = await h.ensurePullRequestForPushedBranch(h.buildPushedPrRequest(task),
  async args => execFileSync('gh', args, {encoding:'utf8', timeout:60000}));
process.stdout.write(JSON.stringify(result));"""
            task = {
                "task_id": manifest["task_id"],
                "subtask_id": manifest["subtask_id"],
                "repo_url": remote,
                "work_branch": branch,
                "base_branch": "main",
                "auto_merge": False,
            }
            pr_env = {**execution_env, "PARA_GITHUB_ISSUE_NUMBER": str(state["issue_number"])}
            pr = json.loads(
                command(
                    [
                        "node",
                        "--input-type=module",
                        "-e",
                        script,
                        helper.as_uri(),
                        json.dumps(task),
                    ],
                    env=pr_env,
                )
            )
        pr = json.loads(
            gh(
                "pr",
                "view",
                str(int(pr["number"])),
                "--repo",
                repo,
                "--json",
                "number,url,headRefOid,headRefName,baseRefName,body,state",
            )
        )
        if (
            pr["headRefOid"] != target
            or pr["headRefName"] != branch
            or pr["baseRefName"] != "main"
            or pr["state"] == "CLOSED"
            or not re.search(rf"(?m)^Refs #{state['issue_number']}\s*$", pr["body"])
        ):
            raise ValueError("publication_pr_readback_mismatch")
    return _publication_receipt(env, artifact, branch, target, pr["url"], original_pr=False)


if __name__ == "__main__":
    try:
        publish()
    except (ValueError, OSError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        # Never print subprocess output, headers or tokens.
        raise SystemExit(
            f"Publication failed closed ({type(exc).__name__}): "
            + (str(exc) if isinstance(exc, ValueError) else "readback unavailable")
        ) from None
