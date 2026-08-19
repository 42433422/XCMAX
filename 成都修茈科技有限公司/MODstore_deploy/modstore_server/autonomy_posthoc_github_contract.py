"""Validation of the guarded Para-generated pull-request merge contract."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_TASK_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_REQUIRED_CHECKS = frozenset({"release-verify", "review", "security-scan"})


def generated_para_merge_contract_verdict(
    *,
    pull: dict[str, Any],
    checks: list[dict[str, Any]],
    expected_task_id: str,
    branch: str,
    base_branch: str,
) -> dict[str, Any]:
    task_id = str(expected_task_id or "").strip()
    if not _TASK_ID.fullmatch(task_id):
        return {"ok": False, "reason": "github_para_task_id_invalid"}
    body = str(pull.get("body") or "")
    required_markers = (
        "## Para 自动派工产物",
        f"**任务 ID**: {task_id}",
        f"**工作分支**: `{branch}`",
        f"**目标分支**: `{base_branch}`",
        "本 PR 由 merge-worker 自动创建",
        "AI review APPROVE",
        "`risk:r0`",
        "`hold-merge`",
        "`github-actions[bot]`",
    )
    if any(marker not in body for marker in required_markers):
        return {"ok": False, "reason": "github_para_generated_contract_missing"}

    labels = pull.get("labels") if isinstance(pull.get("labels"), list) else []
    label_names = {
        str(label.get("name") or "").strip().lower() for label in labels if isinstance(label, dict)
    }
    if "risk:r0" not in label_names or "hold-merge" in label_names:
        return {"ok": False, "reason": "github_para_merge_labels_invalid"}
    merged_by = pull.get("merged_by") if isinstance(pull.get("merged_by"), dict) else {}
    if str(merged_by.get("login") or "").strip().lower() != "github-actions[bot]":
        return {"ok": False, "reason": "github_para_merge_actor_invalid"}

    successful_checks = {
        str(check.get("name") or "").strip()
        for check in checks
        if isinstance(check, dict)
        and str(check.get("status") or "").lower() == "completed"
        and str(check.get("conclusion") or "").lower() == "success"
        and str(
            (check.get("app") if isinstance(check.get("app"), dict) else {}).get("slug") or ""
        ).lower()
        == "github-actions"
    }
    missing_checks = sorted(_REQUIRED_CHECKS - successful_checks)
    if missing_checks:
        return {
            "ok": False,
            "reason": "github_para_required_checks_missing",
            "missing_checks": missing_checks,
        }

    contract_digest = hashlib.sha256(
        json.dumps(
            {
                "base_branch": base_branch,
                "branch": branch,
                "labels": sorted(label_names),
                "merge_actor": "github-actions[bot]",
                "required_checks": sorted(_REQUIRED_CHECKS),
                "task_id": task_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "ok": True,
        "contract_digest": contract_digest,
        "reason": "github_para_generated_merge_contract_verified",
    }


__all__ = ["generated_para_merge_contract_verdict"]
