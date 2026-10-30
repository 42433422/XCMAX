#!/usr/bin/env python3
"""Fail-closed binder for release_ready vs installer/SHA/five-mode/prod receipt."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REQUIRED_MODES = ("Clean", "Upgrade", "Gui", "Recovery", "Rollback")


def evaluate(
    download_release: dict[str, Any],
    *,
    five_mode_evidence: dict[str, Any] | None,
    prod_receipt: dict[str, Any] | None,
) -> dict[str, Any]:
    blockers: list[str] = []
    release_ready = download_release.get("release_ready") is True
    version = str(
        download_release.get("download_version")
        or download_release.get("version_lock")
        or ""
    )
    if not version:
        blockers.append("missing_download_version")

    artifacts = (
        download_release.get("artifacts")
        if isinstance(download_release.get("artifacts"), dict)
        else {}
    )
    enterprise = artifacts.get("enterprise") if isinstance(artifacts.get("enterprise"), dict) else {}
    installer = str(enterprise.get("win") or "")
    if not installer:
        blockers.append("missing_windows_installer_artifact")

    source_sha = ""
    if five_mode_evidence and isinstance(five_mode_evidence, dict):
        source_sha = str(
            five_mode_evidence.get("source_sha") or five_mode_evidence.get("git_sha") or ""
        )
        modes = five_mode_evidence.get("modes")
        if not isinstance(modes, dict):
            blockers.append("five_mode_evidence_missing_modes")
        else:
            for mode in REQUIRED_MODES:
                row = modes.get(mode)
                if not isinstance(row, dict) or row.get("passed") is not True:
                    blockers.append(f"five_mode_failed_or_missing:{mode}")
    else:
        blockers.append("five_mode_evidence_missing")

    if not source_sha or len(source_sha) != 40:
        blockers.append("missing_or_invalid_version_sha")

    if not prod_receipt or not isinstance(prod_receipt, dict):
        blockers.append("prod_release_receipt_missing")
    else:
        if prod_receipt.get("ok") is not True:
            blockers.append("prod_release_receipt_not_ok")
        receipt_sha = str(prod_receipt.get("git_sha") or prod_receipt.get("source_sha") or "")
        if source_sha and receipt_sha and receipt_sha != source_sha:
            blockers.append("prod_receipt_sha_mismatch")
        receipt_version = str(prod_receipt.get("version") or "")
        if version and receipt_version and receipt_version != version:
            blockers.append("prod_receipt_version_mismatch")

    if blockers and release_ready:
        blockers.append("release_ready_true_without_complete_chain")

    return {
        "schema": "xcagi.release_ready_chain/v1",
        "release_ready_claimed": release_ready,
        "release_ready_allowed": bool(release_ready and not blockers),
        "version": version,
        "installer": installer,
        "source_sha": source_sha,
        "required_modes": list(REQUIRED_MODES),
        "blockers": blockers,
        "passed": not (release_ready and blockers),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-release", type=Path, required=True)
    parser.add_argument("--five-mode-evidence", type=Path)
    parser.add_argument("--prod-receipt", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    download_release = json.loads(args.download_release.read_text(encoding="utf-8"))
    five = (
        json.loads(args.five_mode_evidence.read_text(encoding="utf-8"))
        if args.five_mode_evidence and args.five_mode_evidence.is_file()
        else None
    )
    receipt = (
        json.loads(args.prod_receipt.read_text(encoding="utf-8"))
        if args.prod_receipt and args.prod_receipt.is_file()
        else None
    )
    result = evaluate(download_release, five_mode_evidence=five, prod_receipt=receipt)
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if result["release_ready_claimed"] and result["blockers"]:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
