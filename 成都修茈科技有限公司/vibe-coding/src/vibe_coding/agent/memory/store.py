"""Unified :class:`ProjectMemory` that wires style + exemplars + retrieval."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Literal, TYPE_CHECKING

from .exemplars import Exemplar, ExemplarStore
from .retriever import Retriever
from .style import StyleProfile

if TYPE_CHECKING:
    from ..repo_index import RepoIndex
    from ..patch import ProjectPatch

_MEMORY_FILENAME = "memory.json"
_DEFAULT_MAX_EXEMPLARS = 200


class ProjectMemory:
    """Persistent project-level learning and memory.

    Backed by ``<store_dir>/memory.json``. Thread-safe via a reentrant lock.
    All data is stored lazily — calling :meth:`rebuild_style` or
    :meth:`record_success` is the only way to populate it.

    P2 enhancements:

    - ``max_exemplars`` (default 200) caps the on-disk size; the store is
      auto-pruned via the ``prune_strategy`` strategy after every record.
    - :meth:`record_failure` lets the heal loop log negative examples that
      the retriever surfaces alongside successes (callers decide whether
      to use them as warnings).
    - :meth:`retrieve` updates ``last_used_at`` on each returned exemplar
      so LRU pruning has accurate signal.
    """

    def __init__(
        self,
        store_dir: str | Path,
        *,
        max_exemplars: int = _DEFAULT_MAX_EXEMPLARS,
        prune_strategy: Literal["lru", "oldest", "failures_first"] = "lru",
        knowledge_base: "Any | None" = None,
        project_id: str = "",
        framework: str = "",
        auto_promote: bool = True,
    ) -> None:
        self._path = Path(store_dir) / _MEMORY_FILENAME
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._style: StyleProfile = StyleProfile()
        self._exemplars: ExemplarStore = ExemplarStore()
        self._retriever: Retriever | None = None
        self._max_exemplars = int(max_exemplars)
        self._prune_strategy = prune_strategy
        self.knowledge_base = knowledge_base
        self.project_id = project_id
        self.framework = framework
        self.auto_promote = bool(auto_promote)
        self._load()

    # ------------------------------------------------------------------ style

    def rebuild_style(self, index: "RepoIndex") -> StyleProfile:
        with self._lock:
            self._style = StyleProfile.from_index(index)
            self._save()
            return self._style

    @property
    def style(self) -> StyleProfile:
        return self._style

    # ---------------------------------------------------------------- exemplars

    def record_success(
        self,
        brief: str,
        patch: "ProjectPatch",
        *,
        tools_passed: list[str] | None = None,
        languages: list[str] | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Exemplar:
        with self._lock:
            ex = Exemplar(
                brief=brief.strip(),
                patch_id=patch.patch_id,
                summary=patch.summary,
                diff_text=_render_diff_text(patch),
                tools_passed=list(tools_passed or []),
                languages=list(languages or []),
                outcome="success",
                tags=list(tags or []),
                metadata=dict(metadata or {}),
            )
            self._exemplars.add(ex)
            self._retriever = None
            self._auto_prune()
            self._save()
        # Auto-promote to the cross-project KB after we've persisted the
        # local memory; the KB has its own lock so we don't nest.
        self._maybe_promote(ex)
        return ex

    def record_failure(
        self,
        brief: str,
        patch: "ProjectPatch | None" = None,
        *,
        error: str = "",
        tools_failed: list[str] | None = None,
        languages: list[str] | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Exemplar:
        """Log a failed attempt so the LLM can learn from it.

        ``patch`` is optional — sometimes the LLM's first attempt fails
        before producing a patch (parse error etc). In that case we still
        want to remember the brief and the error so the next try doesn't
        repeat the same mistake.
        """
        with self._lock:
            patch_id = patch.patch_id if patch is not None else f"failed-{int(_now())}"
            summary = patch.summary if patch is not None else error[:120]
            diff_text = _render_diff_text(patch) if patch is not None else ""
            ex = Exemplar(
                brief=brief.strip(),
                patch_id=patch_id,
                summary=summary,
                diff_text=diff_text,
                tools_passed=[],
                tools_failed=list(tools_failed or []),
                languages=list(languages or []),
                outcome="failure",
                error=error[:1_000],
                tags=list(tags or []) + ["failure"],
                metadata=dict(metadata or {}),
            )
            self._exemplars.add(ex)
            self._retriever = None
            self._auto_prune()
            self._save()
            return ex

    def retrieve(
        self,
        query: str,
        k: int = 3,
        *,
        outcome: Literal["success", "failure", "any"] = "success",
    ) -> list[Exemplar]:
        with self._lock:
            if self._retriever is None or outcome != "any":
                pool = self._exemplars.all()
                if outcome == "success":
                    pool = [e for e in pool if e.outcome == "success"]
                elif outcome == "failure":
                    pool = [e for e in pool if e.outcome == "failure"]
                self._retriever = Retriever(pool)
            results = self._retriever.search(query, k=k)
            # Bump last_used_at for LRU pruning fairness.
            for ex in results:
                ex.touch()
            if results:
                self._save()
            return results

    def _maybe_promote(self, ex: Exemplar) -> None:
        """Best-effort cross-project promotion via :func:`auto_promote_to_kb`."""
        if not self.auto_promote or self.knowledge_base is None:
            return
        try:
            from .knowledge_base import auto_promote_to_kb

            auto_promote_to_kb(
                kb=self.knowledge_base,
                exemplar=ex,
                project_id=self.project_id,
                framework=self.framework,
            )
        except Exception:  # noqa: BLE001
            # Promotion never breaks a successful memory write.
            pass

    def prune_now(self) -> int:
        """Manually trigger pruning. Returns the number of removed entries."""
        with self._lock:
            removed = self._exemplars.prune(self._max_exemplars, strategy=self._prune_strategy)
            if removed:
                self._retriever = None
                self._save()
            return removed

    def _auto_prune(self) -> None:
        if self._max_exemplars <= 0:
            return
        if len(self._exemplars) <= self._max_exemplars:
            return
        # Slightly over-budget pruning: drop down to 90% of the cap so we
        # don't churn on every record.
        target = max(1, int(self._max_exemplars * 0.9))
        self._exemplars.prune(target, strategy=self._prune_strategy)
        self._retriever = None

    # ----------------------------------------------------------------- prompt

    def to_prompt_block(
        self,
        brief: str,
        *,
        k: int = 3,
        include_failures: bool = True,
        failure_k: int = 2,
    ) -> str:
        """Return a combined prompt block: style + top-K successes + recent failures.

        Failures are rendered as a "things to avoid" section so the LLM
        treats them as warnings rather than templates. Set
        ``include_failures=False`` to suppress the failure section if the
        prompt budget is tight.
        """
        parts: list[str] = []
        style_block = self._style.to_prompt_block()
        if style_block:
            parts.append(style_block)
        successes = self.retrieve(brief, k=k, outcome="success")
        if successes:
            lines = ["## 历史相关范例（仅供参考，不要照抄）"]
            for idx, ex in enumerate(successes, 1):
                lines.append(
                    f"### 范例 {idx} — {ex.summary or ex.brief[:60]}\n"
                    f"原始需求: {ex.brief[:120]}\n"
                    f"diff 片段:\n```\n{ex.diff_text[:600]}\n```"
                )
            parts.append("\n\n".join(lines))
        if include_failures:
            failures = self.retrieve(brief, k=failure_k, outcome="failure")
            if failures:
                lines = ["## 历史失败（**请避免重复**）"]
                for idx, ex in enumerate(failures, 1):
                    lines.append(
                        f"### 失败 {idx} — {ex.summary or ex.brief[:60]}\n"
                        f"原始需求: {ex.brief[:120]}\n"
                        f"失败原因: {ex.error[:300]}\n"
                        f"未通过的工具: {', '.join(ex.tools_failed) or '(无)'}\n"
                        f"diff 片段:\n```\n{ex.diff_text[:400] or '(无)'}\n```"
                    )
                parts.append("\n\n".join(lines))
        return "\n\n".join(parts)

    # ------------------------------------------------------------------ I/O

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict):
            return
        if "style" in raw and isinstance(raw["style"], dict):
            self._style = StyleProfile.from_dict(raw["style"])
        if "exemplars" in raw and isinstance(raw["exemplars"], list):
            self._exemplars = ExemplarStore.from_list(raw["exemplars"])

    def _save(self) -> None:
        data: dict[str, Any] = {
            "style": self._style.to_dict(),
            "exemplars": self._exemplars.to_list(),
        }
        self._path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def _render_diff_text(patch: "ProjectPatch") -> str:
    """Compact ``+/-`` rendering of a patch for indexing.

    We trim each hunk's text and cap the total at ~100 lines so an
    unusually large patch doesn't dominate the BM25 corpus.
    """
    lines: list[str] = []
    for edit in patch.edits:
        for hunk in edit.hunks:
            old = (hunk.old_text or "").strip()
            new = (hunk.new_text or "").strip()
            if old:
                lines.append(f"- {old}")
            if new:
                lines.append(f"+ {new}")
    return "\n".join(lines[:100])


def _now() -> float:
    import time as _t

    return _t.time()


__all__ = ["ProjectMemory"]
