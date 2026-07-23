"""Deterministic, read-only QA execution receipt validator."""

from __future__ import annotations

import re
from typing import Any

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def run(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    qa_run = payload.get("qa_run")
    if not isinstance(qa_run, dict):
        return _failed("qa_run object is required", "missing_qa_run")

    command = str(qa_run.get("command") or "").strip()
    counts = (qa_run.get("total"), qa_run.get("passed"), qa_run.get("failed"))
    blockers: list[str] = []
    if not command:
        blockers.append("command_missing")
    if not all(isinstance(value, int) and value >= 0 for value in counts):
        blockers.append("test_counts_invalid")
    else:
        total, passed, failed = counts
        if passed + failed != total:
            blockers.append("test_counts_inconsistent")
        if failed:
            blockers.append("tests_failed")
    if qa_run.get("exit_code") != 0:
        blockers.append("exit_code_nonzero")
    artifact_sha256 = str(qa_run.get("artifact_sha256") or "").strip().lower()
    if not _SHA256_RE.fullmatch(artifact_sha256):
        blockers.append("artifact_sha256_invalid")

    approved = not blockers
    return {
        "ok": True,
        "status": "approved" if approved else "rejected",
        "summary": (
            f"QA 执行回执已确定性只读核验：命令与 {qa_run.get('total', 0)} 项测试结果"
            f"{'可放行' if approved else '不可放行'}，{len(blockers)} 个阻塞项；未重跑或修改测试。"
        ),
        "release_allowed": approved,
        "blockers": blockers,
        "evidence": ["qa_run.command", "qa_run test counts", "qa_run.artifact_sha256"],
        "read_only": True,
        "side_effects": [],
    }


def _failed(message: str, code: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "failed",
        "summary": message,
        "error_code": code,
        "evidence": [],
        "read_only": True,
        "side_effects": [],
    }
