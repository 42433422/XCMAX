from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import sys
import threading
import uuid
import weakref
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal as Decimal
from pathlib import Path
from typing import Any

import httpx as httpx

from app.utils.path_io.path_utils import get_app_data_dir

DEFAULT_LLM_TOKENS_PER_COST_UNIT = 1000
_ledger_lock = threading.Lock()
_usage_locks: weakref.WeakValueDictionary = weakref.WeakValueDictionary()
_storage_location: tuple[str, str] | None = None


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def llm_tokens_per_cost_unit() -> int:
    configured = _coerce_int(os.environ.get("FHD_LLM_TOKENS_PER_COST_UNIT"))
    return configured if configured > 0 else DEFAULT_LLM_TOKENS_PER_COST_UNIT


def estimate_llm_cost_units(
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
) -> int:
    total = _coerce_int(total_tokens)
    if total <= 0:
        total = _coerce_int(prompt_tokens) + _coerce_int(completion_tokens)
    if total <= 0:
        return 0
    return max(1, int(math.ceil(total / llm_tokens_per_cost_unit())))


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def model_usage_ledger_path() -> Path:
    custom = (os.environ.get("MODEL_USAGE_LEDGER_PATH") or "").strip()
    if custom:
        return Path(custom)
    if getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS"):
        return Path(get_app_data_dir()) / "data" / "model_usage_ledger.json"
    return _repo_root() / "data" / "model_usage_ledger.json"


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _empty_usage_state() -> dict[str, Any]:
    return {"entries": [], "wallets": {}, "summary": {"entry_count": 0, "cost_units_total": 0}}


def _load_legacy_usage_state(*, strict: bool = False) -> dict[str, Any]:
    path = model_usage_ledger_path()
    if not path.is_file():
        return _empty_usage_state()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        if strict:
            raise
        return _empty_usage_state()
    if not isinstance(data, dict):
        if strict:
            raise ValueError("Legacy usage ledger must be a JSON object")
        return _empty_usage_state()
    entries = data.get("entries", [])
    wallets = data.get("wallets", {})
    if strict and (
        not isinstance(entries, list)
        or any(not isinstance(entry, dict) for entry in entries)
        or not isinstance(wallets, dict)
        or any(not isinstance(wallet, dict) for wallet in wallets.values())
    ):
        raise ValueError("Malformed legacy usage entries or wallets; migration refused")
    if not isinstance(entries, list):
        entries = []
    data["entries"] = [entry for entry in entries if isinstance(entry, dict)]
    wallets = data.get("wallets")
    data["wallets"] = wallets if isinstance(wallets, dict) else {}
    data["summary"] = _usage_summary(data["entries"])
    return data


def _safe_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    try:
        json.dumps(value, ensure_ascii=False, default=str)
        return dict(value)
    except TypeError:  # noqa: BLE001 - normalize untrusted metadata values
        return {str(key): str(item) for key, item in value.items()}


def _usage_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    model_entries = [
        entry for entry in entries if str(entry.get("entry_type") or "model_call") == "model_call"
    ]
    tool_entries = [entry for entry in entries if str(entry.get("entry_type") or "") == "tool_call"]
    refunded_entries = [
        entry
        for entry in entries
        if isinstance(entry.get("refund"), dict)
        and str(entry.get("refund", {}).get("status") or "") == "refunded"
    ]
    return {
        "entry_count": len(entries),
        "cost_units_total": sum(_coerce_int(entry.get("cost_units")) for entry in entries),
        "token_total": sum(_coerce_int(entry.get("total_tokens")) for entry in entries),
        "model_entry_count": len(model_entries),
        "model_cost_units_total": sum(
            _coerce_int(entry.get("cost_units")) for entry in model_entries
        ),
        "tool_entry_count": len(tool_entries),
        "tool_cost_units_total": sum(
            _coerce_int(entry.get("cost_units")) for entry in tool_entries
        ),
        "refund_entry_count": len(refunded_entries),
        "refund_cost_units_total": sum(
            _coerce_int(entry.get("refund", {}).get("cost_units")) for entry in refunded_entries
        ),
    }


def _wallet_required() -> bool:
    return (os.environ.get("MODEL_USAGE_WALLET_REQUIRED") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def model_usage_wallet_backend() -> str:
    raw = (os.environ.get("MODEL_USAGE_WALLET_BACKEND") or "").strip().lower()
    if raw in {"market", "modstore", "xcagi_market", "xiuci"}:
        return "market"
    if raw in {"audit", "none", "off", "disabled"}:
        return "audit"
    return "local"


def _wallet_user_id(user_id: str) -> str:
    return str(user_id or "anonymous").strip() or "anonymous"


def _wallet_snapshot(wallets: dict[str, Any], user_id: str) -> dict[str, Any] | None:
    wallet = wallets.get(_wallet_user_id(user_id))
    return dict(wallet) if isinstance(wallet, dict) else None


def _apply_wallet_debit(
    state: dict[str, Any],
    *,
    user_id: str,
    cost_units: int,
) -> tuple[str, dict[str, Any]]:
    wallets: dict[str, Any] = state.setdefault("wallets", {})
    uid = _wallet_user_id(user_id)
    wallet = _wallet_snapshot(wallets, uid)
    required = _wallet_required()
    if cost_units <= 0:
        return "unmetered", {"status": "not_required", "user_id": uid, "cost_units": 0}
    if wallet is None and not required:
        return "metered", {
            "status": "audit_only",
            "user_id": uid,
            "cost_units": cost_units,
            "reason": "wallet_not_configured",
        }
    balance_before = _coerce_int((wallet or {}).get("balance_units"))
    if balance_before < cost_units:
        return "insufficient_balance", {
            "status": "insufficient_balance",
            "user_id": uid,
            "cost_units": cost_units,
            "balance_before_units": balance_before,
            "balance_after_units": balance_before,
            "shortfall_units": cost_units - balance_before,
        }
    balance_after = balance_before - cost_units
    wallet_row = dict(wallet or {})
    wallet_row["user_id"] = uid
    wallet_row["balance_units"] = balance_after
    wallet_row["updated_at"] = _utc_iso()
    wallets[uid] = wallet_row
    return "debited", {
        "status": "debited",
        "user_id": uid,
        "cost_units": cost_units,
        "balance_before_units": balance_before,
        "balance_after_units": balance_after,
    }


from app.infrastructure.billing.model_usage_market import (
    _apply_market_wallet_debit as _apply_market_wallet_debit,
)
from app.infrastructure.billing.model_usage_market import (
    _apply_market_wallet_refund as _apply_market_wallet_refund,
)
from app.infrastructure.billing.model_usage_market import (
    _market_amount_for_cost_units as _market_amount_for_cost_units,
)
from app.infrastructure.billing.model_usage_market import _market_auth_token as _market_auth_token
from app.infrastructure.billing.model_usage_market import _market_base_url as _market_base_url
from app.infrastructure.billing.model_usage_market import _market_post_json as _market_post_json
from app.infrastructure.billing.model_usage_market import _market_timeout as _market_timeout
from app.infrastructure.billing.model_usage_market import _money as _money
from app.infrastructure.billing.model_usage_market import _money_str as _money_str
from app.infrastructure.billing.model_usage_market import (
    _prepare_market_request as _prepare_market_request,
)
from app.infrastructure.billing.model_usage_market import _strip_bearer as _strip_bearer
from app.infrastructure.billing.model_usage_records import record_model_usage as record_model_usage
from app.infrastructure.billing.model_usage_records import record_tool_usage as record_tool_usage
from app.infrastructure.billing.model_usage_records import refund_tool_usage as refund_tool_usage


def model_usage_database_path() -> Path:
    """Incremental store beside the immutable legacy JSON import source."""
    return Path(f"{model_usage_ledger_path()}.sqlite3")


def _sync_directory(path: Path) -> None:
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _record_storage_location() -> None:
    """Locate a .env-selected desktop ledger once per process/path for rollback."""
    global _storage_location
    if not (
        getattr(sys, "frozen", False)
        or hasattr(sys, "_MEIPASS")
        or os.environ.get("XCAGI_DESKTOP_MODE") == "1"
    ):
        return
    target = Path(get_app_data_dir()) / "data" / "model_usage_storage.json"
    ledger = str(model_usage_ledger_path().resolve())
    key = str(target), ledger
    if _storage_location == key:
        return
    with _ledger_lock:
        if _storage_location == key:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f"{target.name}.{os.getpid()}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as output:
                json.dump({"version": 1, "ledger_path": ledger}, output, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
            _sync_directory(target.parent)
            _storage_location = key
        finally:
            temporary.unlink(missing_ok=True)


@contextmanager
def _usage_key_lock(usage_key: str):
    # No network call holds the registry lock. Weak references release completed
    # keys instead of retaining one lock for every historical model invocation.
    key = str(model_usage_database_path().resolve()), usage_key
    with _ledger_lock:
        lock = _usage_locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _usage_locks[key] = lock
    with lock:
        yield


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


def _save_wallet(db, uid: str, wallet: dict[str, Any]) -> None:
    db.execute("INSERT OR REPLACE INTO wallets VALUES (?, ?)", (uid, _json(wallet)))


def _read_wallet(db, uid: str) -> dict[str, Any] | None:
    row = db.execute("SELECT payload FROM wallets WHERE user_id = ?", (uid,)).fetchone()
    return json.loads(row[0]) if row else None


def _read_entry(db, usage_key: str):
    row = db.execute(
        "SELECT payload, state FROM entries WHERE usage_key = ?", (usage_key,)
    ).fetchone()
    return (json.loads(row[0]), row[1]) if row else (None, None)


def _save_entry(db, entry, *, previous=None, state="complete", storage_key=None) -> None:
    db.execute(
        "INSERT OR REPLACE INTO entries VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            storage_key or entry["usage_key"],
            str(entry.get("usage_id") or ""),
            str(entry.get("user_id") or ""),
            str(entry.get("run_id") or ""),
            str(entry.get("created_at") or ""),
            _json(entry),
            state,
        ),
    )
    before = _usage_summary([previous] if previous else [])
    after = _usage_summary([entry] if state == "complete" else [])
    db.executemany(
        "INSERT INTO summary VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET value=value+excluded.value",
        [(name, value - before[name]) for name, value in after.items()],
    )


@contextmanager
def _usage_db(*, write: bool = False):
    path = model_usage_database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    try:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            raise RuntimeError(f"Unsupported usage ledger schema: {version}")
        if version == 0:
            db.execute("PRAGMA journal_mode=WAL")
            with db:
                db.execute("BEGIN IMMEDIATE")
                # Another process may have migrated while this writer waited.
                if db.execute("PRAGMA user_version").fetchone()[0] == 0:
                    source = model_usage_ledger_path()
                    if not source.is_file() and next(
                        source.parent.glob(f"{source.stem}.*.legacy{source.suffix}"), None
                    ):
                        raise RuntimeError(
                            "Migrated usage database is missing; restore it before billing"
                        )
                    db.execute(
                        "CREATE TABLE entries (usage_key TEXT PRIMARY KEY, usage_id TEXT, user_id TEXT, run_id TEXT, created_at TEXT, payload TEXT NOT NULL, state TEXT NOT NULL)"
                    )
                    db.execute(
                        "CREATE TABLE wallets (user_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
                    )
                    db.execute(
                        "CREATE TABLE summary (name TEXT PRIMARY KEY, value INTEGER NOT NULL)"
                    )
                    db.execute(
                        "CREATE TABLE migration (source_hash TEXT, archived INTEGER NOT NULL)"
                    )
                    for columns in (
                        "created_at",
                        "user_id, created_at",
                        "run_id, created_at",
                        "user_id, run_id, created_at",
                        "usage_id",
                    ):
                        name = columns.replace(", ", "_")
                        db.execute(f"CREATE INDEX usage_{name} ON entries ({columns})")
                    digest = (
                        hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else ""
                    )
                    legacy = _load_legacy_usage_state(strict=True)
                    if digest and hashlib.sha256(source.read_bytes()).hexdigest() != digest:
                        raise RuntimeError(
                            "Legacy usage ledger changed during migration; stop the old writer"
                        )
                    db.execute("INSERT INTO migration VALUES (?, ?)", (digest, int(not digest)))
                    for index, entry in enumerate(legacy["entries"]):
                        key = str(
                            entry.get("usage_key") or entry.get("usage_id") or f"legacy:{index}"
                        )
                        if _read_entry(db, key)[0] is not None:
                            raise ValueError(f"Duplicate legacy usage key: {key}")
                        _save_entry(db, entry, storage_key=key)
                    for uid, wallet in legacy["wallets"].items():
                        if isinstance(wallet, dict):
                            _save_wallet(db, uid, wallet)
                    db.execute("PRAGMA user_version=1")
        _archive_legacy_ledger(db)
        _record_storage_location()
        db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        with db:
            yield db
    finally:
        db.close()


def _archive_legacy_ledger(db) -> None:
    row = db.execute("SELECT source_hash, archived FROM migration").fetchone()
    if row is None:
        raise RuntimeError("Usage ledger migration metadata is missing")
    if row[1]:
        return
    with db:
        # The first-open filesystem handoff is serialized across processes too.
        # Otherwise another initializer can move source between is_file/read_bytes.
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT source_hash, archived FROM migration").fetchone()
        if row[1]:
            return
        source = model_usage_ledger_path()
        backup = source.with_name(f"{source.stem}.{row[0][:12]}.legacy{source.suffix}")
        if source.is_file():
            if hashlib.sha256(source.read_bytes()).hexdigest() != row[0]:
                raise RuntimeError(
                    "Legacy usage ledger changed after migration; reconciliation required"
                )
            if backup.exists() and hashlib.sha256(backup.read_bytes()).hexdigest() != row[0]:
                raise RuntimeError("Legacy ledger backup already exists with different data")
            os.replace(source, backup)
            _sync_directory(source.parent)
        if not backup.is_file() or hashlib.sha256(backup.read_bytes()).hexdigest() != row[0]:
            raise RuntimeError("Migrated ledger backup is missing or changed")
        backup.chmod(backup.stat().st_mode & ~0o222)
        db.execute("UPDATE migration SET archived = 1")


def export_model_usage_ledger(path: Path, *, retire_database: bool = False) -> None:
    """Explicit snapshot for export/rollback after all billing writers are stopped.

    Keep the database and .legacy.json backup until a rollback has been verified.
    Running old JSON writers concurrently with the new runtime is unsupported.
    """
    path = Path(path)
    database = model_usage_database_path()
    if path.resolve() == database.resolve():
        raise ValueError("Cannot export JSON over the SQLite ledger")
    if retire_database and path.resolve() != model_usage_ledger_path().resolve():
        raise ValueError("Rollback handoff must export to the configured legacy path")
    with _usage_db() as db:
        # A read transaction keeps entries and wallets at the same commit.
        if db.execute("SELECT 1 FROM entries WHERE state != 'complete' LIMIT 1").fetchone():
            raise RuntimeError("Pending market debits require reconciliation before rollback")
        payload = {
            "entries": [json.loads(row[0]) for row in db.execute("SELECT payload FROM entries")],
            "wallets": {uid: json.loads(body) for uid, body in db.execute("SELECT * FROM wallets")},
            "summary": dict(db.execute("SELECT * FROM summary")),
        }
    if any(
        (entry.get("refund") or {}).get("status") == "refund_pending"
        for entry in payload["entries"]
    ):
        raise RuntimeError("Pending market refunds require reconciliation before rollback")
    payload["compatibility_snapshot"] = {"source": str(database), "exported_at": _utc_iso()}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".export.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as output:
            output.write(_json(payload))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
        if retire_database:
            # All writers must already be stopped by the rollback coordinator.
            # Refuse a busy WAL rather than archive an incomplete database.
            connection = sqlite3.connect(database, timeout=30)
            try:
                if connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]:
                    raise RuntimeError("Usage ledger still has active connections")
            finally:
                connection.close()
            archive = database.with_name(f"{database.stem}.rollback-{uuid.uuid4().hex}.sqlite3")
            os.replace(database, archive)
            _sync_directory(database.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _load_usage_state() -> dict[str, Any]:
    """Explicit full snapshot for export/legacy diagnostics, never a write path."""
    if not model_usage_database_path().is_file():
        return _load_legacy_usage_state()
    with _usage_db() as db:
        return {
            "entries": [json.loads(row[0]) for row in db.execute("SELECT payload FROM entries")],
            "wallets": {uid: json.loads(body) for uid, body in db.execute("SELECT * FROM wallets")},
            "summary": dict(db.execute("SELECT * FROM summary")),
        }


def set_model_wallet_balance(
    user_id: str, balance_units: int, *, reason: str = "manual_set"
) -> dict[str, Any]:
    uid = _wallet_user_id(user_id)
    wallet = {
        "user_id": uid,
        "balance_units": max(_coerce_int(balance_units), 0),
        "reason": str(reason or ""),
        "updated_at": _utc_iso(),
    }
    with _usage_db(write=True) as db:
        _save_wallet(db, uid, wallet)
    return wallet


def get_model_wallet(user_id: str) -> dict[str, Any]:
    uid = _wallet_user_id(user_id)
    with _usage_db() as db:
        wallet = _read_wallet(db, uid)
    return {**(wallet or {"user_id": uid, "balance_units": 0}), "configured": wallet is not None}


def _set_debit_result(entry, status, debit, backend):
    entry["wallet_debit"] = debit
    if status in {
        "debited",
        "insufficient_balance",
        "market_debit_failed",
        "market_auth_missing",
        "market_debit_pending",
    }:
        entry["billing_status"] = (
            "market_debit_failed" if status == "market_auth_missing" else status
        )
        entry["billing_source"] = "market_wallet" if backend == "market" else "local_model_wallet"


def _record_usage_entry(entry: dict[str, Any]) -> dict[str, Any]:
    key = entry["usage_key"]
    with _usage_key_lock(key):
        with _usage_db(write=True) as db:
            existing, state = _read_entry(db, key)
            if state == "complete":
                return dict(existing)
            # A crash-recovered market request must reuse the persisted owner,
            # amount and idempotency key, even if a retry supplies different data.
            entry = existing or entry
            backend = entry.get("wallet_backend") or model_usage_wallet_backend()
            entry["wallet_backend"] = backend
            uid = _wallet_user_id(entry["user_id"])
            if backend == "market":
                if "market_request" not in entry:
                    entry["market_request"] = _prepare_market_request(uid, entry["cost_units"])
                entry["market_attempts"] = _coerce_int(entry.get("market_attempts")) + 1
                _save_entry(db, entry, state="pending")
            else:
                wallet = _read_wallet(db, uid)
                state = {"wallets": {uid: wallet} if wallet is not None else {}}
                status, debit = (
                    (
                        "metered" if entry["cost_units"] else "unmetered",
                        {
                            "status": "audit_only",
                            "user_id": uid,
                            "cost_units": entry["cost_units"],
                            "reason": "wallet_backend_audit",
                        },
                    )
                    if backend == "audit"
                    else _apply_wallet_debit(state, user_id=uid, cost_units=entry["cost_units"])
                )
                _set_debit_result(entry, status, debit, backend)
                if uid in state["wallets"]:
                    _save_wallet(db, uid, state["wallets"][uid])
                _save_entry(db, entry)
                return dict(entry)
        # External debit is idempotent and never holds the SQLite writer lock.
        status, debit = _apply_market_wallet_debit(
            user_id=entry["user_id"],
            provider=entry["provider"],
            model=entry["model"],
            cost_units=entry["cost_units"],
            usage_key=key,
            request=entry["market_request"],
        )
        with _usage_db(write=True) as db:
            existing, state = _read_entry(db, key)
            if state == "complete":
                return dict(existing)
            entry = existing
            # A retry/cross-process overlap cannot turn an earlier uncertain
            # request into a definite failure merely because this attempt failed.
            pending = bool(debit.get("outcome_unknown")) or (
                entry["market_attempts"] > 1 and status not in {"debited", "unmetered"}
            )
            if pending:
                status = "market_debit_pending"
                debit = {**debit, "outcome_unknown": True, "reconciliation_required": True}
            _set_debit_result(entry, status, debit, "market")
            _save_entry(db, entry, state="pending" if pending else "complete")
        return dict(entry)


def list_model_usage_entries(
    *, limit: int = 50, run_id: str = "", user_id: str = ""
) -> list[dict[str, Any]]:
    run_id, user_id = (str(value or "").strip() for value in (run_id, user_id))
    query = {
        (False, False): "SELECT payload FROM entries ORDER BY created_at DESC LIMIT ?",
        (
            True,
            False,
        ): "SELECT payload FROM entries WHERE run_id = ? ORDER BY created_at DESC LIMIT ?",
        (
            False,
            True,
        ): "SELECT payload FROM entries WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (
            True,
            True,
        ): "SELECT payload FROM entries WHERE run_id = ? AND user_id = ? ORDER BY created_at DESC LIMIT ?",
    }[bool(run_id), bool(user_id)]
    params = [value for value in (run_id, user_id) if value]
    with _usage_db() as db:
        rows = db.execute(
            query,
            (*params, max(0, int(limit or 0))),
        ).fetchall()
    return [json.loads(row[0]) for row in rows]
