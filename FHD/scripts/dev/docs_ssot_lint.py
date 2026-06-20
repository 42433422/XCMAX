#!/usr/bin/env python3
"""SSOT 声明 lint 工具：扫描 md 文件中的 SSOT 声明，与 SSOT_INDEX.md 比对。

检测两类冲突：
  1. 未登记的 SSOT 声明：某 md 文件声称 SSOT 但不在 SSOT_INDEX.md 登记表中
  2. SSOT 文件未声明：SSOT_INDEX.md 中登记的 SSOT 文件本身未含 SSOT 声明

用法：
  python scripts/dev/docs_ssot_lint.py            # 仅打印告警，退出码 0
  python scripts/dev/docs_ssot_lint.py --strict   # 告警即退出码 1（CI 门禁）
"""
import argparse
import re
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[3]  # XCMAX/
FHD_ROOT = REPO_ROOT / "FHD"
SSOT_INDEX = FHD_ROOT / "docs" / "SSOT_INDEX.md"
SCAN_DIRS = [FHD_ROOT / "docs", REPO_ROOT / "docs"]
# 设计/规划文档（brainstorming spec、implementation plan）含 YAML 示例中的 "ssot:" 字段，
# 非权威 SSOT 声明，跳过扫描避免假阳性。
IGNORE_DIRS = {REPO_ROOT / "docs" / "superpowers"}

CLAIM_PATTERN = re.compile(r"(唯一真相源|SSOT|单一事实来源)", re.IGNORECASE)
# Markdown link in table cell: [text](path)
LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
# Table separator row: |------|------|
SEPARATOR_PATTERN = re.compile(r"^\|[\s\-:]+\|")
# Filename containing "ssot" (e.g., mods_ssot.py, CI_SSOT.md, repo-ssot-dayclose-*.md)
FILENAME_SSOT_PATTERN = re.compile(r"[\w./-]*[sS][sS][oO][tT][\w-]*\.\w+", re.IGNORECASE)
# Backtick-quoted code span: `...`
BACKTICK_PATTERN = re.compile(r"`[^`]+`")
# Markdown link: [text](url)
MD_LINK_PATTERN = re.compile(r"\[[^\]]*\]\([^)]*\)")
# Meta-references to the registry/lint tool itself (not claims)
META_REF_PATTERN = re.compile(r"(SSOT_INDEX\.md|docs_ssot_lint\.py)", re.IGNORECASE)


def parse_ssot_index(index_path: Path) -> dict[str, Path]:
    """解析 SSOT_INDEX.md 的领域登记表，返回 {领域: SSOT 文件路径}。

    只解析"## 领域 SSOT 登记表"下的表格，跳过"已退役"表格与其他章节。
    """
    if not index_path.exists():
        return {}

    content = index_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    registered: dict[str, Path] = {}
    in_registration_table = False

    for line in lines:
        stripped = line.strip()

        # Track which section we're in
        if stripped == "## 领域 SSOT 登记表":
            in_registration_table = True
            continue
        elif stripped.startswith("## "):
            # New section header → exit registration table
            in_registration_table = False
            continue

        if not in_registration_table:
            continue

        # Must be a table row
        if not stripped.startswith("|"):
            continue

        # Skip separator rows (|------|------|)
        if SEPARATOR_PATTERN.match(stripped):
            continue

        # Parse table row: | 领域 | SSOT 文档 | 说明 |
        parts = [p.strip() for p in stripped.split("|")]
        # parts[0] and parts[-1] are empty (before/after the outer |)
        if len(parts) < 4:
            continue

        domain = parts[1]
        ssot_cell = parts[2]

        # Skip header row
        if domain == "领域" or "SSOT 文档" in ssot_cell:
            continue

        # Extract link path from [text](path)
        link_match = LINK_PATTERN.search(ssot_cell)
        if link_match:
            rel_path = link_match.group(2)
        else:
            rel_path = ssot_cell.strip()

        if not rel_path:
            continue

        # Resolve path relative to SSOT_INDEX.md's directory (FHD/docs/)
        resolved = (index_path.parent / rel_path).resolve()
        registered[domain] = resolved

    return registered


def parse_retired_files(index_path: Path) -> set[Path]:
    """解析 SSOT_INDEX.md 的"已退役 SSOT"表格，返回退役文件路径集合。

    退役文件是指针化文件，本身会包含 SSOT 字样指向新 SSOT，不应视为未登记声明。
    """
    if not index_path.exists():
        return set()

    content = index_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    retired: set[Path] = set()
    in_retired_table = False

    for line in lines:
        stripped = line.strip()

        if stripped == "## 已退役 SSOT（指针化）":
            in_retired_table = True
            continue
        elif stripped.startswith("## "):
            in_retired_table = False
            continue

        if not in_retired_table:
            continue

        if not stripped.startswith("|"):
            continue

        if SEPARATOR_PATTERN.match(stripped):
            continue

        # Parse table row: | 原文档 | 指向 | 原因 |
        parts = [p.strip() for p in stripped.split("|")]
        if len(parts) < 4:
            continue

        original_cell = parts[1]

        # Skip header row
        if "原文档" in original_cell:
            continue

        # Extract link path from [text](path) if present
        link_match = LINK_PATTERN.search(original_cell)
        if link_match:
            rel_path = link_match.group(2)
        else:
            # Strip trailing parenthetical like "（覆盖率章节）"
            rel_path = re.sub(r"[（(].*?[)）]", "", original_cell).strip()

        if not rel_path:
            continue

        resolved = (index_path.parent / rel_path).resolve()
        retired.add(resolved)

    return retired


def is_real_claim(line: str) -> bool:
    """判断一行是否为真正的 SSOT 声明（而非引用、文件名或元描述）。

    排除以下非声明性用法：
    1. SSOT 仅出现在文件名中（如 mods_ssot.py、CI_SSOT.md）
    2. SSOT 仅出现在反引号代码 span 中
    3. SSOT 仅出现在 Markdown 链接目标中
    4. 行引用 SSOT_INDEX.md 或 docs_ssot_lint.py（元描述）
    """
    # 元引用：提到登记表或 lint 工具本身
    if META_REF_PATTERN.search(line):
        return False

    # 剥离文件名中的 ssot（如 mods_ssot.py、CI_SSOT.md、repo-ssot-dayclose-*.md）
    stripped = FILENAME_SSOT_PATTERN.sub("", line)
    # 剥离反引号代码 span
    stripped = BACKTICK_PATTERN.sub("", stripped)
    # 剥离 Markdown 链接（[text](url) 整体）
    stripped = MD_LINK_PATTERN.sub("", stripped)

    # 剥离后若不再含 SSOT/唯一真相源/单一事实来源，则非声明
    return bool(CLAIM_PATTERN.search(stripped))


def scan_claims(scan_dirs: list[Path], retired_files: Optional[set] = None) -> list[tuple[Path, int, str]]:
    """扫描所有 md 文件，返回 [(文件绝对路径, 行号, 匹配行文本)]。

    跳过 SSOT_INDEX.md 本身（它是登记表，不是 SSOT 声明）。
    跳过已退役的指针化文件（它们含 SSOT 字样但只是重定向指针）。
    仅保留真正的 SSOT 声明（排除文件名、代码 span、链接目标中的 ssot）。
    """
    if retired_files is None:
        retired_files = set()

    claims: list[tuple[Path, int, str]] = []
    seen_files: set[Path] = set()
    ssot_index_resolved = SSOT_INDEX.resolve()

    for scan_dir in SCAN_DIRS:
        if not scan_dir.exists():
            continue
        for md_file in scan_dir.rglob("*.md"):
            resolved = md_file.resolve()
            if resolved in seen_files:
                continue
            seen_files.add(resolved)

            # Skip files under ignored dirs (design/plan artifacts)
            if any(resolved.is_relative_to(d) for d in IGNORE_DIRS if d.exists()):
                continue

            # Skip SSOT_INDEX.md itself (it's the registry, not a claim)
            if resolved == ssot_index_resolved:
                continue

            # Skip retired pointer files
            if resolved in retired_files:
                continue

            try:
                content = resolved.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            for line_num, line in enumerate(content.splitlines(), start=1):
                # 先用宽松正则快速筛选
                if not CLAIM_PATTERN.search(line):
                    continue
                # 再用严格判断排除文件名/代码 span/链接/元引用
                if not is_real_claim(line):
                    continue
                claims.append((resolved, line_num, line.strip()))

    return claims


def main() -> int:
    parser = argparse.ArgumentParser(
        description="扫描 md 文件中的 SSOT 声明，与 SSOT_INDEX.md 比对，检测未登记或冲突的 SSOT 声明。"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="告警即退出码 1（用于 CI 门禁）",
    )
    args = parser.parse_args()

    registered = parse_ssot_index(SSOT_INDEX)
    registered_paths: set[Path] = set(registered.values())
    retired_files = parse_retired_files(SSOT_INDEX)
    claims = scan_claims(SCAN_DIRS, retired_files)

    conflicts = 0

    # 检测未登记的 SSOT 声明
    for file_path, line_num, matched_text in claims:
        if file_path not in registered_paths:
            print(f"[WARN] unregistered SSOT claim: {file_path}:{line_num} — {matched_text}")
            conflicts += 1

    # 检测 SSOT 文件未声明（仅检查 .md 文件）
    for domain, reg_path in registered.items():
        if reg_path.suffix.lower() != ".md":
            continue
        if not reg_path.exists():
            print(f"[WARN] registered SSOT file missing: {reg_path} (domain: {domain})")
            conflicts += 1
            continue

        try:
            content = reg_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        has_claim = any(
            CLAIM_PATTERN.search(line) and is_real_claim(line)
            for line in content.splitlines()
        )
        if not has_claim:
            print(f"[WARN] registered SSOT file missing claim: {reg_path}")
            conflicts += 1

    total_claims = len(claims)
    print(
        f"[INFO] total claims: {total_claims}, registered: {len(registered)}, conflicts: {conflicts}"
    )

    if conflicts > 0 and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
