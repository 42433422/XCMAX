"""Prepare a release candidate from Para's completed main integration batch."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

FHD = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FHD))

from scripts.ci.para_pr_integration import (
    REPOSITORY,
    SHANGHAI,
    github,
    integration_queue,
    yesterday_main_pulls,
)
from scripts.dev.verify_version_anchors import canonical_version
from scripts.dev.version_sync import sync

CATALOG = FHD / "config/download_release.json"


def completed_batch(queue: dict[int, str], now: datetime, read=github) -> dict:
    day = now.astimezone(SHANGHAI).date()
    yesterday = yesterday_main_pulls(now, read)
    unfinished = sorted(number for number, pull in yesterday.items() if not pull.get("merged_at"))
    if unfinished:
        return {"reason": "yesterday_prs_unresolved", "prs": unfinished}
    batch = {number: pull["head"]["sha"] for number, pull in sorted(yesterday.items())}
    batch.update(queue)
    if not batch:
        return {"reason": "empty_integration_queue"}
    source = read("git/ref/heads/main")["object"]["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", source):
        raise ValueError("invalid main SHA from GitHub")
    receipts = []
    current_window = False
    for number, expected_head in batch.items():
        pull = read(f"pulls/{number}")
        base = pull.get("base") or {}
        merge = pull.get("merge_commit_sha") or ""
        if (
            pull.get("number") != number
            or pull.get("merged") is not True
            or base.get("ref") != "main"
            or (base.get("repo") or {}).get("full_name", "").casefold() != REPOSITORY.casefold()
            or (pull.get("head") or {}).get("sha") != expected_head
            or not re.fullmatch(r"[0-9a-f]{40}", merge)
            or not pull.get("merged_at")
        ):
            return {"reason": "missing_exact_merge_receipt", "pr": number}
        if read(f"compare/{merge}...{source}").get("status") not in {"ahead", "identical"}:
            return {"reason": "merge_not_on_main", "pr": number}
        merged_at = datetime.fromisoformat(pull["merged_at"].replace("Z", "+00:00"))
        local = merged_at.astimezone(SHANGHAI)
        current_window |= local.date() == day and 2 <= local.hour < 5
        receipts.append((number, expected_head, merge))
    if not current_window:
        return {"reason": "no_new_merge_in_current_window"}
    digest = hashlib.sha256(json.dumps(receipts).encode()).hexdigest()[:16]
    return {"source": source, "branch": f"automation/para-release-{day}-{digest}"}


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare_candidate(source: str, day: str) -> str:
    current = canonical_version()
    if not re.fullmatch(r"\d+(?:\.\d+){3}", current):
        raise ValueError("nightly release requires a four-part product version")
    prefix, patch = current.rsplit(".", 1)
    version = f"{prefix}.{int(patch) + 1}"
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    if any(
        row.get("version") == current
        and row.get("publication_scope") == "para-nightly"
        and row.get("publication_state") == "candidate"
        for row in catalog["release_history"]
    ):
        raise ValueError(f"release candidate {current} is still awaiting completion")
    if any(row.get("version") == version for row in catalog["release_history"]):
        raise ValueError(f"release version {version} is already reserved")

    version_file = FHD / "VERSION.md"
    lines = version_file.read_text(encoding="utf-8").splitlines(keepends=True)
    anchor = next(i for i, line in enumerate(lines) if "**XCAGI 稳定产品版本**" in line)
    lines[anchor] = lines[anchor].replace(f"`{current}`", f"`{version}`", 1)
    version_file.write_text("".join(lines), encoding="utf-8")
    if sync(apply=True):
        raise RuntimeError("version anchors did not synchronize")

    catalog.update(
        marketing_version=version,
        version_lock=version,
        download_version=version,
        release_ready=False,
    )
    artifacts = catalog["artifacts"]["enterprise"]
    for platform in ("win", "mac_arm64", "mac_x64"):
        artifacts[platform] = artifacts[platform].replace(current, version)
    catalog["release_history"].insert(
        0,
        {
            "kind": "release",
            "publication_state": "candidate",
            "publication_scope": "para-nightly",
            "version": version,
            "date": day,
            "title": f"Para 集成候选 {version}",
            "channel": "候选构建",
            "notes": ["待冻结原包、Para 复测和正式渠道读回。"],
            "platforms": ["Windows x64", "macOS arm64/x64", "Android", "iOS"],
            "provenance": {"repository": REPOSITORY, "integrated_main": source},
        },
    )
    write_json(CATALOG, catalog)

    for path in (
        FHD / "config/release_train.json",
        FHD.parent / "成都修茈科技有限公司/FHD/config/release_train.json",
    ):
        train = json.loads(path.read_text(encoding="utf-8"))
        train["current"] = version
        write_json(path, train)

    # Keep GitHub's input allow-lists and historical candidate options.
    desktop = FHD / ".github/workflows/release-desktop.yml"
    mac = FHD / ".github/workflows/release-desktop-mac-ota.yml"
    for path, option, updated in (
        (desktop, f'- "{current}"', f'- "{version}"\n          - "{current}"'),
        (mac, f'options: ["{current}"', f'options: ["{version}", "{current}"'),
    ):
        text = path.read_text(encoding="utf-8")
        default = f'default: "{current}"'
        if default not in text or option not in text:
            raise ValueError(f"missing current version choices in {path.name}")
        path.write_text(
            text.replace(default, f'default: "{version}"', 1).replace(option, updated, 1),
            encoding="utf-8",
        )

    changelog = FHD / "CHANGELOG.md"
    lines = changelog.read_text(encoding="utf-8")
    changelog.write_text(
        lines.replace(
            "## Unreleased\n\n", f"## Unreleased\n\n- Para 集成批次候选版本 {version}。\n\n", 1
        ),
        encoding="utf-8",
    )
    return version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", metavar="INTEGRATED_MAIN_SHA")
    args = parser.parse_args()
    now = datetime.now(SHANGHAI)
    if args.prepare:
        if not re.fullmatch(r"[0-9a-f]{40}", args.prepare):
            raise ValueError("invalid integrated main SHA")
        if subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() != args.prepare:
            raise ValueError("release candidate must use the verified main checkout")
        result = {"version": prepare_candidate(args.prepare, now.date().isoformat())}
    else:
        result = completed_batch(
            integration_queue(os.environ.get("XCMAX_MAIN_MERGE_QUEUE", "")), now
        )
    rendered = json.dumps(result, ensure_ascii=False)
    print(rendered)
    if not args.prepare and (summary := os.environ.get("GITHUB_STEP_SUMMARY")):
        with open(summary, "a", encoding="utf-8") as stream:
            print(f"### Para 凌晨合入核对\n\n`{rendered}`", file=stream)
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as stream:
            for key, value in result.items():
                print(f"{key}={value}", file=stream)


if __name__ == "__main__":
    main()
