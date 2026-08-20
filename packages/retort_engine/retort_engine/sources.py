from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from retort_engine.models import ExternalProjectRef


def _is_github_name(value: str) -> bool:
    return (
        bool(value)
        and len(value) <= 100
        and all(char.isalnum() or char in "-_." for char in value)
    )


@dataclass(frozen=True)
class GitHubRepo:
    owner: str
    repo: str
    ref: str = ""

    @property
    def clone_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}.git"


def parse_github_url(url: str) -> GitHubRepo:
    value = url.strip()[:2048]
    if value.startswith("git@github.com:"):
        path = value.removeprefix("git@github.com:")
    else:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or parsed.hostname != "github.com":
            raise ValueError(f"Not a GitHub URL: {url}")
        path = parsed.path

    parts = [part for part in path.split("/") if part]
    owner = parts[0] if parts else ""
    repo = parts[1].removesuffix(".git") if len(parts) > 1 else ""
    ref = parts[3] if len(parts) > 3 and parts[2] == "tree" else ""
    if not _is_github_name(owner) or not _is_github_name(repo):
        raise ValueError(f"Not a GitHub URL: {url}")
    return GitHubRepo(owner, repo, ref)


def resolve_external_project(
    *,
    github_url: str = "",
    external_path: str = "",
    cache_dir: str = "",
    ref: str = "",
    refresh: bool = False,
) -> ExternalProjectRef:
    if external_path:
        path = Path(external_path).expanduser().resolve()
        if not path.is_dir():
            raise FileNotFoundError(f"External project folder not found: {path}")
        return ExternalProjectRef(str(path), "local_path", str(path), ref)
    if not github_url:
        raise ValueError("Either github_url or external_path is required")
    repo = parse_github_url(github_url)
    actual_ref = ref or repo.ref
    local_path = clone_or_update(
        repo, cache_dir=cache_dir, ref=actual_ref, refresh=refresh
    )
    return ExternalProjectRef(github_url, "github", str(local_path), actual_ref)


def clone_or_update(
    repo: GitHubRepo, *, cache_dir: str = "", ref: str = "", refresh: bool = False
) -> Path:
    root = Path(cache_dir or ".retort/cache/github").expanduser().resolve()
    target = root / repo.owner / repo.repo
    if refresh and target.exists():
        shutil.rmtree(target)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth", "1", repo.clone_url, str(target)],
            check=True,
            text=True,
            capture_output=True,
        )
    if ref:
        subprocess.run(
            ["git", "fetch", "--depth", "1", "origin", ref],
            cwd=target,
            check=False,
            text=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "checkout", ref],
            cwd=target,
            check=True,
            text=True,
            capture_output=True,
        )
    return target
