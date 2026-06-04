#!/usr/bin/env python3
"""从 GitHub Actions 工作流运行记录生成 DORA 部署事件 JSONL。

数据源：``Deploy``、``CI/CD Pipeline`` 工作流的成功/失败运行（GitHub REST API）。
每条事件字段与 ``dora_metrics.py`` 的 JSONL 契约一致。

用法（CI 或本地，需 ``GITHUB_TOKEN``）::

  python3 scripts/dora_metrics_collect_events.py \\
      --out metrics/deploy_events.jsonl \\
      --max-runs 200
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

API_ROOT = "https://api.github.com"
TARGET_WORKFLOW_NAMES = ("Deploy", "CI/CD Pipeline")


def _auth_headers() -> dict[str, str]:
    token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "xcmax-dora-collect",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers=_auth_headers())
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"GitHub API {exc.code} for {url}: {body}") from exc


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_github_ts(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    s = str(raw).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _repo_slug(explicit: str) -> str:
    if explicit:
        return explicit.strip()
    env = (os.environ.get("GITHUB_REPOSITORY") or "").strip()
    if not env:
        raise SystemExit("missing repo: pass --repo or set GITHUB_REPOSITORY")
    return env


def _list_workflow_ids(repo: str) -> dict[str, int]:
    url = f"{API_ROOT}/repos/{repo}/actions/workflows?per_page=100"
    data = _get_json(url)
    out: dict[str, int] = {}
    for wf in data.get("workflows") or []:
        name = str(wf.get("name") or "")
        if name in TARGET_WORKFLOW_NAMES:
            out[name] = int(wf["id"])
    return out


def _fetch_runs(repo: str, workflow_id: int, *, max_runs: int) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    page = 1
    while len(runs) < max_runs:
        per_page = min(100, max_runs - len(runs))
        url = (
            f"{API_ROOT}/repos/{repo}/actions/workflows/{workflow_id}/runs"
            f"?per_page={per_page}&page={page}&exclude_pull_requests=true"
        )
        data = _get_json(url)
        batch = data.get("workflow_runs") or []
        if not batch:
            break
        runs.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
    return runs[:max_runs]


_commit_cache: dict[str, Optional[datetime]] = {}


def _commit_time(repo: str, sha: str) -> Optional[datetime]:
    if not sha:
        return None
    if sha in _commit_cache:
        return _commit_cache[sha]
    url = f"{API_ROOT}/repos/{repo}/commits/{sha}"
    try:
        data = _get_json(url)
    except RuntimeError:
        _commit_cache[sha] = None
        return None
    commit = (data.get("commit") or {}).get("commit") or {}
    dt = _parse_github_ts((commit.get("author") or {}).get("date"))
    _commit_cache[sha] = dt
    return dt


def _run_to_event(repo: str, run: dict[str, Any]) -> Optional[dict[str, Any]]:
    conclusion = str(run.get("conclusion") or "").lower()
    if conclusion not in ("success", "failure", "cancelled"):
        return None
    deployed = _parse_github_ts(run.get("updated_at")) or _parse_github_ts(run.get("created_at"))
    if deployed is None:
        return None
    sha = str(run.get("head_sha") or "")
    commit_at = _commit_time(repo, sha)
    status = "success" if conclusion == "success" else "failed"
    return {
        "deploy_id": str(run.get("id") or ""),
        "deployed_at": _iso_z(deployed),
        "commit_at": _iso_z(commit_at) if commit_at else None,
        "status": status,
        "restored_at": None,
        "source_workflow": str(run.get("name") or ""),
        "source_run_url": str(run.get("html_url") or ""),
        "head_branch": str(run.get("head_branch") or ""),
        "head_sha": sha,
    }


def _assign_mttr(events: list[dict[str, Any]]) -> None:
    """失败部署的 restored_at = 下一次成功部署时间（同仓库内近似 MTTR）。"""
    ordered = sorted(events, key=lambda e: e["deployed_at"])
    next_success: Optional[str] = None
    for ev in reversed(ordered):
        if ev.get("status") == "success":
            next_success = ev.get("deployed_at")
        elif ev.get("status") == "failed" and next_success and not ev.get("restored_at"):
            ev["restored_at"] = next_success


def _load_existing(path: Path) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return by_id
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        did = str(row.get("deploy_id") or "")
        if did:
            by_id[did] = row
    return by_id


def collect_events(*, repo: str, max_runs: int) -> list[dict[str, Any]]:
    wf_ids = _list_workflow_ids(repo)
    if not wf_ids:
        raise SystemExit(f"no target workflows in {repo}: {TARGET_WORKFLOW_NAMES}")

    merged: dict[str, dict[str, Any]] = {}
    for wf_name, wf_id in wf_ids.items():
        for run in _fetch_runs(repo, wf_id, max_runs=max_runs):
            ev = _run_to_event(repo, run)
            if ev is None:
                continue
            ev["source_workflow"] = wf_name
            merged[ev["deploy_id"]] = ev

    events = list(merged.values())
    _assign_mttr(events)
    events.sort(key=lambda e: e["deployed_at"])
    return events


def write_jsonl(path: Path, events: list[dict[str, Any]], *, merge: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if merge:
        existing = _load_existing(path)
        for ev in events:
            existing[str(ev["deploy_id"])] = ev
        events = sorted(existing.values(), key=lambda e: e["deployed_at"])
    with path.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Collect deploy events from GitHub Actions")
    parser.add_argument("--repo", default="", help="owner/repo (default: GITHUB_REPOSITORY)")
    parser.add_argument("--out", default="metrics/deploy_events.jsonl")
    parser.add_argument("--max-runs", type=int, default=200)
    parser.add_argument("--no-merge", action="store_true", help="replace output file instead of merge")
    args = parser.parse_args(argv)

    repo = _repo_slug(args.repo)
    events = collect_events(repo=repo, max_runs=args.max_runs)
    out = Path(args.out)
    write_jsonl(out, events, merge=not args.no_merge)
    print(f"[ok] {len(events)} deploy events → {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
