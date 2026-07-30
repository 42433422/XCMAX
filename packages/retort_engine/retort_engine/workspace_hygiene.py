from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

# Closed-loop proof flags may remain. Everything else under .retort is runtime residue.
DURABLE_RELATIVE_PATHS = frozenset(
    {
        "absorption_state.json",
    }
)

EPHEMERAL_DIR_NAMES = frozenset(
    {
        "cache",
        "trajectories",
        "employee_results",
        "employee_runtime_requests",
        "employee_patch_closures",
        "employee_patch_stress",
        "real_absorption_runs",
        "execution_requests",
        "review_family_behavior_replays",
        "paibi_cli_cross_adjudications",
        "external_process_adjudications",
        "external_merge_landings",
        "operator_journey_replays",
        "self_bootstrap_absorptions",
        "runs",
    }
)

EPHEMERAL_FILE_NAMES = frozenset(
    {
        "employee_queue.jsonl",
        "retort_history.sqlite",
        "self_evolution_actions.jsonl",
        "paibi_llm_outbox.jsonl",
        "llm_reviews.jsonl",
        "pre_frontier_baseline.json",
    }
)


def retort_runtime_root(project: str | Path) -> Path:
    return Path(project).expanduser().resolve() / ".retort"


def clean_workspace(
    project: str | Path,
    *,
    keep_durable_state: bool = True,
    purge_empty_runtime: bool = True,
) -> dict[str, Any]:
    """Remove Retort runtime residue so the project returns to a clean workspace.

    Durable closed-loop state (absorption_state.json) may be kept. GitHub clones,
    trajectories, employee payloads, labs, sqlite/jsonl queues, and caches are
    always treated as ephemeral and deleted.
    """
    root = Path(project).expanduser().resolve()
    runtime = retort_runtime_root(root)
    removed: list[str] = []
    kept: list[str] = []
    errors: list[str] = []
    if not runtime.exists():
        return {
            "status": "clean",
            "project": str(root),
            "runtime_root": str(runtime),
            "removed": [],
            "kept": [],
            "errors": [],
            "summary": {
                "removed_count": 0,
                "kept_count": 0,
                "residue_bytes": 0,
                "clean": True,
            },
        }

    for path in sorted(runtime.iterdir(), key=lambda item: item.name):
        rel = path.name
        if keep_durable_state and rel in DURABLE_RELATIVE_PATHS and path.is_file():
            kept.append(str(path.relative_to(root)))
            continue
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
            removed.append(str(path.relative_to(root)))
        except OSError as exc:
            errors.append(f"{rel}: {exc}")

    if purge_empty_runtime and runtime.exists() and not any(runtime.iterdir()):
        try:
            runtime.rmdir()
            removed.append(".retort")
        except OSError as exc:
            errors.append(f".retort: {exc}")

    residue = workspace_residue_report(root, keep_durable_state=keep_durable_state)
    return {
        "status": (
            "clean"
            if residue["clean"] and not errors
            else ("partial" if removed else "dirty")
        ),
        "project": str(root),
        "runtime_root": str(runtime),
        "removed": removed,
        "kept": kept,
        "errors": errors,
        "summary": {
            "removed_count": len(removed),
            "kept_count": len(kept),
            "error_count": len(errors),
            "residue_bytes": residue["residue_bytes"],
            "clean": bool(residue["clean"] and not errors),
        },
        "residue": residue,
    }


def workspace_residue_report(
    project: str | Path, *, keep_durable_state: bool = True
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    runtime = retort_runtime_root(root)
    residues: list[dict[str, Any]] = []
    if runtime.exists():
        for path in sorted(runtime.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if (
                keep_durable_state
                and path.relative_to(runtime).as_posix() in DURABLE_RELATIVE_PATHS
            ):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            residues.append({"path": rel, "bytes": size})
    residue_bytes = sum(int(item["bytes"]) for item in residues)
    return {
        "clean": not residues,
        "residue_count": len(residues),
        "residue_bytes": residue_bytes,
        "residues": residues[:100],
        "policy": {
            "durable_paths": sorted(DURABLE_RELATIVE_PATHS),
            "ephemeral_dirs": sorted(EPHEMERAL_DIR_NAMES),
            "ephemeral_files": sorted(EPHEMERAL_FILE_NAMES),
            "first_principle": "clean_workspace_after_every_closed_run",
        },
    }


def assert_clean_workspace(
    project: str | Path, *, keep_durable_state: bool = True
) -> dict[str, Any]:
    report = workspace_residue_report(project, keep_durable_state=keep_durable_state)
    if not report["clean"]:
        raise RuntimeError(
            "Retort workspace is dirty after run; "
            f"{report['residue_count']} residue file(s), {report['residue_bytes']} bytes remain under .retort"
        )
    return report


def close_run_workspace(project: str | Path, *, run_id: str = "") -> dict[str, Any]:
    """Mandatory end-of-run closer: purge ephemeral residue and prove cleanliness."""
    cleaned = clean_workspace(
        project, keep_durable_state=True, purge_empty_runtime=True
    )
    proof = workspace_residue_report(project, keep_durable_state=True)
    return {
        "status": "closed" if proof["clean"] else "residue_remaining",
        "run_id": run_id,
        "cleaned": cleaned,
        "proof": proof,
        "summary": {
            "closed": proof["clean"],
            "removed_count": cleaned["summary"]["removed_count"],
            "residue_bytes": proof["residue_bytes"],
        },
    }
