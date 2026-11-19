from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from modstore_server.corp_download_deployment import (
    CorpDownloadDeployment,
    read_corp_download_deployment,
)

SHA = "a" * 40
REPO = "42433422/XCMAX"
RUN_API = f"https://api.github.com/repos/{REPO}/actions"
LATEST = f"{RUN_API}/workflows/corp-site-deploy.yml/runs?branch=main&per_page=100"
JOBS = f"{RUN_API}/runs/1234/attempts/2/jobs?per_page=100"
NEWER_JOBS = f"{RUN_API}/runs/1235/attempts/2/jobs?per_page=100"
MARKER = "https://xiu-ci.com/site/data/corp-download-deployment.json"
QUERY = f"xcmax_download_probe={SHA}"
APEX_SLASH = f"https://xiu-ci.com/download/?{QUERY}"
WWW_SLASH = f"https://www.xiu-ci.com/download/?{QUERY}"
APEX_FINAL = f"https://xiu-ci.com/download?{QUERY}"
WWW_FINAL = f"https://www.xiu-ci.com/download?{QUERY}"
STEP = "SSH — git sync + xcmax-site-auto-update + nginx reload"
TITLE = "<title>XCAGI 产品下载</title>"


def _configure_http(monkeypatch, scenario: str):
    verified = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=1)
    started = (verified - timedelta(seconds=30)).isoformat()
    completed = (verified + timedelta(seconds=30)).isoformat()
    marker = {
        "deployed_sha": SHA,
        "workflow_run_id": 1234,
        "run_attempt": 2,
        "verified_at": verified.isoformat(),
    }
    run = {
        "id": 1234,
        "run_attempt": 2,
        "status": "completed",
        "conclusion": "success",
        "head_branch": "main",
        "head_sha": SHA,
        "path": ".github/workflows/corp-site-deploy.yml",
        "event": "repository_dispatch",
        "repository": {"full_name": REPO},
        "head_repository": {"full_name": REPO},
        "run_started_at": started,
        "updated_at": completed,
    }
    step = {
        "name": STEP,
        "status": "completed",
        "conclusion": "success",
        "started_at": started,
        "completed_at": completed,
    }
    job = {"name": "deploy", "status": "completed", "conclusion": "success", "steps": [step]}
    calls = []

    def route(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append((request.method, url))
        if request.url.host == "api.github.com":
            assert request.headers.get("authorization") == "Bearer fixture"
        else:
            assert "authorization" not in request.headers
            assert request.headers.get("cache-control") == "no-cache"
        if url == MARKER:
            if scenario == "missing_marker":
                return httpx.Response(404)
            if scenario == "redirected_marker":
                return httpx.Response(301, headers={"Location": "https://outside.invalid"})
            if scenario == "malformed_marker":
                return httpx.Response(200, text="<html>fallback</html>")
            if scenario == "weak_sha":
                marker["deployed_sha"] = SHA[:12]
            if scenario == "boolean_attempt":
                marker["run_attempt"] = True
            if scenario == "unknown_marker_field":
                marker["ticket_id"] = 7
            if scenario == "naive_time":
                marker["verified_at"] = verified.replace(tzinfo=None).isoformat()
            if scenario == "future_time":
                marker["verified_at"] = (verified + timedelta(days=1)).isoformat()
            if scenario == "marker_changed" and calls.count(("GET", MARKER)) == 2:
                marker["run_attempt"] = 3
            return httpx.Response(200, json=marker)
        if url == LATEST:
            changes = {
                "different_sha": {"head_sha": "b" * 40},
                "stale_attempt": {"run_attempt": 3},
                "latest_skipped": {"conclusion": "skipped"},
                "latest_in_progress": {"status": "in_progress", "conclusion": None},
                "different_branch": {"head_branch": "feature"},
                "different_workflow": {"path": ".github/workflows/other.yml"},
                "other_head_repo": {"head_repository": {"full_name": "example/XCMAX"}},
                "outside_run_time": {"updated_at": started},
            }
            run.update(changes.get(scenario, {}))
            if scenario == "github_unavailable":
                raise httpx.ConnectError("fixture unavailable", request=request)
            if scenario.startswith("newer_") or scenario == "latest_different_run":
                newer = {**run, "id": 1235, "event": "schedule"}
                newer.update(
                    {
                        "newer_skipped_run": {"conclusion": "skipped"},
                        "newer_running": {"status": "in_progress", "conclusion": None},
                        "newer_failed": {"conclusion": "failure"},
                        "newer_cancelled": {"conclusion": "cancelled"},
                    }.get(scenario, {})
                )
                return httpx.Response(200, json={"workflow_runs": [newer, run]})
            return httpx.Response(200, json={"workflow_runs": [run]})
        if url == NEWER_JOBS:
            newer_job = dict(job)
            if scenario in ("newer_skipped_job", "newer_other_job_ran"):
                newer_job.update(conclusion="skipped", steps=[])
            jobs = [newer_job]
            if scenario == "newer_other_job_ran":
                jobs.append(dict(job, name="another deployment"))
            return httpx.Response(200, json={"jobs": jobs, "total_count": len(jobs)})
        if url == JOBS:
            if scenario == "job_skipped":
                job["conclusion"] = "skipped"
            if scenario == "ambiguous_steps":
                job["steps"] = [step, step]
            if scenario == "deploy_failed":
                step["conclusion"] = "failure"
            if scenario == "outside_step_time":
                step["completed_at"] = started
            return httpx.Response(
                200, json={"jobs": [job], "total_count": 2 if scenario == "incomplete_jobs" else 1}
            )
        if url == APEX_SLASH:
            target = f"/download?{QUERY}" if scenario == "relative" else APEX_FINAL
            if scenario == "canonical_loop" and ("GET", WWW_SLASH) in calls:
                target = WWW_SLASH
            return httpx.Response(301, headers={"Location": target})
        if url == WWW_SLASH:
            target = {
                "canonical_slash_host": APEX_SLASH,
                "canonical_loop": APEX_SLASH,
                "dropped_query": WWW_FINAL.partition("?")[0],
                "foreign_redirect": f"https://outside.invalid/download?{QUERY}",
                "self_redirect": WWW_SLASH,
            }.get(scenario, WWW_FINAL)
            if scenario == "head_mismatch" and request.method == "HEAD":
                target = APEX_FINAL
            if scenario == "duplicate_location":
                return httpx.Response(301, headers=[("Location", target), ("Location", target)])
            return httpx.Response(
                302 if scenario == "temporary_redirect" else 301, headers={"Location": target}
            )
        if url in (APEX_FINAL, WWW_FINAL):
            if scenario == "final_redirect":
                return httpx.Response(302, headers={"Location": "https://outside.invalid/"})
            if scenario == "final_head_fails" and request.method == "HEAD":
                return httpx.Response(404)
            return httpx.Response(
                200, text=TITLE if scenario != "wrong_title" else "<title>官网首页</title>"
            )
        pytest.fail(f"unexpected request {request.method} {url}")

    real_client = httpx.Client

    def client(*args, **kwargs):
        return real_client(*args, transport=httpx.MockTransport(route), **kwargs)

    monkeypatch.setenv("XCMAX_GITHUB_TOKEN", "fixture")
    monkeypatch.setattr(httpx, "Client", client)
    return calls, CorpDownloadDeployment(SHA, 1234, 2, verified)


@pytest.mark.parametrize("scenario", ["direct", "relative", "canonical_slash_host"])
def test_download_deployment_requires_exact_run_and_observes_both_original_urls(
    monkeypatch, scenario
):
    calls, expected = _configure_http(monkeypatch, scenario)

    assert read_corp_download_deployment() == expected
    assert calls[:3] == [("GET", MARKER), ("GET", LATEST), ("GET", JOBS)]
    assert calls[-1] == ("GET", MARKER)
    expected_urls = [APEX_SLASH, APEX_FINAL, WWW_SLASH, WWW_FINAL]
    if scenario == "canonical_slash_host":
        expected_urls = [APEX_SLASH, APEX_FINAL, WWW_SLASH, APEX_SLASH, APEX_FINAL]
    assert calls[3:-1] == [(method, url) for url in expected_urls for method in ("GET", "HEAD")]


@pytest.mark.parametrize("scenario", ["newer_skipped_run", "newer_skipped_job"])
def test_download_deployment_ignores_proven_newer_nonpublishing_runs(monkeypatch, scenario):
    calls, expected = _configure_http(monkeypatch, scenario)

    assert read_corp_download_deployment() == expected
    if scenario == "newer_skipped_run":
        assert ("GET", NEWER_JOBS) not in calls
    else:
        assert calls[2] == ("GET", NEWER_JOBS)


@pytest.mark.parametrize(
    "scenario",
    [
        "missing_marker",
        "redirected_marker",
        "malformed_marker",
        "weak_sha",
        "boolean_attempt",
        "unknown_marker_field",
        "naive_time",
        "future_time",
        "latest_different_run",
        "different_sha",
        "stale_attempt",
        "latest_skipped",
        "latest_in_progress",
        "different_branch",
        "different_workflow",
        "other_head_repo",
        "outside_run_time",
        "github_unavailable",
        "job_skipped",
        "ambiguous_steps",
        "deploy_failed",
        "outside_step_time",
        "incomplete_jobs",
        "newer_running",
        "newer_failed",
        "newer_cancelled",
        "newer_other_job_ran",
    ],
)
def test_download_deployment_holds_for_untrusted_provenance(monkeypatch, scenario):
    calls, _ = _configure_http(monkeypatch, scenario)

    assert read_corp_download_deployment() is None
    assert all(url in (MARKER, LATEST, JOBS, NEWER_JOBS) for _, url in calls)


@pytest.mark.parametrize(
    "scenario",
    [
        "marker_changed",
        "canonical_loop",
        "dropped_query",
        "foreign_redirect",
        "self_redirect",
        "head_mismatch",
        "duplicate_location",
        "temporary_redirect",
        "final_redirect",
        "final_head_fails",
        "wrong_title",
    ],
)
def test_download_deployment_holds_for_current_regression_or_marker_change(monkeypatch, scenario):
    calls, _ = _configure_http(monkeypatch, scenario)

    assert read_corp_download_deployment() is None
    assert ("GET", APEX_SLASH) in calls
    assert calls.count(("GET", WWW_SLASH)) <= 1
