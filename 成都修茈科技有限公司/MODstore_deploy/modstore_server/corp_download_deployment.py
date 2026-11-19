"""Read hosted deployment evidence for the official download-page redirect."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urljoin

import httpx
from pydantic import BaseModel, ConfigDict, Field

from modstore_server.release_convergence import _fetch_json

_REPOSITORY = "42433422/XCMAX"
_ACTIONS = f"https://api.github.com/repos/{_REPOSITORY}/actions"
_WORKFLOW = "corp-site-deploy.yml"
_RECENT_RUNS = f"{_ACTIONS}/workflows/{_WORKFLOW}/runs?branch=main&per_page=100"
_DEPLOY_STEP = "SSH — git sync + xcmax-site-auto-update + nginx reload"
_HOSTS = ("xiu-ci.com", "www.xiu-ci.com")
_MARKER_URL = f"https://{_HOSTS[0]}/site/data/corp-download-deployment.json"
_DOWNLOAD_TITLE = "<title>XCAGI 产品下载</title>"


@dataclass(frozen=True)
class CorpDownloadDeployment:
    deployed_sha: str
    workflow_run_id: int
    run_attempt: int
    verified_at: datetime


class _DeploymentMarker(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    deployed_sha: str = Field(pattern=r"^[0-9a-f]{40}$", min_length=40, max_length=40)
    workflow_run_id: int = Field(gt=0)
    run_attempt: int = Field(gt=0)
    verified_at: str


def _utc_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("missing evidence timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() != timedelta(0):
        raise ValueError("evidence timestamp must be UTC")
    return parsed.astimezone(UTC)


def _named_row(rows: Any, name: str) -> dict[str, Any]:
    matches = [row for row in rows if isinstance(row, dict) and row.get("name") == name]
    if len(matches) != 1:
        raise ValueError("missing or ambiguous deployment job/step")
    return matches[0]


def _succeeded(row: dict[str, Any]) -> bool:
    return row.get("status") == "completed" and row.get("conclusion") == "success"


def _trusted_run(run: Any) -> bool:
    return (
        isinstance(run, dict)
        and type(run.get("id")) is int
        and run["id"] > 0
        and type(run.get("run_attempt")) is int
        and run["run_attempt"] > 0
        and run.get("head_branch") == "main"
        and run.get("path") == f".github/workflows/{_WORKFLOW}"
        and run.get("event") in ("workflow_dispatch", "repository_dispatch", "schedule", "push")
        and all(
            isinstance(run.get(repo), dict) and run[repo].get("full_name") == _REPOSITORY
            for repo in ("repository", "head_repository")
        )
    )


def _jobs(run: dict[str, Any]) -> list[dict[str, Any]]:
    url = f"{_ACTIONS}/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100"
    payload = _fetch_json(url)
    jobs = payload.get("jobs")
    total = payload.get("total_count")
    if (
        not isinstance(jobs, list)
        or not jobs
        or type(total) is not int
        or total != len(jobs)
        or not all(isinstance(job, dict) for job in jobs)
    ):
        raise ValueError("incomplete deployment jobs")
    return jobs


def _skipped(row: dict[str, Any]) -> bool:
    return row.get("status") == "completed" and row.get("conclusion") == "skipped"


def _github_matches(marker: CorpDownloadDeployment) -> bool:
    runs = _fetch_json(_RECENT_RUNS).get("workflow_runs")
    if not isinstance(runs, list) or len(runs) > 100:
        return False

    for run in runs:
        if not _trusted_run(run):
            return False
        if run["id"] == marker.workflow_run_id:
            return _run_matches(run, marker)
        if _skipped(run):
            continue
        if not _succeeded(run):
            return False
        # A workflow may complete successfully even when its deploy job is skipped.
        jobs = _jobs(run)
        if not _skipped(_named_row(jobs, "deploy")) or not all(_skipped(job) for job in jobs):
            return False
    return False


def _run_matches(run: dict[str, Any], marker: CorpDownloadDeployment) -> bool:
    if (
        not _succeeded(run)
        or run["run_attempt"] != marker.run_attempt
        or run.get("head_sha") != marker.deployed_sha
        or not _utc_time(run.get("run_started_at"))
        <= marker.verified_at
        <= _utc_time(run.get("updated_at"))
    ):
        return False
    job = _named_row(_jobs(run), "deploy")
    steps = job.get("steps")
    if not _succeeded(job) or not isinstance(steps, list):
        return False
    step = _named_row(steps, _DEPLOY_STEP)
    return _succeeded(step) and _utc_time(
        step.get("started_at")
    ) <= marker.verified_at <= _utc_time(step.get("completed_at"))


def _read_marker(client: httpx.Client) -> CorpDownloadDeployment:
    response = client.get(_MARKER_URL, headers={"Accept": "application/json"})
    if response.status_code != 200 or "location" in response.headers:
        raise ValueError("missing direct deployment marker")
    marker = _DeploymentMarker.model_validate_json(response.content)
    return CorpDownloadDeployment(
        deployed_sha=marker.deployed_sha,
        workflow_run_id=marker.workflow_run_id,
        run_attempt=marker.run_attempt,
        verified_at=_utc_time(marker.verified_at),
    )


def _response_target(response: httpx.Response) -> tuple[int, str]:
    locations = response.headers.get_list("location")
    if not locations:
        return response.status_code, ""
    if len(locations) != 1 or not locations[0]:
        raise ValueError("ambiguous redirect target")
    return response.status_code, urljoin(str(response.url), locations[0])


def _check_original_urls(client: httpx.Client, sha: str) -> bool:
    query = f"xcmax_download_probe={sha}"
    slash = tuple(f"https://{host}/download/?{query}" for host in _HOSTS)
    destinations = {f"https://{host}/download?{query}" for host in _HOSTS}

    def agreed_redirect(url: str) -> str:
        get = _response_target(client.get(url))
        head = _response_target(client.head(url))
        if get[0] != 301 or head != get:
            raise ValueError("expected the same permanent redirect for GET and HEAD")
        return get[1]

    for original in slash:
        destination = agreed_redirect(original)
        if original == slash[1] and destination == slash[0]:
            destination = agreed_redirect(slash[0])
        if destination not in destinations:
            return False
        page = client.get(destination)
        if (
            _response_target(page) != (200, "")
            or _DOWNLOAD_TITLE not in page.text
            or _response_target(client.head(destination)) != (200, "")
        ):
            return False
    return True


def read_corp_download_deployment() -> CorpDownloadDeployment | None:
    """Return evidence only when current public probes and the trusted run agree."""
    try:
        with httpx.Client(
            timeout=httpx.Timeout(10.0, connect=5.0),
            follow_redirects=False,
            trust_env=False,
            headers={"Cache-Control": "no-cache"},
        ) as client:
            marker = _read_marker(client)
            if marker.verified_at > datetime.now(UTC) or not _github_matches(marker):
                return None
            if _check_original_urls(client, marker.deployed_sha) and marker == _read_marker(client):
                return marker
    except (httpx.HTTPError, ValueError):
        return None
    return None
