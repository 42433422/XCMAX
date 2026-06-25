"""Self-maintain the self-evolution KB."""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from modstore_server.self_evolution_knowledge import kb_root


def _runtime_dir() -> Path:
    return Path(os.environ.get("MODSTORE_RUNTIME_DIR") or Path.home() / ".xcmax" / "modstore-daily")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(str(raw).strip())
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_./:-]+|[\u4e00-\u9fff]{2,}", text.lower()))


def _similarity(a: Dict[str, Any], b: Dict[str, Any], kind: str) -> float:
    if kind == "fixes":
        a_text = f"{a.get('symptom') or ''}\n{a.get('root_cause') or ''}"
        b_text = f"{b.get('symptom') or ''}\n{b.get('root_cause') or ''}"
    else:
        a_text = f"{a.get('pattern') or ''}\n{a.get('summary') or ''}"
        b_text = f"{b.get('pattern') or ''}\n{b.get('summary') or ''}"
    a_tokens = _tokens(a_text)
    b_tokens = _tokens(b_text)
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / max(1, len(a_tokens | b_tokens))


def _parse_time(value: Any, fallback: float) -> float:
    if not value:
        return fallback
    text = str(value).strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return fallback


def _load_docs(kind: str) -> List[Tuple[Path, Dict[str, Any]]]:
    directory = kb_root() / kind
    if not directory.exists():
        return []
    out: List[Tuple[Path, Dict[str, Any]]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            out.append((path, data))
    return out


def _write_doc(path: Path, data: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _archive_doc(path: Path, kind: str, reason: str) -> Path:
    archive_dir = kb_root() / "archive" / kind
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / path.name
    counter = 1
    while target.exists():
        target = archive_dir / f"{path.stem}-{counter}{path.suffix}"
        counter += 1
    sidecar = target.with_suffix(target.suffix + ".archive_reason.json")
    path.replace(target)
    sidecar.write_text(
        json.dumps(
            {"archived_at": time.time(), "reason": reason, "source": str(path)},
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return target


def _confidence_for_doc(
    path: Path, doc: Dict[str, Any], now: float
) -> Tuple[float, Dict[str, Any]]:
    metadata = doc.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    created_ts = _parse_time(doc.get("created_at"), path.stat().st_mtime)
    age_days = max(0.0, (now - created_ts) / 86400.0)
    base = metadata.get("base_confidence", metadata.get("confidence", 1.0))
    try:
        base_confidence = max(0.0, min(float(base), 1.0))
    except (TypeError, ValueError):
        base_confidence = 1.0
    half_life_days = max(1, _env_int("MODSTORE_KB_CONFIDENCE_HALF_LIFE_DAYS", 120))
    decay = 0.5 ** (age_days / half_life_days)
    success_bonus = min(0.15, float(metadata.get("success_count") or 0) * 0.02)
    confidence = max(0.0, min(1.0, base_confidence * decay + success_bonus))
    metadata.update(
        {
            "base_confidence": round(base_confidence, 4),
            "confidence": round(confidence, 4),
            "confidence_updated_at": datetime.now(timezone.utc).isoformat(),
            "confidence_source": "phase_d_kb_decay",
        }
    )
    doc["metadata"] = metadata
    return confidence, doc


def _merge_similar(
    kind: str, docs: List[Tuple[Path, Dict[str, Any]]], dry_run: bool
) -> List[Dict[str, Any]]:
    threshold = _env_float("MODSTORE_KB_SIMILARITY_MERGE_THRESHOLD", 0.82)
    actions: List[Dict[str, Any]] = []
    archived: set[str] = set()
    for idx, (path_a, doc_a) in enumerate(docs):
        if str(path_a) in archived:
            continue
        for path_b, doc_b in docs[idx + 1 :]:
            if str(path_b) in archived:
                continue
            score = _similarity(doc_a, doc_b, kind)
            if score < threshold:
                continue
            meta_a = doc_a.get("metadata") if isinstance(doc_a.get("metadata"), dict) else {}
            meta_b = doc_b.get("metadata") if isinstance(doc_b.get("metadata"), dict) else {}
            conf_a = float(meta_a.get("confidence") or 0.0)
            conf_b = float(meta_b.get("confidence") or 0.0)
            keep_path, keep_doc, drop_path = (
                (path_a, doc_a, path_b) if conf_a >= conf_b else (path_b, doc_b, path_a)
            )
            keep_meta = (
                keep_doc.get("metadata") if isinstance(keep_doc.get("metadata"), dict) else {}
            )
            merged_sources = (
                keep_meta.get("merged_sources")
                if isinstance(keep_meta.get("merged_sources"), list)
                else []
            )
            merged_sources.append({"path": str(drop_path), "similarity": round(score, 4)})
            keep_meta["merged_sources"] = merged_sources[-20:]
            keep_meta["merged_at"] = datetime.now(timezone.utc).isoformat()
            keep_meta["merge_source"] = "phase_d_kb_similarity"
            keep_doc["metadata"] = keep_meta
            action = {
                "drop": str(drop_path),
                "keep": str(keep_path),
                "kind": kind,
                "similarity": round(score, 4),
                "type": "merge_similar",
            }
            if not dry_run:
                _write_doc(keep_path, keep_doc)
                archived_path = _archive_doc(drop_path, kind, "merged_similar")
                action["archived_to"] = str(archived_path)
            archived.add(str(drop_path))
            actions.append(action)
    return actions


def run_kb_self_maintenance_once(*, dry_run: bool | None = None) -> Dict[str, Any]:
    if dry_run is None:
        dry_run = (
            os.environ.get("MODSTORE_KB_SELF_MAINTENANCE_DRY_RUN") or "0"
        ).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    now = time.time()
    stale_days = _env_int("MODSTORE_KB_STALE_AFTER_DAYS", 180)
    stale_confidence = _env_float("MODSTORE_KB_STALE_CONFIDENCE", 0.25)
    actions: List[Dict[str, Any]] = []
    for kind in ("fixes", "patterns"):
        docs = _load_docs(kind)
        refreshed: List[Tuple[Path, Dict[str, Any]]] = []
        for path, doc in docs:
            confidence, updated = _confidence_for_doc(path, doc, now)
            created_ts = _parse_time(updated.get("created_at"), path.stat().st_mtime)
            age_days = max(0.0, (now - created_ts) / 86400.0)
            if age_days >= stale_days and confidence <= stale_confidence:
                action = {
                    "age_days": round(age_days, 2),
                    "confidence": round(confidence, 4),
                    "kind": kind,
                    "path": str(path),
                    "type": "archive_stale",
                }
                if not dry_run:
                    action["archived_to"] = str(_archive_doc(path, kind, "stale_low_confidence"))
                actions.append(action)
                continue
            if not dry_run:
                _write_doc(path, updated)
            refreshed.append((path, updated))
        actions.extend(_merge_similar(kind, refreshed, dry_run=dry_run))
    result = {
        "actions": actions,
        "action_count": len(actions),
        "dry_run": dry_run,
        "kb_root": str(kb_root()),
        "ok": True,
        "schema_version": 1,
        "source": "phase_d_kb_self_maintenance",
        "ts": now,
    }
    audit = _runtime_dir() / "kb_self_maintenance_audit.jsonl"
    audit.parent.mkdir(parents=True, exist_ok=True)
    with audit.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    result["audit_path"] = str(audit)
    return result


__all__ = ["run_kb_self_maintenance_once"]
