"""High-level project-aware facade — the agent counterpart of :class:`VibeCoder`.

:class:`ProjectVibeCoder` ties the four P0 capabilities together:

- :class:`RepoIndex` (code understanding)
- :class:`ProjectPatch` + :class:`PatchApplier` (multi-file + precise diff)
- :class:`AgentContext` (P1 will fill it in further; usable today)
- :class:`SandboxDriver` (subprocess by default, Docker when available)

The class is constructed with an :class:`LLMClient` and a project root; all
its methods are pure-Python and accept dependency overrides for tests. P1's
``DebugReasoner`` and P1's ``ToolRunner`` slot in via constructor parameters
when they exist; today they are placeholders so callers can wire them later
without breaking existing call sites.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..nl.llm import LLMClient
from ..nl.parsing import JSONParseError, safe_parse_json_object
from ..nl.prompts import MULTI_FILE_EDIT_PROMPT, MULTI_FILE_REPAIR_PROMPT
from .context import AgentContext
from .domain import DomainViolation, ProjectDomainGuard
from .memory import ProjectMemory
from .patch import (
    ApplyResult,
    FileEdit,
    Hunk,
    PatchApplier,
    ProjectPatch,
    minimise_diff,
)
from .repo_index import LanguageAdapter, RepoIndex, build_index
from .sandbox import (
    SandboxDriver,
    SandboxJob,
    SandboxPolicy,
    SandboxResult,
    SubprocessSandboxDriver,
    create_default_driver,
)

_INDEX_FILENAME = "repo_index.json"


class ProjectVibeCodingError(RuntimeError):
    """Raised by :class:`ProjectVibeCoder` for fatal generation failures."""


@dataclass(slots=True)
class HealRound:
    """One iteration of :meth:`ProjectVibeCoder.heal_project`."""

    round_index: int
    patch_id: str
    summary: str
    apply_result: ApplyResult
    tool_reports: list[dict[str, Any]] = field(default_factory=list)
    success: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_index": self.round_index,
            "patch_id": self.patch_id,
            "summary": self.summary,
            "apply_result": self.apply_result.to_dict(),
            "tool_reports": list(self.tool_reports),
            "success": self.success,
            "error": self.error,
        }


@dataclass(slots=True)
class HealResult:
    """Outcome of :meth:`ProjectVibeCoder.heal_project`."""

    brief: str
    success: bool
    rounds: list[HealRound] = field(default_factory=list)
    final_patch_id: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "brief": self.brief,
            "success": self.success,
            "rounds": [r.to_dict() for r in self.rounds],
            "final_patch_id": self.final_patch_id,
            "error": self.error,
        }


class ProjectVibeCoder:
    """Project-scoped coding agent.

    Keep one instance per ``(root, store_dir)`` pair. The instance caches its
    :class:`RepoIndex` and reuses the same :class:`PatchApplier`, so repeated
    edits within a session don't pay the indexing cost more than once.
    """

    def __init__(
        self,
        *,
        llm: LLMClient,
        root: str | Path,
        store_dir: str | Path | None = None,
        adapters: list[LanguageAdapter] | None = None,
        sandbox: SandboxDriver | None = None,
        applier: PatchApplier | None = None,
        memory: ProjectMemory | None = None,
        domain_guard: ProjectDomainGuard | None = None,
        max_files_in_prompt: int = 20,
        max_file_chars: int = 4_000,
        use_memory: bool = True,
        memory_exemplars: int = 3,
    ) -> None:
        self.llm = llm
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError(f"root {self.root!r} is not a directory")
        self.store_dir = Path(store_dir) if store_dir else self.root / ".vibe_coding"
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.adapters = adapters
        self.sandbox: SandboxDriver = sandbox or _safe_default_driver()
        self.applier = applier or PatchApplier(self.root, backup_dir=self.store_dir / "patch_backups")
        self.memory: ProjectMemory = memory or ProjectMemory(self.store_dir)
        self.domain_guard: ProjectDomainGuard | None = domain_guard
        self.use_memory = use_memory
        self.memory_exemplars = memory_exemplars
        self.max_files_in_prompt = int(max_files_in_prompt)
        self.max_file_chars = int(max_file_chars)
        self._index: RepoIndex | None = None

    # ------------------------------------------------------------------ index

    def index_project(self, *, refresh: bool = False) -> RepoIndex:
        index_path = self.store_dir / _INDEX_FILENAME
        if not refresh and self._index is not None:
            return self._index
        previous: RepoIndex | None = None
        if not refresh and index_path.exists():
            previous = RepoIndex.load(self.root, index_path)
        index = build_index(self.root, adapters=self.adapters, previous=previous)
        index.save(index_path)
        self._index = index
        return index

    # ------------------------------------------------------------------ edit

    def edit_project(
        self,
        brief: str,
        *,
        context: AgentContext | None = None,
        focus_paths: list[str] | None = None,
    ) -> ProjectPatch:
        if not brief or not brief.strip():
            raise ProjectVibeCodingError("brief is required")
        index = self.index_project()
        prompt_user = self._build_edit_user_prompt(brief, index, context, focus_paths)
        raw = self.llm.chat(MULTI_FILE_EDIT_PROMPT, prompt_user, json_mode=True)
        patch = self._parse_patch(raw)
        patch = self._normalise_full_rewrites(patch)
        return patch

    def repair_project(
        self,
        failure: str,
        *,
        context: AgentContext | None = None,
        focus_paths: list[str] | None = None,
    ) -> ProjectPatch:
        if not failure or not failure.strip():
            raise ProjectVibeCodingError("failure is required")
        index = self.index_project()
        prompt_user = self._build_repair_user_prompt(failure, index, context, focus_paths)
        raw = self.llm.chat(MULTI_FILE_REPAIR_PROMPT, prompt_user, json_mode=True)
        patch = self._parse_patch(raw)
        patch = self._normalise_full_rewrites(patch)
        return patch

    def apply_patch(
        self,
        patch: ProjectPatch,
        *,
        dry_run: bool = False,
        record_in_memory: bool = False,
        brief: str = "",
        tools_passed: list[str] | None = None,
        domain_guard: ProjectDomainGuard | None = None,
    ) -> ApplyResult:
        guard = domain_guard or self.domain_guard
        if guard is not None:
            violations = guard.validate(patch)
            if violations:
                return ApplyResult(
                    patch_id=patch.patch_id,
                    applied=False,
                    dry_run=dry_run,
                    error="domain_guard:" + "; ".join(
                        f"[{v.code}] {v.message}" + (f" ({v.file})" if v.file else "")
                        for v in violations
                    ),
                )
        result = self.applier.apply(patch, dry_run=dry_run)
        if result.applied and not dry_run:
            self._invalidate_index_for(patch)
            if record_in_memory and self.use_memory:
                index = self.index_project()
                self.memory.rebuild_style(index)
                self.memory.record_success(
                    brief or patch.summary,
                    patch,
                    tools_passed=tools_passed,
                    languages=index.languages,
                )
        return result

    def rollback_patch(self, patch_id: str) -> bool:
        ok = self.applier.rollback(patch_id)
        if ok:
            self._index = None
        return ok

    # ------------------------------------------------------------------ heal

    def heal_project(
        self,
        brief: str,
        *,
        context: AgentContext | None = None,
        max_rounds: int = 3,
        tool_runner: Any | None = None,
    ) -> HealResult:
        """Edit + tool-validate + repair loop.

        ``tool_runner`` is the P1 ``ToolRunner`` instance; if ``None`` we
        skip the tool-validation phase (the round still succeeds based on
        applier feedback alone). When the loop runs out of rounds the
        result records ``success=False`` with the last round's error.

        Memory hooks (P2): every successful round records the patch as a
        success exemplar; every failed round records it as a failure
        exemplar so future runs can read both the good patterns and the
        traps. Set ``use_memory=False`` on the constructor to disable
        memory writes entirely.
        """
        result = HealResult(brief=brief, success=False)
        last_failure = brief
        for idx in range(1, max_rounds + 1):
            if idx == 1:
                patch = self.edit_project(brief, context=context)
            else:
                patch = self.repair_project(last_failure, context=context)

            apply_res = self.apply_patch(patch, dry_run=False)
            round_record = HealRound(
                round_index=idx,
                patch_id=patch.patch_id,
                summary=patch.summary,
                apply_result=apply_res,
            )
            if not apply_res.applied:
                round_record.error = apply_res.error or "apply_failed"
                last_failure = round_record.error
                result.rounds.append(round_record)
                self._record_failure_to_memory(brief, patch, round_record.error, tools_failed=[])
                if not patch.edits:
                    result.error = "LLM returned empty patch"
                    break
                continue

            tool_failures: list[dict[str, Any]] = []
            if tool_runner is not None:
                reports = tool_runner.run_all(self.root)
                round_record.tool_reports = [r.to_dict() for r in reports]
                tool_failures = [r.to_dict() for r in reports if not r.passed]
            if not tool_failures:
                round_record.success = True
                result.rounds.append(round_record)
                result.success = True
                result.final_patch_id = patch.patch_id
                self._record_success_to_memory(
                    brief,
                    patch,
                    tools_passed=[t["tool"] for t in (round_record.tool_reports or [])],
                )
                return result
            round_record.error = "tool_failed: " + ", ".join(t["tool"] for t in tool_failures)
            last_failure = round_record.error + "\n" + json.dumps(tool_failures, ensure_ascii=False)
            result.rounds.append(round_record)
            self._record_failure_to_memory(
                brief,
                patch,
                round_record.error,
                tools_failed=[t["tool"] for t in tool_failures],
            )
        if not result.success:
            result.error = result.rounds[-1].error if result.rounds else "no rounds executed"
        return result

    def _record_success_to_memory(
        self,
        brief: str,
        patch: ProjectPatch,
        *,
        tools_passed: list[str],
    ) -> None:
        if not self.use_memory:
            return
        try:
            index = self.index_project()
            self.memory.rebuild_style(index)
            self.memory.record_success(
                brief,
                patch,
                tools_passed=tools_passed,
                languages=index.languages,
            )
        except Exception:  # noqa: BLE001
            # Memory writes must never break a successful heal round.
            pass

    def _record_failure_to_memory(
        self,
        brief: str,
        patch: ProjectPatch | None,
        error: str,
        *,
        tools_failed: list[str],
    ) -> None:
        if not self.use_memory:
            return
        try:
            index = self.index_project()
            self.memory.record_failure(
                brief,
                patch,
                error=error,
                tools_failed=tools_failed,
                languages=index.languages,
            )
        except Exception:  # noqa: BLE001
            pass

    # ---------------------------------------------------------------- prompts

    def _build_edit_user_prompt(
        self,
        brief: str,
        index: RepoIndex,
        context: AgentContext | None,
        focus_paths: list[str] | None,
    ) -> str:
        sections = [f"## 用户需求\n{brief.strip()}", _format_index_summary(index)]
        if self.use_memory:
            mem_block = self.memory.to_prompt_block(brief, k=self.memory_exemplars)
            if mem_block:
                sections.append(mem_block)
        if context is not None:
            block = context.to_prompt_block()
            if block:
                sections.append(block)
        sections.append(self._format_focus_files(index, context, focus_paths))
        sections.append(
            "## 输出要求\n严格按照 ProjectPatch JSON 输出。不要整文件重写。"
        )
        return "\n\n".join(s for s in sections if s)

    def _build_repair_user_prompt(
        self,
        failure: str,
        index: RepoIndex,
        context: AgentContext | None,
        focus_paths: list[str] | None,
    ) -> str:
        sections = [
            f"## 失败信息\n```\n{failure.strip()[:8_000]}\n```",
            _format_index_summary(index),
        ]
        if context is not None:
            block = context.to_prompt_block()
            if block:
                sections.append(block)
        sections.append(self._format_focus_files(index, context, focus_paths))
        sections.append(
            "## 输出要求\n严格按照 ProjectPatch JSON 输出。改动尽量小，禁止整文件重写。"
        )
        return "\n\n".join(s for s in sections if s)

    def _format_focus_files(
        self,
        index: RepoIndex,
        context: AgentContext | None,
        focus_paths: list[str] | None,
    ) -> str:
        """Pick the most-relevant N files via :meth:`AgentContext.select_focus_files`.

        Ranking rationale:

        - ``focus_paths`` (caller-supplied) goes first — explicit always wins.
        - Then the agent-context heuristic (active file → open files →
          recent files → recent commit-touched files).
        - Finally a deterministic fallback over ``index.files`` so prompts
          stay populated even when no context is available.

        The output respects ``max_files_in_prompt`` and per-file
        ``max_file_chars`` so total prompt size stays bounded.
        """
        candidates: list[str] = list(focus_paths or [])
        # Always include every indexed file so the ranker can promote
        # context-relevant ones; deduplication is its job.
        candidates.extend(index.files.keys())

        if context is not None:
            ranked = context.select_focus_files(candidates, limit=self.max_files_in_prompt)
        else:
            ranked = []
            seen: set[str] = set()
            for raw in candidates:
                rel = raw.replace("\\", "/")
                if rel in index.files and rel not in seen:
                    ranked.append(rel)
                    seen.add(rel)
                if len(ranked) >= self.max_files_in_prompt:
                    break
        if not ranked:
            return ""
        snippets: list[str] = ["## 相关文件片段（只读引用，不要照抄）"]
        for rel in ranked:
            entry = index.files.get(rel)
            if entry is None:
                continue
            full_path = self.root / Path(rel)
            try:
                source = full_path.read_text(encoding="utf-8")
            except OSError:
                continue
            if len(source) > self.max_file_chars:
                source = source[: self.max_file_chars] + "\n# ... (truncated)\n"
            snippets.append(
                f"### {rel} ({entry.language}, {entry.line_count} lines)\n```\n{source}\n```"
            )
        return "\n\n".join(snippets)

    # ----------------------------------------------------------------- parse

    def _parse_patch(self, raw: str) -> ProjectPatch:
        try:
            data = safe_parse_json_object(raw)
        except JSONParseError as exc:
            snippet = exc.snippet or str(raw or "")[:200]
            raise ProjectVibeCodingError(f"LLM did not return JSON: {snippet!r}") from exc
        try:
            return ProjectPatch.from_dict(data)
        except (TypeError, ValueError) as exc:
            raise ProjectVibeCodingError(f"invalid ProjectPatch shape: {exc}") from exc

    def _normalise_full_rewrites(self, patch: ProjectPatch) -> ProjectPatch:
        """Detect ``modify`` edits that look like full-file rewrites and
        downgrade them into minimal hunks via :func:`minimise_diff`.
        """
        for edit in patch.edits:
            if edit.operation != "modify":
                continue
            if not edit.hunks and edit.contents is not None:
                # The LLM put the new contents in ``contents`` instead of
                # ``hunks``; reconstruct the minimal diff.
                target = self.root / Path(edit.path)
                if target.is_file():
                    try:
                        original = target.read_text(encoding="utf-8")
                    except OSError:
                        continue
                    edit.hunks = list(minimise_diff(original, edit.contents))
                    edit.contents = None
        return patch

    def _invalidate_index_for(self, patch: ProjectPatch) -> None:
        if self._index is None:
            return
        touched = patch.files_touched()
        self._index.remove_files(touched)
        # On next index_project() call we'll do an incremental re-build.
        # Force that by clearing the cache.
        self._index = None


# ---------------------------------------------------------------------- helpers


def _format_index_summary(index: RepoIndex) -> str:
    summary = index.summary()
    return (
        "## 项目摘要\n"
        + json.dumps(summary, ensure_ascii=False, indent=2)
        + "\n\n顶层结构（最多 30 个目录/文件）：\n"
        + _format_tree(index)
    )


def _format_tree(index: RepoIndex, *, limit: int = 30) -> str:
    paths = sorted(index.files.keys())[:limit]
    return "\n".join(f"- {p}" for p in paths) or "(empty)"


def _safe_default_driver() -> SandboxDriver:
    try:
        return create_default_driver(prefer="auto")
    except RuntimeError:
        return SubprocessSandboxDriver()


__all__ = [
    "HealResult",
    "HealRound",
    "ProjectVibeCoder",
    "ProjectVibeCodingError",
]


# Defensive references for type-checkers
_ = (SandboxJob, SandboxPolicy, SandboxResult, FileEdit, Hunk)  # noqa: F841
