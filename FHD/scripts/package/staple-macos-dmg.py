#!/usr/bin/env python3
"""Retry Apple's observed transient ticket disconnect; retain only a failed DMG."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    dmg = Path(sys.argv[1]).absolute()
    result = None
    for attempt in range(3):
        command = ["xcrun", "stapler", "staple", str(dmg)]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            result = subprocess.CompletedProcess(command, 124, "", "stapler timed out\n")
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
        if result.returncode == 0:
            return 0
        output = result.stdout + result.stderr
        if result.returncode != 68 or "NSURLErrorDomain Code=-1005" not in output or attempt == 2:
            break
        print(f"[staple] transient disconnect; retry {attempt + 2}/3", file=sys.stderr)
        time.sleep(15 * (attempt + 1))
    match = re.fullmatch(r"XCAGI-Enterprise-(\d+(?:\.\d+){3})-mac-(arm64|x64)\.dmg", dmg.name)
    sha = os.environ.get("XCAGI_BUILD_SHA", "")
    if match and re.fullmatch(r"[0-9a-f]{40}", sha) and dmg.is_file() and not dmg.is_symlink():
        version, arch = match.groups()
        allowed = [
            ROOT.resolve() / "release" / f"xcagi-v{version}" / "enterprise",
            Path(tempfile.gettempdir()).resolve() / f"xcagi-electron-builder-{version}-enterprise",
        ]
        if not dmg.parent.is_symlink() and dmg.parent.resolve() in allowed:
            destination = ROOT / "release-staple-recovery" / f"{sha}-{arch}"
            if destination.is_symlink() or destination.parent.is_symlink():
                return result.returncode
            destination.mkdir(parents=True, exist_ok=True)
            recovered = destination / dmg.name
            if recovered.is_symlink() or (destination / "recovery-receipt.json").is_symlink():
                return result.returncode
            shutil.copyfile(dmg, recovered)
            with recovered.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
            receipt = {
                "status": "staple_failed_unverified",
                "publishable": False,
                "source_sha": sha,
                "version": version,
                "architecture": arch,
                "filename": dmg.name,
                "size": recovered.stat().st_size,
                "sha256": digest,
                "stapler_exit_code": result.returncode,
            }
            (destination / "recovery-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
