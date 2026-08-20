#!/usr/bin/env python3
"""Restore public action board from git snapshot and rebuild real trajectory."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "成都修茈科技有限公司" / "MODstore_deploy"))

from modstore_server.public_action_board import build_trajectory  # noqa: E402


def main() -> None:
    blob = subprocess.check_output(
        ["git", "show", "HEAD:成都修茈科技有限公司/download-action-board.json"],
        cwd=str(ROOT),
    )
    old = json.loads(blob.decode("utf-8"))
    patches = list((old.get("breakpoints") or {}).get("items") or [])
    updates = list((old.get("goals") or {}).get("items") or [])
    for it in patches + updates:
        # Prefer real updated_at clock; otherwise show business day (not invented HH:MM).
        if not it.get("ts"):
            it["ts"] = str(it.get("day") or "—")
    traj = build_trajectory(patches, updates)
    payload = {
        "schema": "xcagi.public_action_board/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "day": old.get("day") or "2026-07-16",
        "readonly": True,
        "note": old.get("note") or "公开只读进度看板；不含源码路径与内部标识。",
        "breakpoints": old.get("breakpoints"),
        "goals": old.get("goals"),
        "trajectory": traj,
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    targets = [
        ROOT / "成都修茈科技有限公司" / "download-action-board.json",
        ROOT
        / "成都修茈科技有限公司"
        / "MODstore_deploy"
        / "market"
        / "public"
        / "download-action-board.json",
        Path("/root/成都修茈科技有限公司/download-action-board.json"),
        Path("/root/XCMAX/成都修茈科技有限公司/download-action-board.json"),
        Path(
            "/root/XCMAX/成都修茈科技有限公司/MODstore_deploy/market/public/download-action-board.json"
        ),
    ]
    written = []
    for tgt in targets:
        try:
            if not tgt.parent.is_dir():
                continue
            tgt.write_text(body, encoding="utf-8")
            written.append(str(tgt))
        except OSError as exc:
            print("skip", tgt, exc)
    print(
        json.dumps(
            {
                "day": payload["day"],
                "traj": len(traj),
                "bp": len(patches),
                "written": written,
                "sample": traj[0] if traj else None,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
