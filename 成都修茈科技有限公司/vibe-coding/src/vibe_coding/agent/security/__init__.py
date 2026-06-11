"""Cross-cutting safety primitives for the agent.

Two concerns are centralised here so the rest of the codebase has exactly one
place to enforce them:

- :mod:`.paths` — relative-path validation. Every code path that turns an
  LLM-supplied (or generally untrusted) string into a filesystem location goes
  through :func:`safe_relative_path` / :func:`resolve_within_root`. Catches
  path traversal (``..``), absolute paths, Windows drive letters, NUL bytes,
  symlink escapes and tilde expansion.
- :mod:`.env` — environment variable scrubbing for sandbox jobs. The default
  allow-list (``PATH``, ``LANG``, ``HOME`` …) means we never accidentally
  forward LLM-supplied environment additions or host secrets (``OPENAI_API_KEY``,
  ``AWS_*`` …) into a freshly-spawned subprocess.

Both modules are intentionally dependency-free so they can be imported from
anywhere in the package without dragging the agent layer along.
"""

from __future__ import annotations

from .env import DEFAULT_ENV_ALLOWLIST, sanitise_env
from .paths import (
    PathSafetyError,
    is_safe_relative,
    resolve_within_root,
    safe_relative_path,
)

__all__ = [
    "DEFAULT_ENV_ALLOWLIST",
    "PathSafetyError",
    "is_safe_relative",
    "resolve_within_root",
    "safe_relative_path",
    "sanitise_env",
]
