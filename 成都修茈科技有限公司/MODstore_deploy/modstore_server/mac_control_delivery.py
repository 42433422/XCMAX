"""Read-only release provenance; executor prose never advances delivery stages."""

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
from sqlalchemy.exc import IntegrityError

from modstore_server.db.mac_control import MacControlObservation
from modstore_server.deploy_context import health_payload
from modstore_server.mac_control_handoff import source_receipt
from modstore_server.mac_control_store import encoded, event

REPOSITORY = "42433422/XCMAX"
SHA = re.compile(r"^[0-9a-f]{40}$")


class GitHubEvidence:
    def __init__(self):
        token = os.environ.get("MODSTORE_MAC_CONTROL_GITHUB_TOKEN") or os.environ.get(
            "GITHUB_TOKEN"
        )
        self.client = httpx.Client(
            base_url=f"https://api.github.com/repos/{REPOSITORY}/",
            headers={
                "Accept": "application/vnd.github+json",
                **({"Authorization": f"Bearer {token}"} if token else {}),
            },
            timeout=3,
            trust_env=False,
            follow_redirects=False,
        )

    def get(self, path):
        response = self.client.get(path)
        response.raise_for_status()
        return response.json()

    def close(self):
        self.client.close()


def stage(name, state="unknown", source="", reference=""):
    return {"name": name, "state": state, "source": source, "reference": reference}


def release_facts(receipt, github, runtime):
    sha = receipt["commit_sha"]
    result = {
        "source_commit": sha,
        "source_archive_sha256": receipt["archive_sha256"],
        "runtime": {
            k: runtime.get(k) for k in ("git_sha", "deploy_tier", "artifact_sha256", "release_id")
        },
        "stages": [
            stage("code", "recorded", "executor_git_readback", sha),
            stage("tests"),
            stage("approval"),
            stage("merged"),
            stage("deployed"),
        ],
    }
    stages = {s["name"]: s for s in result["stages"]}
    pulls = github.get(f"commits/{sha}/pulls?per_page=100")
    if not isinstance(pulls, list) or len(pulls) >= 100:
        raise ValueError("pull_associations_unavailable_or_truncated")
    matches = [
        p
        for p in pulls
        if isinstance(p, dict)
        and (p.get("head") or {}).get("sha") == sha
        and ((p.get("base") or {}).get("repo") or {}).get("full_name") == REPOSITORY
    ]
    if len(matches) != 1:
        result["error"] = "pull_request_missing" if not matches else "pull_request_ambiguous"
        return result
    pull = matches[0]
    number = pull.get("number")
    if not isinstance(number, int) or number < 1:
        raise ValueError("invalid_pull_identity")
    link = f"https://github.com/{REPOSITORY}/pull/{number}"
    result["pull_request"] = {
        "number": number,
        "url": link,
        "state": pull.get("state"),
        "head_sha": sha,
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        checks_job = pool.submit(github.get, f"commits/{sha}/check-runs?per_page=100")
        reviews_job = pool.submit(github.get, f"pulls/{number}/reviews?per_page=100")
        checks, reviews = checks_job.result(), reviews_job.result()
    runs = checks.get("check_runs") if isinstance(checks, dict) else None
    if not isinstance(runs, list) or checks.get("total_count", 101) > len(runs):
        raise ValueError("ci_evidence_unavailable_or_truncated")
    tests = [r for r in runs if re.search(r"test|smoke|contract", str(r.get("name", "")), re.I)]
    result["checks"] = [{k: r.get(k) for k in ("name", "status", "conclusion")} for r in tests]
    if tests:
        state = "passed" if all(r.get("conclusion") == "success" for r in tests) else "pending"
        if any(
            r.get("conclusion") in {"failure", "cancelled", "timed_out", "action_required"}
            for r in tests
        ):
            state = "failed"
        stages["tests"].update(state=state, source="github_check_runs", reference=link + "/checks")
    if not isinstance(reviews, list) or len(reviews) >= 100:
        raise ValueError("review_evidence_unavailable_or_truncated")
    latest = {}
    for review in reviews:
        if review.get("state") in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
            latest[(review.get("user") or {}).get("id")] = review.get("state")
    approval = (
        "changes_requested"
        if "CHANGES_REQUESTED" in latest.values()
        else "approved" if "APPROVED" in latest.values() else "not_recorded"
    )
    stages["approval"].update(state=approval, source="github_pull_reviews", reference=link)
    merge_sha = str(pull.get("merge_commit_sha") or "")
    if not pull.get("merged_at") or not SHA.fullmatch(merge_sha):
        stages["merged"].update(state="pending", source="github_pull_request", reference=link)
        return result
    main = github.get(f"compare/main...{merge_sha}")
    if not isinstance(main, dict) or main.get("status") not in {"behind", "identical"}:
        result["error"] = "merged_commit_not_verified_on_main"
        return result
    result["merge_commit_sha"] = merge_sha
    stages["merged"].update(state="verified", source="github_main_ancestry", reference=merge_sha)
    release_id = str(runtime.get("release_id") or "")
    identity_matches = release_id == merge_sha or bool(
        re.fullmatch(r"xcagi-[0-9A-Za-z][0-9A-Za-z._+-]*-" + merge_sha, release_id)
    )
    deployed = (
        runtime.get("deploy_tier") == "production"
        and runtime.get("git_sha") == merge_sha
        and identity_matches
        and re.fullmatch(r"[0-9a-f]{64}", str(runtime.get("artifact_sha256") or ""))
    )
    stages["deployed"].update(
        state="verified" if deployed else "version_or_artifact_unverified",
        source="modstore_runtime_release_manifest",
        reference=str(runtime.get("git_sha") or ""),
    )
    return result


def delivery_trace(db, task, customer=None):
    """Persist source observations, with explicit failures and bounded API refreshes."""
    now = time.time()
    receipt = source_receipt(json.loads(task.snapshot_json))
    key = "release:" + task.id
    row = db.get(MacControlObservation, key)
    prior = json.loads(row.payload_json) if row else {}
    scoped = (
        os.environ.get("MODSTORE_PARA_REPO_URL", "").removesuffix(".git")
        == "https://github.com/" + REPOSITORY
    )
    if receipt and not scoped:
        return {
            "freshness": "unavailable",
            "error": "project_scope_not_configured",
            "observed_at": None,
            "stages": [
                stage(k)
                for k in (
                    "code",
                    "tests",
                    "approval",
                    "merged",
                    "deployed",
                    "installed",
                    "business",
                )
            ],
        }
    if receipt and (
        not row
        or prior.get("source_commit") != receipt["commit_sha"]
        or now - row.checked_at >= 120
    ):
        github = GitHubEvidence()
        try:
            observed = release_facts(receipt, github, health_payload())
            error = observed.get("error", "")
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as exc:
            observed = {
                "source_commit": receipt["commit_sha"],
                "error": type(exc).__name__,
                "stages": [
                    stage("code", "recorded", "executor_git_readback", receipt["commit_sha"])
                ]
                + [stage(k) for k in ("tests", "approval", "merged", "deployed")],
            }
            error = type(exc).__name__
        finally:
            github.close()
        row = row or MacControlObservation(id=key)
        if observed != prior:
            with db.begin_nested():
                event(db, task, "delivery_evidence_updated", observed)
        row.payload_json, row.checked_at, row.error = encoded(observed), now, error
        row.observed_at = now
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            row = db.get(MacControlObservation, key)
        prior = json.loads(row.payload_json) if row else observed
    result = dict(prior) if receipt else {}
    result["observed_at"] = row.observed_at if row and receipt else None
    result["freshness"] = (
        "missing"
        if not receipt
        else (
            "unavailable"
            if result.get("error")
            else "fresh" if row and now - row.observed_at < 180 else "stale"
        )
    )
    result.setdefault(
        "stages", [stage(k) for k in ("code", "tests", "approval", "merged", "deployed")]
    )
    tickets = (customer or {}).get("tickets") or []
    verified = [
        t.get("delivery_verification")
        for t in tickets
        if not t.get("error") and t.get("delivery_verification")
    ]
    merge_sha = result.get("merge_commit_sha")
    bound = bool(
        SHA.fullmatch(str(merge_sha or ""))
        and verified
        and len(verified) == len(tickets)
        and all(merge_sha in v.get("verified_host_shas", []) for v in verified)
    )
    install = (
        "verified"
        if bound and all(v.get("runtime_business_verified") for v in verified)
        else (
            "receipt_received"
            if any(
                any(
                    r.get("stage") == "installed" and merge_sha and r.get("host_sha") == merge_sha
                    for r in v.get("receipts", [])
                )
                for v in verified
            )
            else "unknown"
        )
    )
    accepted = (
        "verified"
        if bound
        and all(v.get("completed") and v.get("customer_acceptance") == "accepted" for v in verified)
        else "unknown"
    )
    result["stages"] = result["stages"] + [
        stage("installed", install, "customer_delivery_receipts"),
        stage("business", accepted, "customer_service_delivery_completion"),
    ]
    return result
