"""Read-only dataset API keys for external knowledge-base clients.

Only the SHA-256 hash of a key is persisted; the raw key is shown once at
creation. Keys are dataset-scoped and bound to the tenant of the creator, so a
public call can never widen tenant or ACL visibility.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_MAX_KEYS_PER_DATASET = 50


class DatasetApiKeyStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def create(self, *, dataset_id: str, tenant_id: str, label: str = "") -> dict[str, Any]:
        raw = f"kb_{secrets.token_hex(24)}"
        row = {
            "token_id": f"key_{secrets.token_hex(8)}",
            "dataset_id": dataset_id,
            "tenant_id": tenant_id,
            "label": label.strip()[:80],
            "prefix": raw[:11],
            "key_hash": _hash(raw),
            "created_at": _utc_now_iso(),
            "last_used_at": "",
            "revoked_at": "",
        }
        with self._lock:
            payload = self._load()
            rows = payload.setdefault(dataset_id, [])
            rows.append(row)
            if len(rows) > _MAX_KEYS_PER_DATASET:
                del rows[: len(rows) - _MAX_KEYS_PER_DATASET]
            self._persist(payload)
        return {"key": raw, **self._public(row)}

    def list(self, *, dataset_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = [row for row in self._load().get(dataset_id, []) if isinstance(row, dict)]
        return [self._public(row) for row in rows]

    def revoke(self, *, dataset_id: str, token_id: str) -> bool:
        with self._lock:
            payload = self._load()
            rows = payload.get(dataset_id, [])
            for row in rows:
                if isinstance(row, dict) and row.get("token_id") == token_id:
                    if not row.get("revoked_at"):
                        row["revoked_at"] = _utc_now_iso()
                        self._persist(payload)
                    return True
            return False

    def resolve(self, raw_key: str) -> dict[str, Any] | None:
        digest = _hash(str(raw_key or ""))
        with self._lock:
            payload = self._load()
            for dataset_id, rows in payload.items():
                for row in rows:
                    if (
                        isinstance(row, dict)
                        and row.get("key_hash") == digest
                        and not row.get("revoked_at")
                    ):
                        row["last_used_at"] = _utc_now_iso()
                        self._persist(payload)
                        return {
                            "token_id": str(row.get("token_id") or ""),
                            "dataset_id": dataset_id,
                            "tenant_id": str(row.get("tenant_id") or ""),
                        }
        return None

    def _public(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "token_id": row.get("token_id"),
            "dataset_id": row.get("dataset_id"),
            "label": row.get("label"),
            "prefix": row.get("prefix"),
            "created_at": row.get("created_at"),
            "last_used_at": row.get("last_used_at"),
            "revoked_at": row.get("revoked_at"),
        }

    def _load(self) -> dict[str, list[dict[str, Any]]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        datasets = raw.get("datasets") if isinstance(raw, dict) else None
        if not isinstance(datasets, dict):
            return {}
        return {
            str(dataset_id): [row for row in rows if isinstance(row, dict)]
            for dataset_id, rows in datasets.items()
            if isinstance(rows, list)
        }

    def _persist(self, items: dict[str, list[dict[str, Any]]]) -> None:
        payload = {"version": 1, "datasets": items}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
