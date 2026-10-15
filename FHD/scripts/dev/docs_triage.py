#!/usr/bin/env python3
"""文档分流：把「零入链、非 SSOT、非运行时资产」的 md 标记为归档候选。

背景：仓库 md 文档已膨胀到近千篇 / 十余万行，成为负债（AI 读错、路径漂移）。
本脚本用**确定性规则**给出可复核的归档清单，把「活文档」收敛为 SSOT_INDEX
登记项 + 入口文档 + 被代码/manifest 引用的运行时资产。

活文档 = 从「根」出发沿 md 引用图 **可达** 的文档（死树自引用不算活）：
  根（任一命中即为根）：
    1. SSOT 登记：出现在 ``FHD/config/ssot.yaml`` 或 ``FHD/docs/SSOT_INDEX.md``
    2. 入口文档：basename 命中 ENTRY_BASENAMES
    3. 运行时资产：位于 PROTECTED_PREFIXES，或路径含 prompts/skills 段
    4. 代码引用：basename 出现在任意被跟踪的非 md 文件中
    5. manifest 白名单：被员工包 ``workspace_policy.scope_globs`` 匹配
  可达：根文档链式引用到的 md 也算活（reason=inlink）。

归档候选 = 上述可达集之外的 md，按原因标注：
  deprecated（含废弃标记） / historical-snapshot（历史快照） / unreferenced（不可达）。
这取代了早期「任一 md 入链即活」的规则——后者会被死树内部互链自保，收敛不动。

用法::

    python scripts/dev/docs_triage.py report            # 生成报告 + JSON 清单
    python scripts/dev/docs_triage.py report --json     # 机器可读输出到 stdout
    python scripts/dev/docs_triage.py apply \
        --archive-root ~/XCMAX-archives/docs-20260910   # 复制校验后 git rm

退出码: 0=成功 1=用法/环境错误。
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = FHD_ROOT.parent

SSOT_YAML = FHD_ROOT / "config" / "ssot.yaml"
SSOT_INDEX = FHD_ROOT / "docs" / "SSOT_INDEX.md"
EMPLOYEES_DIR = FHD_ROOT / "mods" / "_employees"
TRIAGE_JSON = FHD_ROOT / "metrics" / "docs-triage.json"

EXIT_OK, EXIT_USAGE = 0, 1

ENTRY_BASENAMES = {
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "ARCHIVE_POINTER.md",
    "SSOT_INDEX.md",
    "PROJECT_STATE.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "LICENSE.md",
    "DEV_TOOLS_INVENTORY.md",
    "INDEX.md",
    "ARCHITECTURE.md",
    "COMMERCIAL_LICENSE.md",
}

# 运行时资产前缀（AI 员工运行时、mod 包、生成镜像）。
PROTECTED_PREFIXES = (
    "FHD/mods/",
    "成都修茈科技有限公司/yuangon/",
    "FHD/AMIN/",
    "FHD/.github/",
    ".github/",
    "FHD/prompts/",
    "FHD/resources/",
)

# 路径段命中即视为运行时资产（prompts/system.md、skills/*.md、runbook.md）。
PROTECTED_SEGMENTS = {"prompts", "skills"}
PROTECTED_BASENAMES = {"runbook.md", "SKILL.md"}

# 历史快照目录：其中的文档多为日期化产物（报告/证据/复盘/周报/计划），
# 它们彼此互链属于「死树自引用」，不构成活文档依据。SSOT/入口/代码引用仍保护。
HISTORICAL_SEGMENTS = {
    "reports",
    "evidence",
    "postmortems",
    "weekly",
    "superpowers",
    "plans",
    "_completed",
    "archive",
}

# 扫描代码引用时跳过的重内容/二进制后缀。
SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp", ".pdf",
    ".zip", ".gz", ".tar", ".whl", ".woff", ".woff2", ".ttf", ".eot",
    ".lock", ".map", ".db", ".sqlite", ".bin", ".exe", ".dll", ".so", ".dylib",
    ".docx", ".xlsx", ".pptx",
}
MAX_SCAN_BYTES = 400_000

MD_REF_RE = re.compile(r"[A-Za-z0-9_\-./\u4e00-\u9fff]+\.md")


def _git(*args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def _tracked_files() -> list[str]:
    out = _git("ls-files", "-z", "--cached")
    return [p for p in out.split("\0") if p]


def _is_text_like(path: str) -> bool:
    return Path(path).suffix.lower() not in SKIP_SUFFIXES


def _read_text(abs_path: Path) -> str:
    try:
        if abs_path.stat().st_size > MAX_SCAN_BYTES:
            return ""
        return abs_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _load_ssot_registered() -> tuple[set[str], set[str]]:
    """返回 (protected_paths, protected_prefixes)；仅按路径匹配，不用 basename
    （basename 歧义大：SSOT_INDEX 里的 README.md 会误保护全仓 README）。"""
    paths: set[str] = set()
    prefixes: set[str] = set()

    if SSOT_YAML.is_file():
        import yaml

        data = yaml.safe_load(SSOT_YAML.read_text(encoding="utf-8")) or {}
        for dom in data.get("domains") or []:
            if not dom.get("enabled", True):
                continue
            for key in ("ssot", "derived"):
                raw = dom.get(key)
                entries = raw if isinstance(raw, list) else [raw]
                for entry in entries:
                    if not entry:
                        continue
                    rel = str(entry).split("#", 1)[0].strip()
                    if not rel:
                        continue
                    if rel.endswith("/"):
                        prefixes.add(rel)
                    elif rel.endswith(".md"):
                        paths.add(rel)
                    else:
                        prefixes.add(rel.rstrip("/") + "/")

    if SSOT_INDEX.is_file():
        text = SSOT_INDEX.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)]+\.md)\)", text):
            target = target.split("#", 1)[0].strip()
            if "://" in target or not target.endswith(".md"):
                continue
            resolved = os.path.normpath(os.path.join("FHD/docs", target))
            paths.add(resolved.replace(os.sep, "/"))
        for target in re.findall(r"`([^`]*?\.md)`", text):
            target = target.split("#", 1)[0].strip()
            if target.endswith(".md") and "/" in target:
                paths.add(os.path.normpath(target).replace(os.sep, "/"))

    return paths, prefixes


def _load_scope_globs() -> list[str]:
    globs: list[str] = []
    if not EMPLOYEES_DIR.is_dir():
        return globs
    for mf in sorted(EMPLOYEES_DIR.glob("*/manifest.json")):
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for holder in (data, data.get("employee_config_v2") or {}):
            wp = holder.get("workspace_policy") if isinstance(holder, dict) else None
            if isinstance(wp, dict):
                for g in wp.get("scope_globs") or []:
                    text = str(g).strip()
                    # 只认「路径限定」的文档 glob（如 docs/runbooks/dbops-*.md）；
                    # 裸 *.md / README.md 是宽泛写权限声明，不作为保留依据。
                    if ".md" in text and "/" in text:
                        globs.append(text)
    return globs


def _glob_match(path: str, pattern: str) -> bool:
    pattern = pattern.strip()
    if not pattern:
        return False
    if pattern.endswith("/**"):
        return path.startswith(pattern[:-3].rstrip("/") + "/")
    if "/" not in pattern:
        return fnmatch.fnmatch(Path(path).name, pattern)
    return fnmatch.fnmatch(path, pattern)


def _collect_refs(tracked: list[str]) -> tuple[set[str], dict[str, set[str]]]:
    """返回 (code_refs, md_edges)。

    * ``code_refs``：非 md 文件（代码/配置/脚本）中出现的 .md 路径或 basename
      —— 命中即说明该文档被代码/工具消费。
    * ``md_edges``：md 文档之间的 **有向引用图**（解析后的仓库相对路径）。
      用于从根出发做可达性判定，死树内部互链不产生活文档。
    """
    md_set = {p for p in tracked if p.lower().endswith(".md")}
    # 路径后缀索引：把 'docs/a/b.md' 与引用里的 'a/b.md' / 'b.md' 对上。
    suffix_index: dict[str, set[str]] = {}
    for p in md_set:
        parts = p.split("/")
        for i in range(len(parts)):
            suffix_index.setdefault("/".join(parts[i:]), set()).add(p)

    code_refs: set[str] = set()
    md_edges: dict[str, set[str]] = {p: set() for p in md_set}
    for rel in tracked:
        if not _is_text_like(rel):
            continue
        text = _read_text(REPO_ROOT / rel)
        if not text:
            continue
        if rel in md_set:
            base_dir = os.path.dirname(rel)
            outs = md_edges[rel]
            for token in MD_REF_RE.findall(text):
                token = token.strip().strip("()<>").lstrip("./")
                if not token:
                    continue
                resolved = os.path.normpath(os.path.join(base_dir, token)).replace(os.sep, "/")
                if resolved.startswith("../"):
                    resolved = resolved[3:]
                if resolved in md_set:
                    outs.add(resolved)
                elif "/" in resolved:
                    outs |= suffix_index.get(resolved, set())
                if "/" in token:
                    outs |= suffix_index.get(token, set())
            outs.discard(rel)
        else:
            for token in MD_REF_RE.findall(text):
                token = token.strip("./")
                if not token:
                    continue
                code_refs.add(token)
                code_refs.add(Path(token).name)
    return code_refs, md_edges


def _count_lines(abs_path: Path) -> int:
    try:
        text = abs_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


DEPRECATED_RE = re.compile(r"(DEPRECATED|已废弃|已归档|已过期|OBSOLETE|SUPERSEDED)", re.IGNORECASE)


def _root_reason(
    rel: str,
    ssot_paths: set[str],
    ssot_prefixes: set[str],
    scope_globs: list[str],
    code_refs: set[str],
) -> str | None:
    """文档若是「活文档之根」返回原因，否则 None（须由可达性抢救）。"""
    basename = Path(rel).name
    if rel in ssot_paths:
        return "ssot"
    if any(rel == pref.rstrip("/") or rel.startswith(pref) for pref in ssot_prefixes):
        return "ssot-dir"
    if basename in ENTRY_BASENAMES:
        return "entry"
    if rel.startswith(PROTECTED_PREFIXES) or basename in PROTECTED_BASENAMES:
        return "runtime"
    if any(seg in PROTECTED_SEGMENTS for seg in rel.split("/")[:-1]):
        return "runtime"
    if any(_glob_match(rel, g) for g in scope_globs):
        return "manifest-scope"
    if basename in code_refs:
        return "code-ref"
    return None


def classify() -> tuple[list[dict], list[dict]]:
    """返回 (living, archive) 两个清单，元素含 path/lines/reason。

    活文档 = 根 ∪ 从根沿引用图可达者；其余为归档候选。
    """
    tracked = _tracked_files()
    ssot_paths, ssot_prefixes = _load_ssot_registered()
    scope_globs = _load_scope_globs()
    code_refs, md_edges = _collect_refs(tracked)

    md_files = [p for p in tracked if p.lower().endswith(".md")]

    reason: dict[str, str] = {}
    for rel in md_files:
        r = _root_reason(rel, ssot_paths, ssot_prefixes, scope_globs, code_refs)
        if r:
            reason[rel] = r
    stack = list(reason)
    while stack:
        cur = stack.pop()
        for nxt in md_edges.get(cur, ()):
            if nxt not in reason:
                reason[nxt] = "inlink"
                stack.append(nxt)

    living: list[dict] = []
    archive: list[dict] = []
    for rel in md_files:
        lines = _count_lines(REPO_ROOT / rel)
        entry = {"path": rel, "lines": lines}
        if rel in reason:
            entry["reason"] = reason[rel]
            living.append(entry)
            continue
        in_historical = bool(set(rel.split("/")) & HISTORICAL_SEGMENTS)
        text = _read_text(REPO_ROOT / rel)
        entry["deprecated"] = bool(DEPRECATED_RE.search(text))
        if entry["deprecated"]:
            entry["archive_reason"] = "deprecated"
        elif in_historical:
            entry["archive_reason"] = "historical-snapshot"
        else:
            entry["archive_reason"] = "unreferenced"
        archive.append(entry)

    living.sort(key=lambda e: e["path"])
    archive.sort(key=lambda e: e["path"])
    # 在途文档：工作区有未提交改动 → 虽不可达也不可归档（归档会丢工作）。
    # 与 cmd_apply 的过滤口径保持一致，避免报告把在途文档误列为可归档。
    dirty = _dirty_paths()
    for entry in archive:
        if entry["path"] in dirty:
            entry["in_flight"] = True
    return living, archive


def _print_summary(living: list[dict], archive: list[dict]) -> None:
    total = len(living) + len(archive)
    live_lines = sum(e["lines"] for e in living)
    arch_lines = sum(e["lines"] for e in archive)
    print(f"[docs-triage] 跟踪 md 总数：{total} 篇 / {live_lines + arch_lines} 行")
    actionable = [e for e in archive if not e.get("in_flight")]
    in_flight = [e for e in archive if e.get("in_flight")]
    print(f"[docs-triage] 活文档：{len(living)} 篇 / {live_lines} 行")
    print(
        f"[docs-triage] 归档候选：{len(archive)} 篇 / {arch_lines} 行"
        f"（可归档 {len(actionable)} 篇 / 在途 {len(in_flight)} 篇）"
    )
    for e in in_flight:
        print(f"    [在途] {e['path']}（{e['lines']} 行，{e['archive_reason']}）")

    by_reason: dict[str, list[int]] = {}
    for e in living:
        slot = by_reason.setdefault(e["reason"], [0, 0])
        slot[0] += 1
        slot[1] += e["lines"]
    print("[docs-triage] 活文档保留原因：")
    for reason, (count, lines) in sorted(by_reason.items(), key=lambda kv: -kv[1][1]):
        print(f"    {reason:<16} {count:>4} 篇 / {lines:>7} 行")

    print("[docs-triage] 归档候选拆解（仅可归档）：")
    by_arch: dict[str, list[int]] = {}
    for e in actionable:
        slot = by_arch.setdefault(e.get("archive_reason", "?"), [0, 0])
        slot[0] += 1
        slot[1] += e["lines"]
    for reason, (count, lines) in sorted(by_arch.items(), key=lambda kv: -kv[1][1]):
        print(f"    {reason:<20} {count:>4} 篇 / {lines:>7} 行")

    top: dict[str, list[int]] = {}
    for e in actionable:
        topdir = e["path"].split("/")[0] if "/" in e["path"] else "."
        slot = top.setdefault(topdir, [0, 0])
        slot[0] += 1
        slot[1] += e["lines"]
    print("[docs-triage] 归档候选 Top 目录：")
    for topdir, (count, lines) in sorted(top.items(), key=lambda kv: -kv[1][1])[:12]:
        print(f"    {topdir:<40} {count:>4} 篇 / {lines:>7} 行")


def cmd_report(as_json: bool) -> int:
    living, archive = classify()
    if as_json:
        print(json.dumps({"living": living, "archive": archive}, ensure_ascii=False, indent=2))
        return EXIT_OK

    TRIAGE_JSON.parent.mkdir(parents=True, exist_ok=True)
    TRIAGE_JSON.write_text(
        json.dumps(
            {
                "living_count": len(living),
                "archive_count": len(archive),
                "actionable_count": len([e for e in archive if not e.get("in_flight")]),
                "in_flight_count": len([e for e in archive if e.get("in_flight")]),
                "living_lines": sum(e["lines"] for e in living),
                "archive_lines": sum(e["lines"] for e in archive),
                "archive": archive,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _print_summary(living, archive)
    print(f"[docs-triage] 清单已写入 {TRIAGE_JSON.relative_to(REPO_ROOT)}")
    return EXIT_OK


def _sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _dirty_paths() -> set[str]:
    """已跟踪但工作区/暂存区有未提交改动的路径 —— 归档必须跳过，避免丢工作。"""
    out = _git("status", "--porcelain", "-z")
    dirty: set[str] = set()
    for chunk in out.split("\0"):
        if len(chunk) < 4:
            continue
        rel = chunk[3:]
        if " -> " in rel:  # 重命名：XY<space>old -> new
            rel = rel.split(" -> ", 1)[1]
        dirty.add(rel)
    return dirty


def cmd_apply(archive_root: Path, dry_run: bool) -> int:
    _, archive = classify()
    if not archive:
        print("[docs-triage] 无归档候选，退出。")
        return EXIT_OK

    archive_root = archive_root.expanduser().resolve()
    if archive_root == REPO_ROOT or str(REPO_ROOT).startswith(str(archive_root) + "/"):
        print(f"[docs-triage] 归档目录不能包含工作区：{archive_root}", file=sys.stderr)
        return EXIT_USAGE

    dirty = _dirty_paths()
    skipped = [e["path"] for e in archive if e["path"] in dirty]
    if skipped:
        print(f"[docs-triage] 跳过 {len(skipped)} 个有未提交改动的候选（须先提交/还原）：")
        for p in skipped:
            print(f"    {p}")
    archive = [e for e in archive if e["path"] not in dirty]
    if not archive:
        print("[docs-triage] 过滤后无候选，退出。")
        return EXIT_OK

    manifest_lines: list[str] = []
    missing: list[str] = []
    for entry in archive:
        src = REPO_ROOT / entry["path"]
        if not src.is_file():
            missing.append(entry["path"])
            continue
        dest = archive_root / entry["path"]
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            if dest.stat().st_size != src.stat().st_size:
                print(f"[docs-triage] 复制大小不一致：{entry['path']}", file=sys.stderr)
                return EXIT_USAGE
        manifest_lines.append(f"{_sha256(src)}  {entry['path']}")

    if missing:
        print(f"[docs-triage] 有 {len(missing)} 个候选文件不存在，终止：{missing[:5]}", file=sys.stderr)
        return EXIT_USAGE

    if dry_run:
        print(f"[docs-triage][dry-run] 将归档 {len(archive)} 篇到 {archive_root}")
        return EXIT_OK

    archive_root.mkdir(parents=True, exist_ok=True)
    (archive_root / "MANIFEST.txt").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")

    paths = [e["path"] for e in archive]
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rm", "-q", "--", *paths],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        print(f"[docs-triage] git rm 失败：{proc.stderr.strip()}", file=sys.stderr)
        return EXIT_USAGE

    removed_lines = sum(e["lines"] for e in archive)
    print(f"[docs-triage] 已归档 {len(paths)} 篇 / {removed_lines} 行 → {archive_root}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    p_report = sub.add_parser("report", help="生成归档候选清单")
    p_report.add_argument("--json", action="store_true", help="输出 JSON 到 stdout")
    p_apply = sub.add_parser("apply", help="复制到归档目录并 git rm")
    p_apply.add_argument("--archive-root", required=True, type=Path)
    p_apply.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.action == "report":
        return cmd_report(args.json)
    return cmd_apply(args.archive_root, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
