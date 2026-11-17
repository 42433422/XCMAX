"""Prompt improvement proposals use GEPA trials and require Retort acceptance."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, Optional

from modstore_server.llm_crypto import decrypt_secret, encrypt_secret
from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _override_filename(employee_id: str) -> str:
    normalized = str(employee_id or "").strip()
    if (
        not normalized
        or len(normalized) > 128
        or any(not (char.isalnum() or char in {"-", "_"}) for char in normalized)
    ):
        raise ValueError("invalid employee_id for prompt override")
    return f"{normalized}.json"


def _ab_enabled() -> bool:
    return os.environ.get("MODSTORE_PROMPT_EVOLUTION_AB_ENABLED", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _override_dir() -> Path:
    raw = os.environ.get(
        "MODSTORE_PROMPT_OVERRIDE_DIR",
        "playwright-report/prompt-overrides",
    ).strip()
    try:
        from modstore_server.integrations.ops_action_handlers import repo_root

        root = Path(repo_root())
    except RECOVERABLE_ERRORS:
        root = Path(os.environ.get("MODSTORE_REPO_ROOT", ".")).resolve()
    return root / raw


def _load_prompt_override(employee_id: str) -> Optional[str]:
    try:
        filename = _override_filename(employee_id)
    except ValueError:
        return None
    path = _override_dir() / filename
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != "xcagi.prompt_override.encrypted/v1":
            return None
        encrypted = str(data.get("ciphertext") or "").strip()
        if not encrypted:
            return None
        private = json.loads(decrypt_secret(encrypted))
        if not isinstance(private, dict):
            return None
        return str(private.get("system_prompt") or "").strip() or None
    except RECOVERABLE_ERRORS:
        return None


def _write_private_override(path: Path, payload: Dict[str, Any]) -> None:
    """Encrypt the complete private payload and keep the envelope owner-only."""

    envelope = {
        "schema": "xcagi.prompt_override.encrypted/v1",
        "ciphertext": encrypt_secret(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        ),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(envelope, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    path.chmod(0o600)


def apply_prompt_override(
    employee_id: str, system_prompt: str, *, meta: Dict[str, Any]
) -> Dict[str, Any]:
    """写入 prompt override 文件（可还原）。"""
    d = _override_dir()
    d.mkdir(parents=True, exist_ok=True)
    filename = _override_filename(employee_id)
    path = d / filename
    backup_path = d / f"{filename.removesuffix('.json')}.backup.json"
    if path.is_file():
        try:
            backup_path.write_bytes(path.read_bytes())
            backup_path.chmod(0o600)
        except RECOVERABLE_ERRORS:
            pass
    payload = {
        "employee_id": employee_id,
        "system_prompt": system_prompt,
        "applied_at": datetime.now(UTC).isoformat(),
        "meta": meta,
    }
    _write_private_override(path, payload)
    return {"ok": True, "path": str(path)}


def revert_prompt_override(employee_id: str) -> Dict[str, Any]:
    d = _override_dir()
    filename = _override_filename(employee_id)
    path = d / filename
    backup = d / f"{filename.removesuffix('.json')}.backup.json"
    if backup.is_file():
        path.write_bytes(backup.read_bytes())
        path.chmod(0o600)
        return {"ok": True, "reverted_from": str(backup)}
    if path.is_file():
        path.unlink()
        return {"ok": True, "removed": True}
    return {"ok": True, "skipped": True, "reason": "no override"}


def get_effective_system_prompt(employee_id: str, manifest_prompt: str) -> str:
    """employee_runtime 可读：override 优先于 manifest。"""
    ov = _load_prompt_override(employee_id)
    return ov if ov else manifest_prompt


def run_prompt_shadow_ab(
    *, employee_id: str, prompt_before: str, prompt_after: str,
    lookback_hours: int = 24, min_wins: int = 2,
) -> Dict[str, Any]:
    """Compatibility entry: compare real trials through GEPA, never an LLM vote."""
    path = os.environ.get("MODSTORE_RETORT_RSI_PROTOCOL", "")
    if not _ab_enabled() or not path:
        return {"ok": True, "skipped": True, "improved_wins": False,
                "reason": "awaiting_measured_baseline"}
    from modstore_server.integrations.repository_packages import load_repository_module

    optimizer = load_repository_module("retort_engine.evolution_optimizer")
    result = optimizer.optimize_protocol(
        Path(path), seed={"system_prompt": prompt_before},
        proposer=lambda candidate, reflective_dataset, components_to_update:
            {key: prompt_after for key in components_to_update},
    )
    return {"ok": True, **result, "improved_wins": result["status"] == "proposed",
            "verdict": "after" if result["status"] == "proposed" else "tie"}


def maybe_auto_apply_prompt_evolution(
    *, employee_id: str, prompt_before: str, prompt_after: str,
    evolution_record_id: int = 0, lookback_hours: int = 24,
) -> Dict[str, Any]:
    """Legacy callers may propose; only the Retort approval flow may promote."""
    ab = run_prompt_shadow_ab(employee_id=employee_id, prompt_before=prompt_before,
                              prompt_after=prompt_after, lookback_hours=lookback_hours)
    return {"ok": True, "applied": False, "ab": ab,
            "reason": "awaiting_retort_acceptance" if ab.get("improved_wins") else ab.get("reason", "no_verified_improvement")}


__all__ = [
    "apply_prompt_override",
    "get_effective_system_prompt",
    "maybe_auto_apply_prompt_evolution",
    "revert_prompt_override",
    "run_prompt_shadow_ab",
]
