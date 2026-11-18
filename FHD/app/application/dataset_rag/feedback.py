"""Answer feedback records kept beside the dataset snapshot."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.application.dataset_rag.models import _utc_now_iso

FEEDBACK_RATINGS = frozenset({"up", "down"})
_MAX_RECORDS_PER_DATASET = 2000


class DatasetFeedbackStore:
    """Append answer feedback per dataset without rewriting the dataset snapshot."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def record(
        self,
        *,
        dataset_id: str,
        tenant_id: str,
        rating: str,
        query: str = "",
        answer: str = "",
        comment: str = "",
        citations: list[dict[str, Any]] | None = None,
        actor_id: str = "",
    ) -> dict[str, Any]:
        if rating not in FEEDBACK_RATINGS:
            raise ValueError("rating must be 'up' or 'down'")
        record = {
            "feedback_id": f"fb_{uuid4().hex[:12]}",
            "dataset_id": dataset_id,
            "tenant_id": tenant_id,
            "actor_id": actor_id,
            "rating": rating,
            "query": query.strip()[:2000],
            "answer": answer.strip()[:4000],
            "comment": comment.strip()[:1000],
            "citations": _bounded_citations(citations),
            "created_at": _utc_now_iso(),
        }
        with self._lock:
            payload = self._load()
            rows = payload.setdefault(dataset_id, [])
            rows.append(record)
            if len(rows) > _MAX_RECORDS_PER_DATASET:
                del rows[: len(rows) - _MAX_RECORDS_PER_DATASET]
            self._persist(payload)
        return record

    def summary(self, *, dataset_id: str, tenant_id: str = "", limit: int = 20) -> dict[str, Any]:
        with self._lock:
            rows = [
                row
                for row in self._load().get(dataset_id, [])
                if isinstance(row, dict) and (not tenant_id or row.get("tenant_id") == tenant_id)
            ]
        up = sum(1 for row in rows if row.get("rating") == "up")
        down = sum(1 for row in rows if row.get("rating") == "down")
        rated = up + down
        return {
            "total": rated,
            "up": up,
            "down": down,
            "satisfaction": round(up / rated, 4) if rated else None,
            "latest": list(reversed(rows[-max(1, min(limit, 100)) :])),
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


def _bounded_citations(citations: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    bounded: list[dict[str, Any]] = []
    for row in (citations or [])[:10]:
        if not isinstance(row, dict):
            continue
        bounded.append(
            {
                "source": str(row.get("source") or "")[:300],
                "chunk_index": row.get("chunk_index")
                if isinstance(row.get("chunk_index"), int)
                else None,
                "score": float(row.get("score") or 0.0),
            }
        )
    return bounded
