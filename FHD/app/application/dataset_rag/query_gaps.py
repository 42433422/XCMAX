"""Unanswered-question log kept beside the dataset snapshot.

Mature knowledge bases keep a bounded list of questions that retrieved no
evidence so operators can add the missing documents. Frequent repeats collapse
into one row with a counter instead of growing without bound.
"""

from __future__ import annotations

import builtins
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_MAX_ROWS_PER_DATASET = 500


class DatasetQueryGapStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def record(self, *, dataset_id: str, tenant_id: str, query: str) -> None:
        text = " ".join(query.split())[:500]
        if not text:
            return
        key = text.casefold()
        now = _utc_now_iso()
        with self._lock:
            payload = self._load()
            rows = payload.setdefault(dataset_id, [])
            for row in rows:
                if isinstance(row, dict) and str(row.get("key") or "") == key:
                    row["count"] = int(row.get("count") or 1) + 1
                    row["last_at"] = now
                    self._persist(payload)
                    return
            rows.append(
                {
                    "key": key,
                    "query": text,
                    "tenant_id": tenant_id,
                    "count": 1,
                    "created_at": now,
                    "last_at": now,
                }
            )
            if len(rows) > _MAX_ROWS_PER_DATASET:
                del rows[: len(rows) - _MAX_ROWS_PER_DATASET]
            self._persist(payload)

    def list(
        self, *, dataset_id: str, tenant_id: str = "", limit: int = 20
    ) -> builtins.list[dict[str, Any]]:
        with self._lock:
            rows = [
                dict(row)
                for row in self._load().get(dataset_id, [])
                if isinstance(row, dict) and (not tenant_id or row.get("tenant_id") == tenant_id)
            ]
        rows.sort(
            key=lambda row: (int(row.get("count") or 0), str(row.get("last_at") or "")),
            reverse=True,
        )
        return rows[: max(1, min(limit, 100))]

    def clear(self, *, dataset_id: str, tenant_id: str = "") -> int:
        with self._lock:
            payload = self._load()
            rows = payload.get(dataset_id, [])
            kept = [
                row
                for row in rows
                if tenant_id and isinstance(row, dict) and row.get("tenant_id") != tenant_id
            ]
            removed = len(rows) - len(kept)
            if kept:
                payload[dataset_id] = kept
            else:
                payload.pop(dataset_id, None)
            self._persist(payload)
        return removed

    def _load(self) -> dict[str, builtins.list[dict[str, Any]]]:
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

    def _persist(self, items: dict[str, builtins.list[dict[str, Any]]]) -> None:
        payload = {"version": 1, "datasets": items}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
