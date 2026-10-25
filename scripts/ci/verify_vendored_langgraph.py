#!/usr/bin/env python3
"""Warn if vendored LangGraph packages lack basic provenance markers."""
from __future__ import annotations
import sys
from pathlib import Path

MARKERS = ("VERSION", "PYPI", "upstream", "langgraph", "checksum", "sha256")

def main() -> int:
    repo = Path(__file__).resolve().parents[2]
    hits = list(repo.rglob("*langgraph*"))
    pkgs = [p for p in hits if p.is_dir() and (p / "pyproject.toml").exists() or (p.is_dir() and (p / "SETUP.cfg").exists())]
    # fallback: any dir named langgraph*
    dirs = [p for p in repo.rglob("langgraph*") if p.is_dir()][:20]
    warns = 0
    if not dirs:
        print("INFO no langgraph* dirs found")
        return 0
    for d in dirs[:12]:
        text = " ".join(x.name for x in d.rglob("*") if x.is_file())[:2000].lower()
        if not any(m.lower() in text for m in MARKERS):
            print(f"WARN {d}: no obvious provenance markers")
            warns += 1
        else:
            print(f"INFO {d}: provenance markers present")
    print(f"summary warns={warns}")
    return 0  # warn-only hook

if __name__ == "__main__":
    raise SystemExit(main())
