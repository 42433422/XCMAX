from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from retort_engine.models import ExternalProjectRef


@dataclass(frozen=True)
class GitHubRepo:
    owner: str
    repo: str
    ref: str = ""

    @property
    def clone_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}.git"


def parse_github_url(url: str) -> GitHubRepo:
    match = re.search(r"github\.com[:/](?P<owner>[^/\s]+)/(?P<repo>[^/\s#?]+)(?:/tree/(?P<ref>[^/\s#?]+))?", url)
    if not match:
        raise ValueError(f"Not a GitHub URL: {url}")
    return GitHubRepo(match.group("owner"), match.group("repo").removesuffix(".git"), match.group("ref") or "")


def resolve_external_project(*, github_url: str = "", external_path: str = "", cache_dir: str = "", ref: str = "", refresh: bool = False) -> ExternalProjectRef:
    if external_path:
        path = Path(external_path).expanduser().resolve()
        if not path.is_dir():
            raise FileNotFoundError(f"External project folder not found: {path}")
        return ExternalProjectRef(str(path), "local_path", str(path), ref)
    if not github_url:
        raise ValueError("Either github_url or external_path is required")
    repo = parse_github_url(github_url)
    actual_ref = ref or repo.ref
    local_path = clone_or_update(repo, cache_dir=cache_dir, ref=actual_ref, refresh=refresh)
    return ExternalProjectRef(github_url, "github", str(local_path), actual_ref)


def clone_or_update(repo: GitHubRepo, *, cache_dir: str = "", ref: str = "", refresh: bool = False) -> Path:
    root = Path(cache_dir or ".retort/cache/github").expanduser().resolve()
    target = root / repo.owner / repo.repo
    if refresh and target.exists():
        shutil.rmtree(target)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--depth", "1", repo.clone_url, str(target)], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if ref:
        subprocess.run(["git", "fetch", "--depth", "1", "origin", ref], cwd=target, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "checkout", ref], cwd=target, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return target
