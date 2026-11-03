"""One-shot closer for incidents already green on main. Removed after it runs."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

def main() -> int:
    repo = os.environ["GH_REPO"]
    payload = json.loads(
        Path(__file__).with_name("resolved-incidents.json").read_text(encoding="utf-8")
    )
    failed = False
    for number, body in payload.items():
        comment = subprocess.run(
            ["gh", "issue", "comment", str(number), "--repo", repo, "--body", body],
            capture_output=True,
            text=True,
        )
        close = subprocess.run(
            ["gh", "issue", "close", str(number), "--repo", repo, "--reason", "completed"],
            capture_output=True,
            text=True,
        )
        print(number, "comment", comment.returncode, (comment.stderr or "").strip()[:240])
        print(number, "close", close.returncode, (close.stderr or "").strip()[:240])
        if comment.returncode != 0 or close.returncode != 0:
            failed = True
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main())
