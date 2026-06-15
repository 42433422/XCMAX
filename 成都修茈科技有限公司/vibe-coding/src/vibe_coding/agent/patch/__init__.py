"""Multi-file precise-diff patch system.

The data model is intentionally explicit so it survives round-tripping through
LLMs and JSON: a :class:`ProjectPatch` is an ordered list of
:class:`FileEdit`, each of which is one of ``modify`` (a list of
:class:`Hunk`), ``create``, ``delete`` or ``rename``.

Hunks carry **anchor context** (≥3 lines before/after) plus the precise
``old_text`` / ``new_text`` so we can match against drifted source code with
fuzzy fallbacks while still being safer than line-number patches.

Use :class:`PatchApplier` to apply a patch atomically: every hunk is staged in
a temp directory first, conflicts roll the whole patch back, success commits
all files in one pass with a backup ledger ready for ``rollback``.
"""

from __future__ import annotations

from .applier import ApplyResult, PatchApplier, PatchConflict
from .differ import minimise_diff, hunks_from_full_rewrite
from .file_edit import FileEdit, ProjectPatch
from .hunk import Hunk

__all__ = [
    "ApplyResult",
    "FileEdit",
    "Hunk",
    "PatchApplier",
    "PatchConflict",
    "ProjectPatch",
    "hunks_from_full_rewrite",
    "minimise_diff",
]
