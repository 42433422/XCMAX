#!/usr/bin/env python3
"""Coverage audit: ensure every file in the repo is owned by some employee or is on the explicit-ignore list.

Output:
- exit 0 if every non-ignored file matches at least one employee's scope_globs.
- exit 1 with a list of orphan paths otherwise.

Run:
  $ python -m scripts.coverage_audit
  $ python -m scripts.coverage_audit --max-show 50
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
YUANGON_DIR = REPO_ROOT / "yuangon"

# Explicit ignore globs (mirrors yuangon/_shared/OWNERSHIP.md §五).
DEFAULT_IGNORES: list[str] = [
    "**/__pycache__/**",
    "**/.pytest_cache/**",
    "**/.mypy_cache/**",
    "**/.ruff_cache/**",
    "**/node_modules/**",
    "**/.venv/**",
    "**/.git/**",
    "**/dist/**",
    "**/modstore.egg-info/**",
    "**/*.pyc",
    "**/*.pyo",
    "**/.DS_Store",
    "**/._*",
    "*.bak.*",
    ".coverage",
    "MODstore_deploy/.coverage",
    "MODstore_deploy/.venv/**",
    "MODstore_deploy/.mypy_cache/**",
    "MODstore_deploy/.pytest_cache/**",
    "MODstore_deploy/.ruff_cache/**",
    # Per-employee runtime data managed by MODstore itself.
    "MODstore_deploy/var/**",
    "MODstore_deploy/modstore_server/data/**",
    "MODstore_deploy/modstore_server/catalog_data/**",
    "MODstore_deploy/modstore_server/library/**",
    "MODstore_deploy/modstore_server/vector_data/**",
    "MODstore_deploy/modstore_server/script_agent/**",
    # User-installed mods/employees (managed at runtime, not by yuangon employees).
    "MODstore_deploy/library/**",
    "MODstore_deploy/keys/**",
    "MODstore_deploy/keys_staging/**",
    "MODstore_deploy/modstore_server/payment_orders/**",
    "MODstore_deploy/modstore_server/webhook_events/**",
    "MODstore_deploy/modstore_server/workbench_script_runs/**",
    "MODstore_deploy/modstore_server/market_files/.tmp_chunks/**",
    # Build outputs / large binary blobs (kept for archive but not authored by employees).
    "MODstore_deploy/market/dist/**",
    "MODstore_deploy/market/coverage/**",
    "MODstore_deploy/market/.tmp-*/**",
    "MODstore_deploy/market/coverage*/**",
    "MODstore_deploy/market/coverage-*/**",
    "MODstore_deploy/market/cov*.txt",
    "MODstore_deploy/market/coverage_output.txt",
    "MODstore_deploy/market/strict-errors*.txt",
    "MODstore_deploy/market/strict-e*.txt",
    "MODstore_deploy/market/out.txt",
    "MODstore_deploy/market/err.txt",
    "MODstore_deploy/market/test-results.json",
    "MODstore_deploy/market/test-edge.wav",
    "MODstore_deploy/market/tmp_*.log",
    "MODstore_deploy/market/*.log",
    "MODstore_deploy/market/market-dist-upload.tgz",
    "MODstore_deploy/market/playwright-report/**",
    "MODstore_deploy/market/test-results/**",
    "MODstore_deploy/market_vue_baseline/**",
    "MODstore_deploy/market_vue_baseline*.tar.gz",
    "MODstore_deploy/market-dist-*.zip",
    "MODstore_deploy/hero-video.mp4",
    "MODstore_deploy/voice-e2e-result.png",
    "MODstore_deploy/playwright-report/**",
    "MODstore_deploy/tmp_*",
    "MODstore_deploy/*.db*",
    "MODstore_deploy/:memory:",
    "MODstore_deploy/artifacts/*.log",
    "MODstore_deploy/backups/**",
    "MODstore_deploy/_generated_employee/**",
    "MODstore_deploy/data/**",
    "*.mp4",
    "MODstore_deploy.zip",
    "xiu-ci.com_nginx.zip",
    "test_image.jpg",
    "MODstore_deploy/modstore.egg-info/**",
    "**/*.egg-info/**",
    # `coverage/` HTML report at repo root (already owned conceptually but not by glob).
    "coverage/**",
    "playwright-report/**",
    "test-results/**",
    # Vibe-coding runtime user data (test fixtures and per-user code skill stores).
    "var/vibe_coding/**",
    "vibe-coding/test_vibe_*_data/**",
    "vibe-coding/test_vibe_data*/**",
    # Static-site bundled/vendor artifacts.
    "corp-butler/**/chunks/**",
    "corp-butler/**/assets/**",
    "corp-butler/**/vosk.wasm.js",
    "corp-butler/**/vosk.worker.js",
    "corp-butler/**/*.wasm",
    "corp-butler/**/model.tar.gz",
    # Generated marketing media outputs.
    "marketing-assets/xc-brand-film/output/**",
    # Repo root mojibake/corrupt zero-byte file ("���"). retention-officer cleans manually.
    "\u17b9\u17b9\u17b9",
    "*\u17b9*",
]


def _load_yaml(p: Path) -> dict:
    import yaml

    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _collect_globs() -> list[str]:
    globs: list[str] = []
    for f in YUANGON_DIR.glob("**/employee.yaml"):
        d = _load_yaml(f)
        for g in d.get("scope_globs") or []:
            if isinstance(g, str) and g.strip():
                globs.append(g.strip())
    return globs


def _glob_to_regex(glob: str) -> str:
    """Convert a recursive glob (with `**`) to a regex string anchored to full path."""
    import re

    g = glob.replace("\\", "/")
    if g.startswith("./"):
        g = g[2:]
    out: list[str] = []
    i = 0
    while i < len(g):
        c = g[i]
        if g[i : i + 3] == "**/":
            out.append("(?:.*/)?")
            i += 3
        elif g[i : i + 2] == "**":
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c in ".+(){}|^$\\":
            out.append("\\" + c)
            i += 1
        else:
            out.append(c)
            i += 1
    return "^" + "".join(out) + "$"


def _match_any(path: str, globs: list[str]) -> bool:
    import re

    pp = path.replace("\\", "/")
    for g in globs:
        if g.startswith("./"):
            g = g[2:]
        try:
            if re.match(_glob_to_regex(g), pp):
                return True
        except re.error:
            continue
        # Bare-name match (e.g. "models.py" should also match anywhere).
        if "/" not in g and "/" in pp:
            tail = pp.rsplit("/", 1)[1]
            if fnmatch.fnmatchcase(tail, g):
                return True
    return False


def _walk_repo() -> list[str]:
    files: list[str] = []
    for p in REPO_ROOT.rglob("*"):
        if p.is_dir():
            continue
        try:
            rel = p.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            continue
        files.append(rel)
    return files


def _is_yuangon_self_owned(path: str) -> bool:
    """Each employee implicitly owns `yuangon/<area>/<id>/**` (its own folder)."""
    if not path.startswith("yuangon/"):
        return False
    parts = path.split("/")
    # yuangon/<area>/<id>/...  (id != _shared)
    return len(parts) >= 4 and parts[1] != "_shared"


def _has_non_ascii(path: str) -> bool:
    """Heuristic: treat clearly mojibake (non-printable / non-ASCII) zero-byte names as ignored."""
    return any(ord(c) > 0x4DFF for c in path) and len(path) <= 6


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--max-show", type=int, default=200, help="Cap orphan listing size.")
    parser.add_argument("--show-ignored", action="store_true")
    args = parser.parse_args()

    scope_globs = _collect_globs()
    ignore_globs = DEFAULT_IGNORES
    files = _walk_repo()

    orphans: list[str] = []
    for f in files:
        if _match_any(f, ignore_globs):
            continue
        if _is_yuangon_self_owned(f):
            continue
        if _has_non_ascii(f):
            continue
        if _match_any(f, scope_globs):
            continue
        orphans.append(f)

    print(
        f"[coverage] repo_files={len(files)}  scope_globs={len(scope_globs)}  ignored_rules={len(ignore_globs)}"
    )
    if not orphans:
        print("[coverage] OK — every file is owned or explicitly ignored.")
        return 0

    print(f"[coverage] FAIL — {len(orphans)} orphan path(s):")
    for f in orphans[: args.max_show]:
        print(f"  - {f}")
    if len(orphans) > args.max_show:
        print(f"  ... and {len(orphans) - args.max_show} more")
    print()
    print("Fix: either (a) add an owning employee scope_glob, or (b) extend DEFAULT_IGNORES")
    print("     and the §五 explicit-ignore table in yuangon/_shared/OWNERSHIP.md.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
