"""Cross-project knowledge base.

Each :class:`ProjectMemory` instance is scoped to one workspace —
useful for "this project's style", less useful for "what worked in
similar projects last quarter". The :class:`GlobalKnowledgeBase`
aggregates exemplars across many projects and supports:

- **Embedding-based search** — pluggable :class:`Embedder` (hashing
  fallback when no vendor configured) so semantic queries beat exact
  word matches.
- **Tag-aware filtering** — search by language / framework / domain /
  custom tag combinations.
- **Auto-promotion** — :meth:`promote_from_project` ingests a
  project's :class:`ExemplarStore` and persists the high-quality
  successes for global retrieval. Failure exemplars are kept too
  (handy for "things-to-avoid" prompts) but tagged.
- **Persistent storage** — JSON file (``knowledge_base.json``) by
  default; subclass and override :meth:`_save` / :meth:`_load` for
  databases.

Usage::

    kb = GlobalKnowledgeBase(store_dir="~/.vibe_coding/kb")
    kb.add_exemplar(exemplar, project_id="proj-A")
    matches = kb.search("vue 3 composition API state management",
                        k=5, language="vue")
    print(kb.to_prompt_block("similar refactors", k=3))
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal, Sequence

from .embedder import Embedder, HashingEmbedder, cosine_similarity
from .exemplars import Exemplar
from .retriever import Retriever

_KB_FILENAME = "knowledge_base.json"
_PROMOTION_QUALITY_KEY = "promotion_score"


@dataclass
class KnowledgeRecord:
    """One indexed entry: exemplar + provenance + (optional) embedding."""

    exemplar: Exemplar
    project_id: str = ""
    framework: str = ""
    languages: list[str] = field(default_factory=list)
    embedding: list[float] = field(default_factory=list)
    promoted_at: float = field(default_factory=time.time)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "exemplar": self.exemplar.to_dict(),
            "project_id": self.project_id,
            "framework": self.framework,
            "languages": list(self.languages),
            "embedding": list(self.embedding),
            "promoted_at": float(self.promoted_at),
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "KnowledgeRecord":
        ex_raw = raw.get("exemplar")
        if not isinstance(ex_raw, dict):
            raise ValueError("knowledge record missing 'exemplar'")
        return cls(
            exemplar=Exemplar.from_dict(ex_raw),
            project_id=str(raw.get("project_id") or ""),
            framework=str(raw.get("framework") or ""),
            languages=[str(x) for x in raw.get("languages") or []],
            embedding=[float(x) for x in raw.get("embedding") or []],
            promoted_at=float(raw.get("promoted_at") or time.time()),
            tags=[str(x) for x in raw.get("tags") or []],
        )


class GlobalKnowledgeBase:
    """Cross-project exemplar store with semantic + tag-aware retrieval.

    Thread-safe via a single reentrant lock. Persistence is JSON-file
    based by default; pass ``store_path`` to point at a custom location
    or subclass and override :meth:`_save` / :meth:`_load` for SQLite /
    Postgres.
    """

    def __init__(
        self,
        store_dir: str | Path,
        *,
        embedder: Embedder | None = None,
        max_records: int = 5_000,
        promotion_threshold: float = 0.8,
        store_path: Path | None = None,
    ) -> None:
        self.store_dir = Path(store_dir).expanduser()
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.store_path = Path(store_path) if store_path else self.store_dir / _KB_FILENAME
        self.embedder: Embedder = embedder or HashingEmbedder()
        self.max_records = int(max_records)
        self.promotion_threshold = float(promotion_threshold)
        self._lock = threading.RLock()
        self._records: list[KnowledgeRecord] = []
        self._load()

    # ------------------------------------------------------------------ writes

    def add_exemplar(
        self,
        exemplar: Exemplar,
        *,
        project_id: str = "",
        framework: str = "",
        tags: Sequence[str] | None = None,
    ) -> KnowledgeRecord:
        """Add one exemplar to the global KB; returns the stored record."""
        record = KnowledgeRecord(
            exemplar=exemplar,
            project_id=project_id,
            framework=framework,
            languages=list(exemplar.languages),
            embedding=self._embed(exemplar.search_text()),
            tags=list(tags or []) + list(exemplar.tags),
        )
        with self._lock:
            self._records.append(record)
            self._auto_prune()
            self._save()
        return record

    def promote_from_project(
        self,
        exemplars: Iterable[Exemplar],
        *,
        project_id: str,
        framework: str = "",
        only_successes: bool = False,
    ) -> int:
        """Bulk-import a project's exemplars into the KB.

        ``only_successes=True`` filters failures out (useful when
        promoting a stable project; failures pollute the cross-project
        BM25 corpus). The default is ``False`` — failure exemplars are
        valuable cross-project signal too.
        """
        added = 0
        with self._lock:
            for ex in exemplars:
                # De-duplicate by (project_id, patch_id) so promoting
                # twice doesn't double-count a record.
                if any(
                    r.project_id == project_id and r.exemplar.patch_id == ex.patch_id
                    for r in self._records
                ):
                    continue
                if only_successes and ex.outcome != "success":
                    continue
                self._records.append(
                    KnowledgeRecord(
                        exemplar=ex,
                        project_id=project_id,
                        framework=framework,
                        languages=list(ex.languages),
                        embedding=self._embed(ex.search_text()),
                        tags=list(ex.tags),
                    )
                )
                added += 1
            if added:
                self._auto_prune()
                self._save()
        return added

    def remove_project(self, project_id: str) -> int:
        with self._lock:
            keep = [r for r in self._records if r.project_id != project_id]
            removed = len(self._records) - len(keep)
            if removed:
                self._records = keep
                self._save()
            return removed

    # ------------------------------------------------------------------ reads

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        language: str | Sequence[str] | None = None,
        framework: str | None = None,
        outcome: Literal["success", "failure", "any"] = "success",
        tags: Sequence[str] | None = None,
        min_similarity: float = 0.0,
    ) -> list[KnowledgeRecord]:
        """Return the top-K records most similar to ``query``.

        Filters: language(s), framework, outcome, required tags. The
        embedding-based score is combined with a small BM25 boost on
        the same text, so very-short queries (where embeddings are
        noisier) still benefit from keyword overlap.
        """
        with self._lock:
            pool = self._filter_pool(
                language=language,
                framework=framework,
                outcome=outcome,
                tags=tags,
            )
            if not pool:
                return []
            query_vec = self._embed(query)
            scored: list[tuple[float, KnowledgeRecord]] = []
            for rec in pool:
                vec = rec.embedding or self._embed(rec.exemplar.search_text())
                sim = cosine_similarity(query_vec, vec)
                if sim < min_similarity:
                    continue
                scored.append((sim, rec))
            # BM25 boost — lookup the same exemplars by ranked text.
            try:
                retriever = Retriever([r.exemplar for r in pool])
                top_text = retriever.search(query, k=min(k * 2, len(pool)))
                bm25_ids = {ex.id for ex in top_text}
            except Exception:  # noqa: BLE001
                bm25_ids = set()
            scored.sort(
                key=lambda triple: (
                    triple[0]
                    + (0.05 if triple[1].exemplar.id in bm25_ids else 0.0)
                ),
                reverse=True,
            )
            return [rec for _, rec in scored[:k]]

    def __len__(self) -> int:
        return len(self._records)

    def all(self) -> list[KnowledgeRecord]:
        with self._lock:
            return list(self._records)

    def to_prompt_block(
        self,
        query: str,
        *,
        k: int = 3,
        language: str | Sequence[str] | None = None,
        framework: str | None = None,
        outcome: Literal["success", "failure", "any"] = "success",
    ) -> str:
        """Render a ``## 跨项目知识`` block ready to splice into prompts."""
        records = self.search(
            query, k=k, language=language, framework=framework, outcome=outcome
        )
        if not records:
            return ""
        lines = ["## 跨项目知识（仅供参考，请按当前项目风格调整）"]
        for idx, rec in enumerate(records, start=1):
            tags = ", ".join(rec.tags) or "(无标签)"
            ex = rec.exemplar
            lines.append(
                f"### 知识 {idx} — {ex.summary or ex.brief[:60]} "
                f"[from {rec.project_id or 'unknown'}; {tags}]\n"
                f"原始需求: {ex.brief[:120]}\n"
                f"diff 片段:\n```\n{ex.diff_text[:500]}\n```"
            )
        return "\n\n".join(lines)

    # ------------------------------------------------------------------ tools

    def stats(self) -> dict[str, Any]:
        """Quick stats for the dashboard / Web UI."""
        with self._lock:
            by_project: dict[str, int] = {}
            by_outcome: dict[str, int] = {}
            by_language: dict[str, int] = {}
            for r in self._records:
                by_project[r.project_id or "unknown"] = (
                    by_project.get(r.project_id or "unknown", 0) + 1
                )
                by_outcome[r.exemplar.outcome] = by_outcome.get(r.exemplar.outcome, 0) + 1
                for lang in r.languages or [""]:
                    by_language[lang or "unknown"] = by_language.get(lang or "unknown", 0) + 1
            return {
                "records": len(self._records),
                "projects": dict(sorted(by_project.items())),
                "outcomes": dict(sorted(by_outcome.items())),
                "languages": dict(sorted(by_language.items())),
                "embedder": type(self.embedder).__name__,
            }

    # ------------------------------------------------------------------ internals

    def _filter_pool(
        self,
        *,
        language: str | Sequence[str] | None,
        framework: str | None,
        outcome: Literal["success", "failure", "any"],
        tags: Sequence[str] | None,
    ) -> list[KnowledgeRecord]:
        if isinstance(language, str):
            languages = {language.lower()}
        elif language is None:
            languages = None
        else:
            languages = {l.lower() for l in language}
        framework_norm = (framework or "").strip().lower()
        required_tags = {t.lower() for t in (tags or [])}

        out: list[KnowledgeRecord] = []
        for rec in self._records:
            if outcome != "any" and rec.exemplar.outcome != outcome:
                continue
            if languages is not None and not any(
                lang.lower() in languages for lang in rec.languages
            ):
                continue
            if framework_norm and rec.framework.lower() != framework_norm:
                continue
            if required_tags and not required_tags.issubset(
                {t.lower() for t in rec.tags}
            ):
                continue
            out.append(rec)
        return out

    def _embed(self, text: str) -> list[float]:
        try:
            vectors = self.embedder.embed([text or ""])
        except Exception:  # noqa: BLE001
            vectors = []
        if not vectors or not vectors[0]:
            return []
        return list(vectors[0])

    def _auto_prune(self) -> None:
        if self.max_records <= 0:
            return
        if len(self._records) <= self.max_records:
            return
        # Drop oldest by ``promoted_at`` first; keep last 90% to avoid churn.
        target = max(1, int(self.max_records * 0.9))
        self._records.sort(key=lambda r: r.promoted_at, reverse=True)
        self._records = self._records[:target]

    def _save(self) -> None:
        data = {
            "version": 1,
            "records": [r.to_dict() for r in self._records],
        }
        self.store_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load(self) -> None:
        if not self.store_path.exists():
            return
        try:
            raw = json.loads(self.store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict):
            return
        records: list[KnowledgeRecord] = []
        for item in raw.get("records") or []:
            if not isinstance(item, dict):
                continue
            try:
                records.append(KnowledgeRecord.from_dict(item))
            except (ValueError, TypeError):
                continue
        self._records = records


# ----------------------------------------------------- ProjectMemory hook


def auto_promote_to_kb(
    *,
    kb: GlobalKnowledgeBase,
    exemplar: Exemplar,
    project_id: str,
    framework: str = "",
    promotion_threshold: float | None = None,
) -> bool:
    """Promote a project exemplar into the global KB if it qualifies.

    Quality gate: success exemplars are always promoted; failures only
    when the caller explicitly threshold-passes them via the
    ``promotion_score`` metadata field. Returns ``True`` when the
    exemplar was added.
    """
    threshold = promotion_threshold if promotion_threshold is not None else kb.promotion_threshold
    if exemplar.outcome == "failure":
        score = float(exemplar.metadata.get(_PROMOTION_QUALITY_KEY) or 0.0)
        if score < threshold:
            return False
    kb.add_exemplar(exemplar, project_id=project_id, framework=framework)
    return True


__all__ = [
    "GlobalKnowledgeBase",
    "KnowledgeRecord",
    "auto_promote_to_kb",
]
