"""Environment-variable scrubbing for sandbox jobs.

Without scrubbing, every ``subprocess.run`` we spawn from the sandbox driver
inherits *the entire parent environment*. That means:

- ``OPENAI_API_KEY`` (and every other LLM credential) becomes readable by
  whatever code the LLM itself wrote.
- ``AWS_ACCESS_KEY_ID`` / ``GOOGLE_APPLICATION_CREDENTIALS`` / vault tokens
  flow into untrusted test runs.
- Implementation-specific variables like ``PYTHONDONTWRITEBYTECODE`` /
  ``PYTHONHASHSEED`` may break the sandboxed code in subtle ways.

The default allow-list keeps only what's required to run linters / type
checkers / test runners (the ``PATH`` for executable lookup, ``LANG`` /
``LC_ALL`` so Python doesn't choke on UTF-8 stdout, ``HOME`` so tools that
write caches into ``$HOME/.cache`` don't crash, ``TMPDIR`` so they pick the
sandbox's tmpfs). Everything else has to be opted in via ``extra_allow``
or :class:`SandboxJob.env`.
"""

from __future__ import annotations

import os
from typing import Iterable, Mapping

# Curated allow-list. Resist the temptation to add ``*_KEY`` / ``*_SECRET``
# / ``*_TOKEN`` style variables — if a tool needs one, the caller can pass
# it explicitly via the ``env`` argument and they'll see the leak in
# their code review.
DEFAULT_ENV_ALLOWLIST: frozenset[str] = frozenset(
    {
        "PATH",
        "PATHEXT",  # Windows uses this to find ``.cmd`` / ``.exe``
        "SYSTEMROOT",  # Windows: many CLIs (incl. Python) need this
        "WINDIR",  # Windows
        "COMSPEC",  # Windows
        "HOME",
        "USERPROFILE",  # Windows analogue of HOME
        "USERNAME",  # Windows
        "USER",
        "LOGNAME",
        "SHELL",
        "LANG",
        "LANGUAGE",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "TMPDIR",
        "TEMP",
        "TMP",
        "PYTHONIOENCODING",
        "PYTHONUNBUFFERED",
        # Some toolchains (mypy, ruff, pytest) honour these for cache placement.
        "MYPY_CACHE_DIR",
        "RUFF_CACHE_DIR",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
    }
)


def sanitise_env(
    *,
    extra_allow: Iterable[str] | None = None,
    overrides: Mapping[str, str] | None = None,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a sanitised env dict suitable for handing to ``subprocess.run``.

    Steps:

    1. Start from ``base`` (default: ``os.environ``) filtered down to keys in
       ``DEFAULT_ENV_ALLOWLIST | extra_allow``.
    2. Apply ``overrides`` last — explicit wins over inherited.
    3. ``PYTHONIOENCODING`` defaults to ``utf-8`` so subprocesses don't blow
       up on non-ASCII paths.
    """
    base_env = dict(base if base is not None else os.environ)
    allow = set(DEFAULT_ENV_ALLOWLIST)
    if extra_allow:
        allow.update(str(name) for name in extra_allow)
    out: dict[str, str] = {}
    for key, value in base_env.items():
        if key in allow:
            out[key] = str(value)
    if overrides:
        for key, value in overrides.items():
            if value is None:
                out.pop(str(key), None)
            else:
                out[str(key)] = str(value)
    out.setdefault("PYTHONIOENCODING", "utf-8")
    return out


__all__ = ["DEFAULT_ENV_ALLOWLIST", "sanitise_env"]
