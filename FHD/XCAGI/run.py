#!/usr/bin/env python3
"""Compat entry — prefer FHD/run.py (SSOT). Delegates to run_fastapi.main()."""

from __future__ import annotations

from run_fastapi import main

if __name__ == "__main__":
    main()
