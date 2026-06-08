#!/usr/bin/env python3
"""生产 MODstore P-W 全量 surface-audit 重拍。"""
from __future__ import annotations

import asyncio
import os
import sys


async def main() -> int:
    os.environ.setdefault("MODSTORE_INTERNAL_API_BASE", "http://127.0.0.1:9990")
    os.environ.setdefault("MODSTORE_SURFACE_AUDIT_API_URL", "http://127.0.0.1:9990")
    from modstore_server.daily_digest_surface_audit import run_surface_audit_async

    report = await run_surface_audit_async()
    results = report.get("results") if isinstance(report.get("results"), list) else []
    pw = [r for r in results if r.get("lane") == "P-W"]
    admin = [r for r in pw if "/market/admin/" in str(r.get("url") or "")]
    print(f"ok={report.get('ok')} day={report.get('day')} pw={len(pw)} admin={len(admin)}")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
