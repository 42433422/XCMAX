"""Fail-closed Persy / Para / Retort strategic council receipts.

The change-request-auditor already delegates to this contract.  A council
receipt is accepted only when all three seats are backed by evidence and the
veto channel is clear.  Every attempt is written to a hash-chained JSONL
ledger; the read side refuses to report readiness when that chain is broken.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from modstore_server.strategic_council_live import (
    live_para_evidence as _live_para_evidence,
    live_persy_evidence as _live_persy_evidence,
    live_veto_state as _live_veto_state,
    strategic_council_status,
)

SCHEMA_VERSION = "xcmax.strategic_council_receipt/v1"
STATUS_SCHEMA_VERSION = "xcmax.strategic_council_status/v1"
LEDGER_FILENAME = "strategic_council_receipts.jsonl"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _text(value: Any, limit: int = 512) -> str:
    return str(value or "").strip()[:limit]


def _runtime_dir() -> Path:
    return Path(os.environ.get("MODSTORE_RUNTIME_DIR") or "/tmp/modstore_runtime").expanduser()


def strategic_council_ledger_path() -> Path:
    configured = _text(os.environ.get("MODSTORE_STRATEGIC_COUNCIL_LEDGER"), 4096)
    return Path(configured).expanduser() if configured else _runtime_dir() / LEDGER_FILENAME


def _retort_import_root() -> Path:
    configured = _text(os.environ.get("MODSTORE_RETORT_ENGINE_ROOT"), 4096)
    if configured:
        return Path(configured).expanduser().resolve()
    monorepo = _text(os.environ.get("XCMAX_MONOREPO_ROOT"), 4096)
    root = (
        Path(monorepo).expanduser().resolve() if monorepo else Path(__file__).resolve().parents[3]
    )
    return root / "packages" / "retort_engine"


def _load_retort_alignment() -> Callable[..., dict[str, Any]]:
    try:
        from retort_engine.intent_alignment import assess_change_intent_alignment

        return assess_change_intent_alignment
    except ImportError:
        package_root = _retort_import_root()
        if package_root.is_dir() and str(package_root) not in sys.path:
            sys.path.insert(0, str(package_root))
        from retort_engine.intent_alignment import assess_change_intent_alignment

        return assess_change_intent_alignment


def _retort_result(
    changed_files: Sequence[Any],
    strategy_intent: str,
    *,
    proposal_id: str = "",
    run_id: str = "",
    package_id: str = "",
    change_request_id: int | None = None,
) -> tuple[dict[str, Any], list[str], str]:
    """Evaluate Retort seat with clarification gate.

    Returns ``(role_payload, blockers, effective_strategy_intent)``.
    """

    blockers: list[str] = []
    normalized: list[dict[str, Any]] = []
    for item in changed_files:
        if isinstance(item, str):
            path = _text(item, 1024)
            if path:
                normalized.append({"path": path, "hunks": []})
        elif isinstance(item, Mapping):
            path = _text(item.get("path"), 1024)
            if path:
                normalized.append(
                    {
                        "path": path,
                        "hunks": item.get("hunks") if isinstance(item.get("hunks"), list) else [],
                    }
                )
    if not normalized:
        blockers.append("retort_changed_files_missing")

    effective_intent = strategy_intent
    clarification: dict[str, Any] = {}
    try:
        from modstore_server.retort_clarification_gate import (
            evaluate_retort_clarification_gate,
            gate_enabled,
        )

        if gate_enabled():
            gate = evaluate_retort_clarification_gate(
                strategy_intent=strategy_intent,
                changed_files=normalized,
                change_request_id=change_request_id,
                proposal_id=proposal_id,
                run_id=run_id,
                package_id=package_id,
                auto_open=True,
            )
            effective_intent = _text(gate.get("effective_strategy_intent") or strategy_intent, 4000)
            clarification = (
                gate.get("clarification") if isinstance(gate.get("clarification"), dict) else {}
            )
            blockers.extend(list(gate.get("blockers") or []))
            assessment = gate.get("assessment") if isinstance(gate.get("assessment"), dict) else {}
            engine_available = True
        else:
            raise RuntimeError("clarification_gate_disabled")
    except Exception:
        # Fallback to legacy keyword alignment when gate import/runtime fails.
        if not strategy_intent:
            blockers.append("retort_strategy_intent_missing")
        try:
            assess = _load_retort_alignment()
            assessment = assess(normalized, issue_context=strategy_intent)
            engine_available = True
        except Exception as exc:  # noqa: BLE001 - engine failures must become a closed gate
            assessment = {"status": "engine_unavailable", "error": type(exc).__name__}
            engine_available = False
            blockers.append("retort_engine_unavailable")
        if engine_available and assessment.get("status") != "aligned":
            blockers.append("retort_intent_misaligned")

    if not effective_intent and "retort_strategy_intent_missing" not in blockers:
        blockers.append("retort_strategy_intent_missing")

    aligned = (
        engine_available
        and assessment.get("status") == "aligned"
        and "retort_clarification_pending" not in blockers
        and "retort_clarification_expired" not in blockers
        and "retort_clarification_cancelled" not in blockers
        and "retort_intent_misaligned" not in blockers
        and "retort_engine_unavailable" not in blockers
    )
    if engine_available and assessment.get("status") != "aligned":
        if (
            "retort_intent_misaligned" not in blockers
            and "retort_clarification_pending" not in blockers
        ):
            blockers.append("retort_intent_misaligned")

    blockers = list(dict.fromkeys(blockers))
    summary = assessment.get("summary") if isinstance(assessment.get("summary"), dict) else {}
    return (
        {
            "status": "aligned" if aligned else "blocked",
            "engine_available": engine_available,
            "assessment_status": _text(assessment.get("status"), 64),
            "overlap_keyword_count": int(summary.get("overlap_keyword_count") or 0),
            "changed_file_count": len(normalized),
            "changed_files_sha256": _digest([item["path"] for item in normalized]),
            "clarification_status": _text(clarification.get("status"), 32),
            "clarification_session_id": _text(clarification.get("session_id"), 128),
            "clarification_question_count": len(clarification.get("questions") or []),
            "effective_strategy_intent_sha256": _digest(effective_intent),
        },
        blockers,
        effective_intent,
    )


def _persy_result(evidence: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    refs = evidence.get("document_refs")
    if not isinstance(refs, list):
        refs = evidence.get("sources") if isinstance(evidence.get("sources"), list) else []
    refs = [_text(item, 256) for item in refs if _text(item, 256)][:20]
    source_count = int(evidence.get("source_count") or len(refs) or 0)
    grounded = evidence.get("grounded") is True and source_count > 0
    blockers = [] if grounded else ["persy_grounding_missing"]
    return (
        {
            "status": "grounded" if grounded else "blocked",
            "dataset_id": _text(evidence.get("dataset_id") or "persy-knowledge", 128),
            "source_count": source_count,
            "document_refs": refs,
            "evidence_sha256": _digest(dict(evidence)),
        },
        blockers,
    )


def _para_result(
    evidence: Mapping[str, Any], *, goal_id: str, loop_run_id: str, para_task_id: str
) -> tuple[dict[str, Any], list[str]]:
    evidence_goal = _text(evidence.get("goal_id"), 128)
    evidence_loop = _text(evidence.get("loop_run_id"), 128)
    evidence_task = _text(evidence.get("para_task_id") or evidence.get("task_id"), 128)
    links_match = (
        bool(goal_id and loop_run_id and para_task_id)
        and evidence_goal == goal_id
        and evidence_loop == loop_run_id
        and evidence_task == para_task_id
    )
    source_verified = evidence.get("source_verified") is True
    linked = evidence.get("linked") is True and links_match and source_verified
    blockers: list[str] = []
    if not goal_id:
        blockers.append("para_goal_id_missing")
    if not loop_run_id:
        blockers.append("para_loop_run_id_missing")
    if not para_task_id:
        blockers.append("para_task_id_missing")
    if goal_id and loop_run_id and para_task_id and not links_match:
        blockers.append("para_links_mismatch")
    if links_match and not source_verified:
        blockers.append("para_source_unverified")
    if links_match and source_verified and evidence.get("linked") is not True:
        blockers.append("para_link_not_confirmed")
    return (
        {
            "status": "linked" if linked else "blocked",
            "goal_id": goal_id,
            "loop_run_id": loop_run_id,
            "para_task_id": para_task_id,
            "goal_status": _text(evidence.get("goal_status"), 64),
            "loop_status": _text(evidence.get("loop_status"), 64),
            "task_status": _text(evidence.get("task_status"), 64),
            "source": _text(evidence.get("source"), 128),
            "source_verified": source_verified,
            "evidence_sha256": _digest(dict(evidence)),
        },
        blockers,
    )


def _veto_result(state: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    available = state.get("available") is True
    vetoed = state.get("vetoed") is True
    pending_count = int(state.get("pending_count") or 0)
    blockers: list[str] = []
    if not available:
        blockers.append("veto_channel_unavailable")
    if vetoed:
        blockers.append("veto_active")
    if pending_count > 0:
        blockers.append("veto_pending")
    return (
        {
            "available": available,
            "vetoed": vetoed,
            "pending_count": pending_count,
            "source": _text(state.get("source"), 128),
            "state_sha256": _digest(dict(state)),
        },
        blockers,
    )


def _read_rows_unlocked(file_obj: Any) -> list[dict[str, Any]]:
    file_obj.seek(0)
    rows: list[dict[str, Any]] = []
    for raw in file_obj:
        try:
            item = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            rows.append(
                {
                    "_malformed": True,
                    "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                }
            )
            continue
        rows.append(item if isinstance(item, dict) else {"_malformed": True})
    return rows


def _verify_rows(rows: Iterable[Mapping[str, Any]]) -> tuple[bool, str]:
    previous = ""
    for row in rows:
        if row.get("_malformed"):
            return False, previous
        candidate = dict(row)
        record_hash = _text(candidate.pop("record_hash", ""), 64)
        if _text(candidate.get("previous_record_hash"), 64) != previous:
            return False, previous
        expected = _digest(candidate)
        if not _SHA256_RE.fullmatch(record_hash) or record_hash != expected:
            return False, previous
        previous = record_hash
    return True, previous


def _append_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    path = strategic_council_ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as file_obj:
        try:
            import fcntl

            fcntl.flock(file_obj.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        rows = _read_rows_unlocked(file_obj)
        integrity_ok, previous = _verify_rows(rows)
        if not integrity_ok:
            raise RuntimeError("strategic council ledger integrity check failed")
        request_sha256 = _text(receipt.get("request_sha256"), 64)
        for existing in rows:
            if _text(existing.get("request_sha256"), 64) == request_sha256:
                return dict(existing)
        record = dict(receipt)
        record["previous_record_hash"] = previous
        record["record_hash"] = _digest(record)
        file_obj.seek(0, os.SEEK_END)
        file_obj.write(_canonical_json(record) + "\n")
        file_obj.flush()
        os.fsync(file_obj.fileno())
        return record


def build_strategic_council_receipt(
    *,
    proposal_id: str,
    run_id: str,
    package_id: str,
    version: str,
    package_sha256: str,
    goal_id: str,
    loop_run_id: str,
    para_task_id: str,
    strategy_intent: str,
    changed_files: Sequence[Any],
    persy_evidence: Mapping[str, Any],
    para_evidence: Mapping[str, Any],
    veto_state: Mapping[str, Any],
    change_request_id: int | None = None,
) -> dict[str, Any]:
    """Validate the three seats and append one content-addressed receipt."""

    proposal_id = _text(proposal_id, 128)
    run_id = _text(run_id, 128)
    package_id = _text(package_id, 128)
    version = _text(version, 64)
    package_sha256 = _text(package_sha256, 64).lower()
    goal_id = _text(goal_id, 128)
    loop_run_id = _text(loop_run_id, 128)
    para_task_id = _text(para_task_id, 128)
    strategy_intent = _text(strategy_intent, 4000)

    blockers: list[str] = []
    for key, value in (
        ("proposal_id", proposal_id),
        ("run_id", run_id),
        ("package_id", package_id),
        ("version", version),
    ):
        if not value:
            blockers.append(f"{key}_missing")
    if not _SHA256_RE.fullmatch(package_sha256):
        blockers.append("package_sha256_invalid")

    persy, persy_blockers = _persy_result(persy_evidence)
    para, para_blockers = _para_result(
        para_evidence,
        goal_id=goal_id,
        loop_run_id=loop_run_id,
        para_task_id=para_task_id,
    )
    retort, retort_blockers, effective_intent = _retort_result(
        changed_files,
        strategy_intent,
        proposal_id=proposal_id,
        run_id=run_id,
        package_id=package_id,
        change_request_id=change_request_id,
    )
    veto, veto_blockers = _veto_result(veto_state)
    blockers.extend(persy_blockers + para_blockers + retort_blockers + veto_blockers)
    blockers = list(dict.fromkeys(blockers))

    request = {
        "proposal_id": proposal_id,
        "run_id": run_id,
        "package_id": package_id,
        "version": version,
        "package_sha256": package_sha256,
        "goal_id": goal_id,
        "loop_run_id": loop_run_id,
        "para_task_id": para_task_id,
        "strategy_intent_sha256": _digest(strategy_intent),
        "effective_strategy_intent_sha256": _digest(effective_intent),
        "persy_evidence_sha256": persy["evidence_sha256"],
        "para_evidence_sha256": para["evidence_sha256"],
        "retort_evidence_sha256": _digest(retort),
        "veto_state_sha256": veto["state_sha256"],
    }
    request_sha256 = _digest(request)
    receipt = {
        "schema": SCHEMA_VERSION,
        "receipt_id": f"council-{request_sha256[:32]}",
        "request_sha256": request_sha256,
        "created_at": _now_iso(),
        **request,
        "roles": {"persy": persy, "para": para, "retort": retort},
        "veto": veto,
        "blockers": blockers,
        "verified": not blockers,
    }
    return _append_receipt(receipt)


def build_live_strategic_council_receipt(
    *,
    proposal_id: str,
    run_id: str,
    package_id: str,
    version: str,
    package_sha256: str,
    goal_id: str,
    loop_run_id: str,
    para_task_id: str,
    strategy_intent: str,
    changed_files: Sequence[Any],
) -> dict[str, Any]:
    """Build a receipt from live Persy, strategic-Goal, Loop, Para and veto sources."""

    return build_strategic_council_receipt(
        proposal_id=proposal_id,
        run_id=run_id,
        package_id=package_id,
        version=version,
        package_sha256=package_sha256,
        goal_id=goal_id,
        loop_run_id=loop_run_id,
        para_task_id=para_task_id,
        strategy_intent=strategy_intent,
        changed_files=changed_files,
        persy_evidence=_live_persy_evidence(strategy_intent),
        para_evidence=_live_para_evidence(
            goal_id=goal_id,
            loop_run_id=loop_run_id,
            para_task_id=para_task_id,
        ),
        veto_state=_live_veto_state(run_id=run_id, loop_run_id=loop_run_id),
    )


__all__ = [
    "build_live_strategic_council_receipt",
    "build_strategic_council_receipt",
    "strategic_council_ledger_path",
    "strategic_council_status",
]
