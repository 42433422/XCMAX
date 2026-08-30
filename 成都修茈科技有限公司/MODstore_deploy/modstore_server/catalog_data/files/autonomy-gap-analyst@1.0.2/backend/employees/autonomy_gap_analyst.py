"""Self-contained scorecard gap analyst entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict


async def run(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    vendor_dir = Path(__file__).resolve().parents[1] / "vendor"
    if str(vendor_dir) not in sys.path:
        sys.path.insert(0, str(vendor_dir))
    from autonomy_gap_analyst.convert import analyze_scorecard  # type: ignore[import-not-found]

    result = analyze_scorecard(dict(payload or {}))
    return {
        "ok": True,
        "summary": result["summary"],
        "items": result["failed_gates"],
        "warnings": result["warnings"],
        "meta": {"handler": "direct_python", "action": "analyze"},
    }
