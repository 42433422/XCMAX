from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from retort_engine.project_assessment import project_files


PROFILE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".yaml", ".yml", ".json", ".toml"}


def materialize_external_source(source: str, own_project: Path, refresh: bool = False) -> Path | None:
    if not source:
        return None
    path = Path(source).expanduser()
    if path.is_dir():
        return path.resolve()
    repo = parse_github_url(source)
    if repo is None:
        return None
    owner, name = repo
    target = own_project / ".retort" / "cache" / "github" / owner / name
    if refresh and target.exists():
        shutil.rmtree(target)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        run_git_clone(f"https://github.com/{owner}/{name}.git", target)
    return target


def parse_github_url(source: str) -> tuple[str, str] | None:
    match = re.search(r"github\.com[:/](?P<owner>[^/\s#?]+)/(?P<repo>[^/\s#?]+)", source)
    if not match:
        return None
    return match.group("owner"), match.group("repo").removesuffix(".git")


def run_git_clone(url: str, target: Path) -> None:
    result = subprocess.run(
        ["git", "clone", "--depth", "1", url, str(target)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())


def external_project_profile(path: Path | None) -> dict[str, bool]:
    if path is None or not path.is_dir():
        return {}
    files = project_files(path, {".git", "__pycache__", "node_modules"})
    text = "\n".join(read_text(file)[:20000] for file in files[:250] if file.suffix.lower() in PROFILE_SUFFIXES)
    lowered = text.lower()
    return {
        "review_pipeline": any(marker in lowered for marker in ("code review", "review pipeline", "reviewer", "reflection", "localization")),
        "file_grouping": any(marker in lowered for marker in ("file group", "group files", "changed files", "diff hunk", "patch set")),
        "benchmarking": any(marker in lowered for marker in ("benchmark", "precision", "recall", "eval", "evaluation")),
        "plugin_surface": any(marker in lowered for marker in ("plugin", "cli", "github action", "codex")),
    }


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
