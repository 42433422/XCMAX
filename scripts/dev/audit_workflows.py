#!/usr/bin/env python3
"""Audit GitHub Actions workflows in the root repo (SSOT).

For every workflow under .github/workflows/*.yml this script prints:
  1. Trigger conditions (the `on:` block: push/pull_request/schedule/... + key filters)
  2. Script-reference existence table (every `scripts/...` ref, resolved against
     all known base dirs, with local/remote classification)

Classification of a script reference:
  - OK      : resolves to an existing file under one of the known base dirs
  - MISSING : no base dir contains the file (candidate dead link)
  - REMOTE  : prefixed by a shell var or an absolute remote path (/opt, /root,
              /var/www...), or read from git via `git show` — not expected locally

Usage:
  python scripts/dev/audit_workflows.py            # audit all workflows
  python scripts/dev/audit_workflows.py fhd-ci-cd  # filter by filename substring
"""

from __future__ import annotations

import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKFLOWS_DIR = os.path.join(REPO_ROOT, ".github", "workflows")

# Base dirs, in priority order, used to resolve relative `scripts/...` paths.
BASE_DIRS = [
    ("(root)", REPO_ROOT),
    ("FHD", os.path.join(REPO_ROOT, "FHD")),
    ("FHD/desktop", os.path.join(REPO_ROOT, "FHD", "desktop")),
    ("FHD/frontend", os.path.join(REPO_ROOT, "FHD", "frontend")),
    ("FHD/mobile-flutter-poc", os.path.join(REPO_ROOT, "FHD", "mobile-flutter-poc")),
    ("成都修茈", os.path.join(REPO_ROOT, "成都修茈科技有限公司")),
    (
        "成都修茈/MODstore_deploy",
        os.path.join(REPO_ROOT, "成都修茈科技有限公司", "MODstore_deploy"),
    ),
]

# A token whose `scripts/` part is preceded by a var or remote-root is not a local link.
REMOTE_PREFIX = re.compile(r"[\w.\-]*\$|/opt/|/root/|/var/www|/home/|^/")

SCRIPT_EXT = re.compile(r"\.(?:py|sh|mjs|ps1)$")


def extract_script_refs(path: str) -> list[tuple[str, str, str]]:
    """Return [(ref, status, resolved_base)] for each unique script reference."""
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()

    tokens = re.split(r"[\s\"'`;()\[\]{}<>|&]+", text)
    seen: set[str] = set()
    results: list[tuple[str, str, str]] = []

    for tok in tokens:
        if "/scripts/" not in tok or not SCRIPT_EXT.search(tok):
            continue
        ref = tok.strip("'\"`").rstrip("\\")
        # fall back to the part from the last directory boundary that looks repo-relative
        if ref in seen:
            continue
        seen.add(ref)

        head, _, _ = ref.partition("/scripts/")
        rel = "scripts/" + ref.partition("/scripts/")[2]

        # 1) remote / var-prefixed -> not a local dead link
        if REMOTE_PREFIX.search(head) or ref.startswith("${") or "git show" in ref:
            results.append((ref, "REMOTE", ""))
            continue

        # 2) reference already includes a repo-relative leading dir (e.g. 成都修茈/...)
        if ref.startswith("FHD/") or ref.startswith("成都修茈"):
            base_label, base = BASE_DIRS[0]
            full = os.path.join(base, ref)
            results.append(
                (
                    ref,
                    "OK" if os.path.exists(full) else "MISSING",
                    base_label if os.path.exists(full) else "",
                )
            )
            continue

        # 3) plain `scripts/...` -> try every base dir
        resolved = ""
        status = "MISSING"
        for label, base in BASE_DIRS:
            if os.path.exists(os.path.join(base, rel)):
                resolved, status = label, "OK"
                break
        results.append((ref, status, resolved))

    return results


def parse_triggers(path: str) -> list[tuple[str, str]]:
    """Parse the `on:` block. Returns [(trigger_name, detail)]."""
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()

    on_idx = next(
        (i for i, ln in enumerate(lines) if re.match(r"^\s*on\s*:\s*($|\[|\S)", ln)),
        None,
    )
    if on_idx is None:
        return [("(none)", "")]

    line = lines[on_idx].strip()

    # on: push
    m = re.match(r"^on\s*:\s*(\S.*)$", line)
    if m and not m.group(1).startswith("["):
        return [(m.group(1).strip(), "")]

    # on: [push, pull_request, ...]
    m = re.match(r"^on\s*:\s*\[(.*)\]\s*$", line)
    if m:
        return [(x.strip(), "") for x in m.group(1).split(",") if x.strip()]

    # nested `on:` block
    base_indent: int | None = None
    result: list[tuple[str, str]] = []
    i = on_idx + 1
    while i < len(lines):
        ln = lines[i]
        if not ln.strip() or ln.strip().startswith("#"):
            i += 1
            continue
        indent = len(ln) - len(ln.lstrip())
        if base_indent is None:
            base_indent = indent
        if indent < base_indent:
            break  # left the on: block
        if indent != base_indent:
            i += 1
            continue
        key = ln.strip().rstrip(":").strip()
        # collect child lines (filters / cron / types)
        child = []
        j = i + 1
        while (
            j < len(lines)
            and lines[j].strip()
            and (
                lines[j].strip().startswith("-")
                or (len(lines[j]) - len(lines[j].lstrip())) > base_indent
            )
        ):
            child.append(lines[j].strip())
            j += 1
        detail = ""
        if key == "schedule":
            # only schedule triggers carry cron entries
            crons = [
                c.split("cron")[-1].strip(" :'\"")
                for c in child
                if c.startswith("cron")
            ]
            detail = "; ".join(crons)
        else:
            # summarize key filters concisely (avoid dumping huge path lists)
            filters = [
                c
                for c in child
                if c.split(":")[0]
                in ("branches", "tags", "types", "workflows", "paths", "labels")
            ]
            detail = "; ".join(filters[:4])
        result.append((key, detail))
        i = j
    return result


def audit(path: str) -> None:
    base = os.path.basename(path)
    print("=" * 78)
    print(f"WORKFLOW: {base}")
    print("-" * 78)

    triggers = parse_triggers(path)
    print("  触发条件 (on:):")
    if not triggers:
        print("    (无 / 未识别)")
    for name, detail in triggers:
        print(f"    - {name:<22}{detail}")

    refs = extract_script_refs(path)
    print("  脚本引用存在性:")
    if not refs:
        print("    (无 scripts/* 引用)")
    else:
        print(f"    {'状态':<8}{'基准目录':<20}引用")
        for ref, status, where in refs:
            print(f"    {status:<8}{where:<20}{ref}")
    print()


def main() -> None:
    if not os.path.isdir(WORKFLOWS_DIR):
        print(f"未找到 workflow 目录: {WORKFLOWS_DIR}")
        sys.exit(1)
    files = sorted(f for f in os.listdir(WORKFLOWS_DIR) if f.endswith(".yml"))
    if not files:
        print("workflow 目录为空")
        sys.exit(1)

    filt = sys.argv[1] if len(sys.argv) > 1 else ""
    targets = [f for f in files if filt in f] if filt else files
    if not targets:
        print(f"没有文件名包含 '{filt}' 的 workflow")
        sys.exit(1)

    print(f"共 {len(targets)}/{len(files)} 个 workflow（过滤: '{filt or 'all'}')")
    missing_global = []
    for f in targets:
        audit(os.path.join(WORKFLOWS_DIR, f))
        for ref, status, _ in extract_script_refs(os.path.join(WORKFLOWS_DIR, f)):
            if status == "MISSING":
                missing_global.append((f, ref))

    print("=" * 78)
    print("MISSING 汇总（候选死链，需人工复核）")
    if missing_global:
        for f, ref in missing_global:
            print(f"  {f:<42}{ref}")
    else:
        print("  无 MISSING 引用")


if __name__ == "__main__":
    main()
