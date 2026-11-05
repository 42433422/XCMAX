#!/usr/bin/env python3
"""Require a review request for net growth above the advisory source-size cap.

Compare immutable Git trees, not the size baseline or a dirty checkout. A valid
request is evidence for reviewers, never evidence of reviewer approval.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

try:
    from .source_governance import _stack_rule
except ImportError:  # Direct CLI execution from any working directory.
    from source_governance import _stack_rule

ROOT = Path(__file__).resolve().parents[2]
REVIEW_PATH = "config/source_growth_reviews.json"
DETAIL_FIELDS = ("reason", "boundary", "validation", "follow_up")
IDENTITY_FIELDS = ("base_file", "base_blob", "head_blob", "before_lines", "after_lines")
PLACEHOLDERS = {"todo", "tbd", "n/a", "none", "待补充", "待定", "无", "..."}


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True
    ).stdout


def commit(root: Path, ref: str) -> str:
    return (
        git(root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
        .decode()
        .strip()
    )


def blob(root: Path, ref: str, path: str) -> tuple[str, int]:
    oid = git(root, "rev-parse", "--verify", f"{ref}:{path}").decode().strip()
    text = git(root, "cat-file", "blob", oid).decode("utf-8", errors="replace")
    return oid, len(text.splitlines())


def growth(root: Path, base: str, head: str) -> tuple[str, str, dict]:
    base, head = commit(root, base), commit(root, head)
    # The merge base excludes unrelated changes which landed on the target
    # branch after this branch forked. A missing history/object must fail closed.
    base = git(root, "merge-base", base, head).decode().strip()
    fields = (
        git(root, "diff", "--name-status", "-z", "--find-renames", base, head)
        .decode()
        .split("\0")
    )
    result: dict = {}
    index = 0
    while index < len(fields) and fields[index]:
        status, old_path = fields[index : index + 2]
        index += 2
        path = old_path
        if status.startswith("R"):
            path = fields[index]
            index += 1
        if status == "D" or _stack_rule(path) is None:
            continue
        _, cap = _stack_rule(path)
        head_blob, after = blob(root, head, path)
        base_blob, before = (None, 0)
        if status != "A" and _stack_rule(old_path) is not None:
            base_blob, before = blob(root, base, old_path)
        if after > cap and after > before:
            result[path] = {
                "base_file": old_path if base_blob else None,
                "base_blob": base_blob,
                "head_blob": head_blob,
                "before_lines": before,
                "after_lines": after,
            }
    return base, head, result


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    value: dict = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def load_reviews(root: Path, head: str) -> dict:
    raw = git(root, "show", f"{head}:{REVIEW_PATH}")
    payload = json.loads(raw, object_pairs_hook=unique_object)
    if (
        not isinstance(payload, dict)
        or type(payload.get("schema_version")) is not int
        or payload.get("schema_version") != 1
        or not isinstance(payload.get("reviews"), dict)
    ):
        raise ValueError(f"invalid {REVIEW_PATH} schema")
    return payload["reviews"]


def evaluate(changes: dict, reviews: dict) -> list[str]:
    errors = []
    for path, measured in changes.items():
        entry = reviews.get(path)
        if not isinstance(entry, dict):
            errors.append(f"{path}: missing source-growth review request")
            continue
        for key in IDENTITY_FIELDS:
            expected = measured[key]
            if (
                key not in entry
                or entry[key] != expected
                or type(entry[key]) is not type(expected)
            ):
                errors.append(
                    f"{path}: {key} must match this exact change ({expected})"
                )
        for key in DETAIL_FIELDS:
            value = entry.get(key)
            if (
                not isinstance(value, str)
                or len(value.strip()) < 12
                or value.strip().lower() in PLACEHOLDERS
            ):
                errors.append(
                    f"{path}: {key} needs a concrete explanation (at least 12 characters)"
                )
        owner = entry.get("review_owner", "")
        if not isinstance(owner, str) or not re.fullmatch(
            r"@[A-Za-z0-9][A-Za-z0-9-]*(?:/[A-Za-z0-9_-]+)?", owner
        ):
            errors.append(
                f"{path}: review_owner must name a GitHub user or team; this is not approval"
            )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument(
        "--print-template",
        action="store_true",
        help="Print measured records to complete, not approvals",
    )
    args = parser.parse_args(argv)
    try:
        base, head, changes = growth(args.repo_root, args.base, args.head)
        if args.print_template:
            entries = {
                path: {
                    **values,
                    **dict.fromkeys(DETAIL_FIELDS, ""),
                    "review_owner": "",
                }
                for path, values in changes.items()
            }
            print(
                json.dumps(
                    {"schema_version": 1, "reviews": entries},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        errors = evaluate(
            changes, load_reviews(args.repo_root, head) if changes else {}
        )
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"[source-growth-review] Cannot verify comparison: {exc}")
        return 2
    print(
        json.dumps(
            {"base": base, "head": head, "growth": changes, "errors": errors},
            ensure_ascii=False,
            indent=2,
        )
    )
    if changes:
        print(
            "[source-growth-review] Requests require human architecture review; this check does not approve them."
        )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
