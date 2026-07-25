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


def _live_persy_evidence(strategy_intent: str) -> dict[str, Any]:
    """Retrieve real Persy chunks and retain only source identities/digests."""

    try:
        from modstore_server.xiaoc_cs_ssot import retrieve_knowledge_for_mode

        chunks = retrieve_knowledge_for_mode(strategy_intent, mode="admin", top_k=5)
    except Exception as exc:  # noqa: BLE001 - absence must fail closed in the receipt
        return {
            "grounded": False,
            "dataset_id": "persy-knowledge",
            "source_count": 0,
            "document_refs": [],
            "error": type(exc).__name__,
        }
    refs: list[str] = []
    evidence_rows: list[dict[str, str]] = []
    for index, chunk in enumerate(chunks if isinstance(chunks, list) else []):
        if not isinstance(chunk, dict):
            continue
        ref = ""
        for key in (
            "document_id",
            "source_id",
            "chunk_id",
            "id",
            "source_name",
            "source",
        ):
            ref = _text(chunk.get(key), 256)
            if ref:
                break
        if not ref:
            ref = f"chunk-{index + 1}-{_digest(chunk)[:16]}"
        refs.append(ref)
        evidence_rows.append({"ref": ref, "sha256": _digest(chunk)})
    return {
        "grounded": bool(refs),
        "dataset_id": "persy-knowledge",
        "source_count": len(refs),
        "document_refs": refs,
        "query_sha256": _digest(strategy_intent),
        "retrieval_sha256": _digest(evidence_rows),
        "source": "persy_live_retrieval",
    }


def _live_para_evidence(*, goal_id: str, loop_run_id: str, para_task_id: str) -> dict[str, Any]:
    """Verify Goal and Para linkage against the strategic DB and Loop ledger."""

    goal_status = ""
    try:
        from modstore_server.db.base import get_session_factory
        from modstore_server.db.strategic import StrategicDecision

        with get_session_factory()() as session:
            goal = (
                session.query(StrategicDecision)
                .filter(StrategicDecision.decision_id == goal_id)
                .first()
            )
            goal_status = _text(getattr(goal, "status", ""), 64) if goal is not None else ""
    except Exception:  # noqa: BLE001 - represented as source_verified=false
        goal_status = ""

    loop_rows: list[dict[str, Any]] = []
    try:
        from modstore_server.self_maintenance_loop_runner import _read_ledger

        loop_rows = [
            row
            for row in _read_ledger(limit=20_000)
            if _text(row.get("run_id"), 128) == loop_run_id
        ]
    except Exception:  # noqa: BLE001 - represented as source_verified=false
        loop_rows = []
    linked_rows = [
        row
        for row in loop_rows
        if _text(row.get("para_task_id") or row.get("task_id"), 128) == para_task_id
    ]
    latest = loop_rows[-1] if loop_rows else {}
    return {
        "linked": bool(goal_status and linked_rows),
        "source_verified": bool(goal_status and linked_rows),
        "goal_id": goal_id,
        "loop_run_id": loop_run_id,
        "para_task_id": para_task_id,
        "goal_status": goal_status,
        "loop_status": _text(latest.get("status") or latest.get("phase"), 64),
        "task_status": _text(linked_rows[-1].get("status"), 64) if linked_rows else "",
        "source": "strategic_decisions+self_maintenance_loop_ledger",
        "loop_evidence_sha256": _digest(linked_rows),
    }


def _live_veto_state(*, run_id: str, loop_run_id: str) -> dict[str, Any]:
    """Read the existing redline channel and immutable autonomy audit."""

    try:
        from modstore_server.autonomy_decision_audit import (
            build_autonomy_decision_evidence,
        )
        from modstore_server.redline_approval_gate import get_pending_redline_requests

        pending = get_pending_redline_requests()
        audit = build_autonomy_decision_evidence(window_days=30, limit=1000)
        rows = audit.get("items") if isinstance(audit.get("items"), list) else []
        correlated_vetoes = [
            row
            for row in rows
            if isinstance(row, dict)
            and _text(row.get("decision"), 32) == "veto"
            and _text(row.get("run_id"), 128) in {run_id, loop_run_id}
        ]
        return {
            "available": True,
            "vetoed": bool(correlated_vetoes),
            "pending_count": len(pending),
            "source": "redline_approval+autonomy_decision_audit",
            "audit_append_only_enforced": audit.get("append_only_enforced") is True,
            "correlated_veto_count": len(correlated_vetoes),
        }
    except Exception as exc:  # noqa: BLE001 - absence must fail closed
        return {
            "available": False,
            "vetoed": False,
            "pending_count": 0,
            "source": "redline_approval+autonomy_decision_audit",
            "error": type(exc).__name__,
        }


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


def _public_receipt(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in (
            "receipt_id",
            "created_at",
            "proposal_id",
            "run_id",
            "package_id",
            "version",
            "package_sha256",
            "goal_id",
            "loop_run_id",
            "para_task_id",
            "request_sha256",
            "record_hash",
            "verified",
            "blockers",
            "roles",
            "veto",
        )
    }


def strategic_council_status(*, limit: int = 20) -> dict[str, Any]:
    clarification_summary: dict[str, Any] = {}
    try:
        from modstore_server.retort_clarification_gate import (
            list_clarifications,
            sweep_expired_clarifications,
        )

        sweep_expired_clarifications()
        clarification_summary = list_clarifications(include_terminal=False, limit=20)
    except Exception as exc:  # noqa: BLE001 - status must still return council ledger
        clarification_summary = {"ok": False, "error": type(exc).__name__, "open_count": 0}

    path = strategic_council_ledger_path()
    if not path.is_file():
        return {
            "schema": STATUS_SCHEMA_VERSION,
            "ok": True,
            "ready": False,
            "append_only": True,
            "hash_chain_verified": True,
            "verified_receipt_count": 0,
            "attempt_count": 0,
            "roles": {},
            "latest_receipt": {},
            "recent_receipts": [],
            "retort_clarifications": clarification_summary,
        }
    with path.open("r", encoding="utf-8") as file_obj:
        rows = _read_rows_unlocked(file_obj)
    integrity_ok, _ = _verify_rows(rows)
    verified = [row for row in rows if row.get("verified") is True] if integrity_ok else []
    latest = verified[-1] if verified else {}
    roles = latest.get("roles") if isinstance(latest.get("roles"), dict) else {}
    bounded = max(1, min(int(limit or 20), 100))
    return {
        "schema": STATUS_SCHEMA_VERSION,
        "ok": integrity_ok,
        "ready": bool(integrity_ok and latest),
        "append_only": True,
        "hash_chain_verified": integrity_ok,
        "verified_receipt_count": len(verified),
        "attempt_count": len(rows),
        "roles": roles,
        "latest_receipt": _public_receipt(latest) if latest else {},
        "recent_receipts": [_public_receipt(row) for row in rows[-bounded:]],
        "retort_clarifications": clarification_summary,
    }


__all__ = [
    "build_live_strategic_council_receipt",
    "build_strategic_council_receipt",
    "strategic_council_ledger_path",
    "strategic_council_status",
]
