from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def build_product_mainline_absorption_proof(project: str | Path, *, output: str | Path = "", commit: str = "HEAD") -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    git_root = _git(["rev-parse", "--show-toplevel"], root)["stdout"].strip()
    repo = Path(git_root) if git_root else root
    commit_sha = _git(["rev-parse", commit], repo)["stdout"].strip()
    parents = _git(["show", "-s", "--format=%P", commit_sha], repo)["stdout"].strip().split()
    parent = parents[0] if parents else f"{commit_sha}^"
    changed_files = _git(["diff", "--name-only", parent, commit_sha, "--", "packages/retort_engine"], repo)["stdout"].splitlines()
    source_files = [item for item in changed_files if item.startswith("packages/retort_engine/retort_engine/") and item.endswith(".py")]
    test_files = [item for item in changed_files if item.startswith("packages/retort_engine/tests/test_") and item.endswith(".py")]
    docs_files = [item for item in changed_files if item.startswith("packages/retort_engine/docs/")]
    quality = _read_json(root / "docs" / "retort_quality_gate_bundle.json")
    quality_summary = quality.get("summary") if isinstance(quality.get("summary"), dict) else {}
    summary = {
        "commit": commit_sha,
        "parent_count": len(parents),
        "is_merge_commit": len(parents) >= 2,
        "first_parent": parent,
        "changed_file_count": len(changed_files),
        "behavior_source_changed_count": len(source_files),
        "behavior_test_changed_count": len(test_files),
        "docs_changed_count": len(docs_files),
        "docs_only": bool(changed_files) and len(changed_files) == len(docs_files),
        "post_merge_quality_gate_passed": quality.get("status") == "ready" and quality_summary.get("all_gates_passed") is True,
        "test_to_source_ratio": quality_summary.get("test_to_source_ratio", ""),
        "contract_schema_count": quality_summary.get("contract_schema_count", ""),
    }
    ready = (
        summary["is_merge_commit"]
        and summary["behavior_source_changed_count"] > 0
        and summary["behavior_test_changed_count"] > 0
        and summary["docs_only"] is False
        and summary["post_merge_quality_gate_passed"]
    )
    result = {
        "status": "ready" if ready else "needs_product_mainline_absorption_merge",
        "project": str(root),
        "summary": summary,
        "changed_files": changed_files,
        "source_files": source_files,
        "test_files": test_files,
        "evidence": {
            "style": "product_mainline_merge_commit_with_behavior_code_and_tests",
            "git_range": f"{parent}..{commit_sha}",
            "quality_report": "docs/retort_quality_gate_bundle.json",
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _git(args: list[str], cwd: Path) -> dict[str, Any]:
    completed = subprocess.run(["git", *args], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    return {"returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
