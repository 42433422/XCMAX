from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class BranchWorkflowState:
    enabled: bool
    project_root: str
    base_branch: str = ""
    absorption_branch: str = ""
    created: bool = False
    merged: bool = False
    status: str = "disabled"
    message: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "project_root": self.project_root,
            "base_branch": self.base_branch,
            "absorption_branch": self.absorption_branch,
            "created": self.created,
            "merged": self.merged,
            "status": self.status,
            "message": self.message,
        }


class BranchWorkflowError(RuntimeError):
    pass


def begin_absorption_branch(project_path: str | Path, *, source: str, branch_name: str = "", allow_dirty: bool = False) -> BranchWorkflowState:
    root = _git_root(Path(project_path).expanduser().resolve())
    if root is None:
        raise BranchWorkflowError("Main project folder is not inside a Git repository")
    if not allow_dirty and _git_status(root):
        raise BranchWorkflowError("Main project has uncommitted changes; commit or enable dirty branch workflow first")
    base = _git(["branch", "--show-current"], root).strip()
    if not base:
        raise BranchWorkflowError("Cannot create absorption branch from detached HEAD")
    target = branch_name or _default_branch_name(source)
    _git(["checkout", "-b", target], root)
    return BranchWorkflowState(True, str(root), base, target, True, False, "branch_created", f"Created {target} from {base}")


def merge_absorption_branch(project_path: str | Path, state: BranchWorkflowState) -> BranchWorkflowState:
    if not state.enabled or not state.absorption_branch:
        return state
    root = Path(state.project_root or project_path).resolve()
    if _git(["branch", "--show-current"], root).strip() != state.absorption_branch:
        _git(["checkout", state.absorption_branch], root)
    if _git_status(root):
        raise BranchWorkflowError("Absorption branch has uncommitted changes; commit before merge")
    _git(["checkout", state.base_branch], root)
    _git(["merge", "--no-ff", state.absorption_branch, "-m", f"Merge {state.absorption_branch}"], root)
    return BranchWorkflowState(True, str(root), state.base_branch, state.absorption_branch, state.created, True, "merged", f"Merged {state.absorption_branch} into {state.base_branch}")


def _git_root(path: Path) -> Path | None:
    try:
        result = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=path, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return Path(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else None


def _git_status(root: Path) -> str:
    return _git(["status", "--short"], root)


def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False)
    if result.returncode != 0:
        raise BranchWorkflowError(result.stderr.strip() or result.stdout.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def _default_branch_name(source: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", source).strip("-").lower()[:48] or "source"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"retort/absorb-{slug}-{stamp}"
