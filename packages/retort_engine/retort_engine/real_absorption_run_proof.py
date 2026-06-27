from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retort_engine.codebase_graph import code_graph_absorption_proof


REQUIRED_PROOF_STYLE = "deterministic_post_absorption_code_graph"


def build_per_run_code_graph_proof(
    project: str | Path,
    *,
    run_id: str,
    changed_files: list[str],
    pre_absorption_focus: dict[str, Any] | None = None,
    max_files: int = 400,
) -> dict[str, Any]:
    """Build the code graph proof that must travel with this absorption run."""
    proof = code_graph_absorption_proof(project, changed_files, pre_absorption_focus, max_files=max_files)
    proof["run_id"] = run_id
    proof["per_run_required"] = True
    proof.setdefault("summary", {})["changed_file_count"] = len(changed_files)
    evidence = proof.setdefault("evidence", {})
    evidence["scope"] = "per_real_absorption_run"
    evidence["run_id"] = run_id
    return proof


def code_graph_proof_gate(proof: dict[str, Any], *, run_id: str, started: float | None = None) -> dict[str, Any]:
    """Return a gate proving that this run generated its own code graph proof."""
    started_at = started if started is not None else time.monotonic()
    missing = per_run_code_graph_proof_missing(proof, run_id=run_id)
    return {
        "command": ["retort", "verify-per-run-code-graph-proof", run_id],
        "cwd": "",
        "exit_code": 0 if not missing else 1,
        "ok": not missing,
        "duration_sec": round(time.monotonic() - started_at, 3),
        "stdout_tail": "per-run code graph proof generated" if not missing else "",
        "stderr_tail": "\n".join(missing),
        "proof_status": str(proof.get("status") or ""),
        "proof_passed": bool(proof.get("passed")),
    }


def per_run_code_graph_proof_missing(proof: dict[str, Any] | None, *, run_id: str) -> list[str]:
    if not isinstance(proof, dict) or not proof:
        return ["missing_per_run_code_graph_proof"]
    missing: list[str] = []
    if proof.get("run_id") != run_id:
        missing.append("code_graph_proof_run_id_mismatch")
    if proof.get("per_run_required") is not True:
        missing.append("code_graph_proof_not_marked_per_run")
    evidence = proof.get("evidence") if isinstance(proof.get("evidence"), dict) else {}
    if evidence.get("style") != REQUIRED_PROOF_STYLE:
        missing.append("code_graph_proof_style_missing")
    if evidence.get("scope") != "per_real_absorption_run":
        missing.append("code_graph_proof_scope_missing")
    summary = proof.get("summary") if isinstance(proof.get("summary"), dict) else {}
    if "graph_status" not in summary:
        missing.append("code_graph_proof_graph_status_missing")
    if "changed_file_count" not in summary:
        missing.append("code_graph_proof_changed_file_count_missing")
    return missing


def record_real_absorption_run(root: Path, result: dict[str, Any]) -> Path:
    """Persist a real absorption run only after its per-run graph proof exists."""
    run_id = str(result.get("run_id") or "run")
    missing = per_run_code_graph_proof_missing(result.get("code_graph_proof"), run_id=run_id)
    if missing:
        raise RuntimeError(f"real absorption run missing per-run code graph proof: {', '.join(missing)}")
    path = root / ".retort" / "real_absorption_runs" / f"{run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(result)
    payload["run_recorded_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload["run_record_path"] = str(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path
