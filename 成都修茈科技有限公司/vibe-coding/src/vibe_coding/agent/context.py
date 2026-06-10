"""Editor / shell context the agent should be aware of when editing.

P1 surface — gives the agent enough signal to write blending-in code:

- ``active_file`` / ``cursor_line`` / ``cursor_column`` / ``selection`` —
  where the user's caret is right now (provided by the IDE plugin).
- ``recent_files`` / ``open_files`` — what's been touched recently
  (de-duplicated; truncated to ``MAX_FILES_BUDGET``).
- ``recent_edits`` — auto-populated from ``git log`` when the IDE doesn't
  feed them; each entry is ``{path, summary, timestamp}``.
- ``shell_output`` — last terminal output (truncated to ``MAX_SHELL_BUDGET``
  characters from the tail because errors live there).
- ``git_status`` — the auto-inferred ``git status`` / ``git diff --stat`` block.
- ``notes`` — free-form caller note.

Two convenience constructors:

- :meth:`from_git` — best-effort context from a git working tree (already
  shipped in P0; P1 adds ``recent_edits`` from the last few commits).
- :meth:`merge` — combine an IDE-supplied context with a git-inferred one
  so the explicit data wins where it overlaps.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Per-section budgets. Empirically prompts above ~6KB of context start to
# crowd out the actual brief and the index summary, so we cap aggressively.
MAX_RECENT_FILES = 50
MAX_OPEN_FILES = 30
MAX_RECENT_EDITS = 8
MAX_SHELL_BUDGET = 4_000
MAX_DIFF_LINES = 80


@dataclass(slots=True)
class AgentContext:
    """A snapshot of what the user is currently doing, fed into prompts.

    All fields are optional. The JSON serialisation drops ``None`` and empty
    sequences to keep the prompt overhead tight.
    """

    active_file: str | None = None
    cursor_line: int | None = None
    cursor_column: int | None = None
    selection: tuple[int, int] | None = None
    recent_files: list[str] = field(default_factory=list)
    open_files: list[str] = field(default_factory=list)
    recent_edits: list[dict[str, Any]] = field(default_factory=list)
    shell_output: str | None = None
    git_status: dict[str, Any] | None = None
    notes: str = ""

    @classmethod
    def empty(cls) -> "AgentContext":
        return cls()

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        compact: dict[str, Any] = {}
        for key, value in raw.items():
            if value is None:
                continue
            if isinstance(value, str) and not value:
                continue
            if isinstance(value, (list, tuple, dict)) and not value:
                continue
            compact[key] = value
        return compact

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "AgentContext":
        if not isinstance(raw, dict):
            return cls()
        sel_raw = raw.get("selection")
        sel: tuple[int, int] | None = None
        if isinstance(sel_raw, (list, tuple)) and len(sel_raw) == 2:
            try:
                sel = (int(sel_raw[0]), int(sel_raw[1]))
            except (TypeError, ValueError):
                sel = None
        return cls(
            active_file=str(raw["active_file"]) if raw.get("active_file") else None,
            cursor_line=int(raw["cursor_line"]) if raw.get("cursor_line") is not None else None,
            cursor_column=int(raw["cursor_column"]) if raw.get("cursor_column") is not None else None,
            selection=sel,
            recent_files=[str(x) for x in raw.get("recent_files") or []],
            open_files=[str(x) for x in raw.get("open_files") or []],
            recent_edits=[dict(x) for x in raw.get("recent_edits") or [] if isinstance(x, dict)],
            shell_output=str(raw["shell_output"]) if raw.get("shell_output") else None,
            git_status=dict(raw["git_status"]) if isinstance(raw.get("git_status"), dict) else None,
            notes=str(raw.get("notes") or ""),
        )

    @classmethod
    def from_git(
        cls,
        root: str | Path,
        *,
        max_lines: int = MAX_DIFF_LINES,
        include_recent_commits: bool = True,
    ) -> "AgentContext":
        """Best-effort context inferred from ``git status`` / ``git diff``.

        P1 enhancement: also populate :attr:`recent_edits` from the last
        few commits (when ``include_recent_commits=True``) — this gives
        the LLM a sense of "what kind of changes the user has been making
        recently" without an IDE plugin. Each entry is shaped
        ``{path, summary, timestamp}``.

        Returns an empty :class:`AgentContext` if Git is unavailable or
        the path is not a repo.
        """
        ctx = cls()
        if shutil.which("git") is None:
            return ctx
        root_path = Path(root).resolve()
        if not root_path.is_dir():
            return ctx
        try:
            status_proc = subprocess.run(
                ["git", "status", "--porcelain=v1"],
                cwd=str(root_path),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return ctx
        if status_proc.returncode != 0:
            return ctx
        files: list[str] = []
        for line in (status_proc.stdout or "").splitlines():
            if len(line) < 4:
                continue
            files.append(line[3:].strip())
        ctx.recent_files = files[:MAX_RECENT_FILES]
        try:
            diff_proc = subprocess.run(
                ["git", "diff", "--no-color", "--stat", "HEAD"],
                cwd=str(root_path),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return ctx
        if diff_proc.returncode == 0:
            stat_lines = (diff_proc.stdout or "").splitlines()[:max_lines]
            ctx.git_status = {
                "stat": "\n".join(stat_lines),
                "dirty_count": len(files),
            }
        if include_recent_commits:
            ctx.recent_edits = _git_recent_edits(root_path, limit=MAX_RECENT_EDITS)
        return ctx

    def merge(self, other: "AgentContext") -> "AgentContext":
        """Combine ``self`` (high-priority) with ``other`` (fallback).

        Scalar fields take ``self``'s value if non-empty; list fields are
        concatenated then deduplicated preserving order; dicts are
        shallow-merged with ``self`` winning on overlapping keys.

        Use this to merge an IDE-supplied context with the auto-inferred
        :meth:`from_git` data — explicit signals beat heuristic ones.
        """

        def first(a: Any, b: Any) -> Any:
            return a if a not in (None, "", [], {}) else b

        def dedupe(*seqs: list[str]) -> list[str]:
            out: list[str] = []
            seen: set[str] = set()
            for seq in seqs:
                for item in seq:
                    if item not in seen:
                        seen.add(item)
                        out.append(item)
            return out

        return AgentContext(
            active_file=first(self.active_file, other.active_file),
            cursor_line=first(self.cursor_line, other.cursor_line),
            cursor_column=first(self.cursor_column, other.cursor_column),
            selection=first(self.selection, other.selection),
            recent_files=dedupe(self.recent_files, other.recent_files)[
                :MAX_RECENT_FILES
            ],
            open_files=dedupe(self.open_files, other.open_files)[:MAX_OPEN_FILES],
            recent_edits=(self.recent_edits or other.recent_edits)[:MAX_RECENT_EDITS],
            shell_output=_truncate_tail(
                first(self.shell_output, other.shell_output), MAX_SHELL_BUDGET
            ),
            git_status={**(other.git_status or {}), **(self.git_status or {})}
            or None,
            notes=first(self.notes, other.notes),
        )

    def select_focus_files(
        self,
        candidates: list[str],
        *,
        limit: int = 20,
    ) -> list[str]:
        """Rank ``candidates`` by relevance to the current context.

        Ranking signals (highest weight first):

        1. ``active_file`` exact match → top of the list.
        2. Files in ``open_files`` → next.
        3. Files in ``recent_files`` → next.
        4. Files mentioned in ``recent_edits[*].path`` → next.
        5. Everything else → tail order preserved.

        Output is deduped, never includes paths missing from
        ``candidates`` and is truncated to ``limit``.
        """
        candidate_set = set(candidates)
        ranked: list[str] = []
        seen: set[str] = set()

        def add(rel: str | None) -> None:
            if not rel:
                return
            norm = rel.replace("\\", "/")
            if norm in candidate_set and norm not in seen:
                ranked.append(norm)
                seen.add(norm)

        add(self.active_file)
        for name in self.open_files:
            add(name)
        for name in self.recent_files:
            add(name)
        for entry in self.recent_edits:
            if isinstance(entry, dict):
                add(str(entry.get("path") or ""))
        for name in candidates:
            add(name)
        return ranked[:limit]

    def to_prompt_block(self) -> str:
        """Render a compact prompt block; empty when no context is set.

        Applies per-section budgets (``MAX_RECENT_FILES``, ``MAX_OPEN_FILES``,
        ``MAX_RECENT_EDITS``, ``MAX_SHELL_BUDGET``) so prompt overhead stays
        bounded even when the IDE feeds in a long history.
        """
        compact = self.to_dict()
        if not compact:
            return ""
        # Apply truncation right before serialisation so we never silently
        # mutate the in-memory ``AgentContext``.
        if "recent_files" in compact:
            compact["recent_files"] = compact["recent_files"][:MAX_RECENT_FILES]
        if "open_files" in compact:
            compact["open_files"] = compact["open_files"][:MAX_OPEN_FILES]
        if "recent_edits" in compact:
            compact["recent_edits"] = compact["recent_edits"][:MAX_RECENT_EDITS]
        if "shell_output" in compact:
            compact["shell_output"] = _truncate_tail(
                compact["shell_output"], MAX_SHELL_BUDGET
            )
        return "## 当前编辑器上下文\n```json\n" + json.dumps(
            compact, ensure_ascii=False, indent=2
        ) + "\n```"


def _git_recent_edits(root: Path, *, limit: int) -> list[dict[str, Any]]:
    """Fetch the last ``limit`` commit summaries from ``git log``.

    Each entry is shaped ``{path: "", summary: "...", timestamp: ""}``
    where ``path`` is the *first* file changed in that commit (often the
    most relevant), and ``summary`` is the commit subject. Returns an
    empty list when git is unavailable or the call fails.
    """
    if shutil.which("git") is None:
        return []
    try:
        proc = subprocess.run(
            [
                "git",
                "log",
                f"-n{int(limit)}",
                "--no-color",
                "--name-only",
                "--pretty=format:%h\x1f%s\x1f%cI",
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if proc.returncode != 0 or not proc.stdout:
        return []
    out: list[dict[str, Any]] = []
    blocks = proc.stdout.split("\n\n")
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        head = lines[0]
        if "\x1f" not in head:
            continue
        try:
            sha, summary, timestamp = head.split("\x1f", 2)
        except ValueError:
            continue
        files = lines[1:]
        path = files[0] if files else ""
        out.append(
            {
                "sha": sha.strip(),
                "path": path.strip(),
                "summary": summary.strip()[:200],
                "timestamp": timestamp.strip(),
                "file_count": len(files),
            }
        )
        if len(out) >= limit:
            break
    return out


def _truncate_tail(text: str | None, limit: int) -> str | None:
    """Keep only the last ``limit`` characters; prefix a marker if truncated.

    Tail-bias is intentional: shell output is usually most informative at
    the end (the actual error / failure surface), so trimming the head
    preserves signal.
    """
    if text is None:
        return None
    if limit <= 0 or len(text) <= limit:
        return text
    return f"... (truncated {len(text) - limit} chars from start)\n{text[-limit:]}"


__all__ = ["AgentContext"]
