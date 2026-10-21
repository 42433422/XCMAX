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
    validate_only = len(sys.argv) == 3 and sys.argv[1] == "--validate-only"
    if len(sys.argv) != (3 if validate_only else 2):
        print("usage: staple-macos-dmg.py [--validate-only] <DMG-or-app>", file=sys.stderr)
        return 64
    dmg = Path(sys.argv[-1]).absolute()
    for action in (("validate",) if validate_only else ("staple", "validate")):
        result = None
        for attempt in range(3):
            command = ["xcrun", "stapler", action, str(dmg)]
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=120)
            except subprocess.TimeoutExpired:
                result = subprocess.CompletedProcess(command, 124, "", f"stapler {action} timed out\n")
            print(result.stdout, end="")
            print(result.stderr, end="", file=sys.stderr)
            if result.returncode == 0:
                break
            output = result.stdout + result.stderr
            if result.returncode != 68 or "NSURLErrorDomain Code=-1005" not in output or attempt == 2:
                break
            print(f"[{action}] transient disconnect; retry {attempt + 2}/3", file=sys.stderr)
            time.sleep(15 * (attempt + 1))
        if result.returncode == 0:
            continue
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
                receipt_path = destination / "recovery-receipt.json"
                if (
                    recovered.is_symlink()
                    or receipt_path.is_symlink()
                    or recovered.exists()
                    or receipt_path.exists()
                ):
                    return result.returncode
                shutil.copyfile(dmg, recovered)
                with recovered.open("rb") as handle:
                    digest = hashlib.file_digest(handle, "sha256").hexdigest()
                receipt = {
                    "status": f"{action}_failed_unverified",
                    "publishable": False,
                    "failed_operation": action,
                    "source_sha": sha,
                    "version": version,
                    "architecture": arch,
                    "filename": dmg.name,
                    "size": recovered.stat().st_size,
                    "sha256": digest,
                    "operation_exit_code": result.returncode,
                }
                if action == "staple":
                    receipt["stapler_exit_code"] = result.returncode
                receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
        return result.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
