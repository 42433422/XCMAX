"""Package verified common-host archives for backend-only legacy Mac markers."""
from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sku", required=True)
    parser.add_argument("--arch", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    entries = []
    if args.sku == "enterprise" and args.arch == "arm64":
        name = "XCAGI-Enterprise-1.0.0.4-mac-arm64.zip"
        digest = "5514e649ac4add504144595adfaba7d5cf7417283db821b9c69d2472908f7ba8"
        archive = args.out / name
        if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
            temporary = archive.with_suffix(".download")
            with urllib.request.urlopen(f"https://xiu-ci.com/releases/stable/enterprise/{name}", timeout=60) as response, temporary.open("wb") as output:
                while block := response.read(1024 * 1024):
                    output.write(block)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
                raise RuntimeError("Legacy recovery archive SHA256 mismatch; original download retained")
            temporary.replace(archive)
        entries.append({"filename": name, "sha256": digest, "gitSha": "280225ac77ce0b5f66470d2d7a11ad2844cdad67", "version": "1.0.0.4", "arch": args.arch, "sku": args.sku})
    (args.out / "manifest.json").write_text(json.dumps({"entries": entries}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"legacy_recovery_archives": len(entries), "architecture": args.arch, "sku": args.sku}))


if __name__ == "__main__":
    main()
