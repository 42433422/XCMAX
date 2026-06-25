#!/usr/bin/env python3
"""从 config/ssot.yaml 的 doc_registry/retired 段自动生成 SSOT 索引文档。

唯一真相源 = FHD/config/ssot.yaml（doc_registry + retired 两段）。
本脚本把它投影成人类可读的 FHD/docs/SSOT_INDEX.md（请勿手改 md）。

同一份 doc_registry 也被 scripts/dev/docs_ssot_lint.py 直接读取（lint 不再解析 md），
确保「机器登记表(ssot.yaml) + 文档登记表(SSOT_INDEX.md)」收敛为单一源。

用法：
  python scripts/dev/gen_ssot_index.py            # 写 SSOT_INDEX.md
  python scripts/dev/gen_ssot_index.py --check    # 重新生成并比对（忽略「生成于」时间戳行），不一致 exit 1
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
from pathlib import Path
from typing import Any

import yaml

# 脚本在 FHD/scripts/dev/ 下 → parents[3] = XCMAX/（仓根）
REPO_ROOT = Path(__file__).resolve().parents[3]
FHD_ROOT = REPO_ROOT / "FHD"
SSOT_YAML = FHD_ROOT / "config" / "ssot.yaml"
OUTPUT_DOC = FHD_ROOT / "docs" / "SSOT_INDEX.md"
DOCS_DIR = OUTPUT_DOC.parent  # FHD/docs/，markdown 链接相对此目录

GEN_LINE_PREFIX = "> 自动生成，请勿手改"


# ---------------------------------------------------------------------------
# 读取 ssot.yaml（doc_registry + retired）——供生成器与 docs_ssot_lint 复用
# ---------------------------------------------------------------------------
def _load_yaml() -> dict[str, Any]:
    with SSOT_YAML.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_doc_registry() -> list[dict[str, Any]]:
    """返回 doc_registry 段（[{key, label, doc, desc}, ...]）。"""
    return list(_load_yaml().get("doc_registry", []) or [])


def load_retired() -> list[dict[str, Any]]:
    """返回 retired 段（[{from, to, reason, note?}, ...]）。"""
    return list(_load_yaml().get("retired", []) or [])


def _resolve(repo_rel: str) -> Path:
    """仓根相对路径 → 绝对路径。"""
    return (REPO_ROOT / repo_rel).resolve()


def registered_paths() -> dict[str, Path]:
    """{label: SSOT 文档绝对路径}，供 docs_ssot_lint 比对（等价旧 parse_ssot_index）。"""
    out: dict[str, Path] = {}
    for entry in load_doc_registry():
        label = entry.get("label") or entry.get("key", "")
        doc = entry.get("doc")
        if label and doc:
            out[label] = _resolve(doc)
    return out


def retired_paths() -> set[Path]:
    """已退役 SSOT 原文档绝对路径集合（等价旧 parse_retired_files）。"""
    return {_resolve(e["from"]) for e in load_retired() if e.get("from")}


def _md_link_target(repo_rel: str) -> str:
    """仓根相对路径 → 相对 FHD/docs/ 的 markdown 链接目标（保持 md 内链接可点）。"""
    return os.path.relpath(_resolve(repo_rel), DOCS_DIR)


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------
def render_doc() -> str:
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    registry = load_doc_registry()
    retired = load_retired()

    parts: list[str] = []
    parts.append("# SSOT 索引（唯一真相源登记表 · 派生视图）")
    parts.append("")
    parts.append(
        f"{GEN_LINE_PREFIX}；源 `FHD/config/ssot.yaml`（doc_registry / retired 段）；"
        f"生成器 `scripts/dev/gen_ssot_index.py`；生成于 {now}"
    )
    parts.append("")
    parts.append(
        "> **本文件是 `config/ssot.yaml` 的派生视图，不是真相源**。"
        "要新增/修改 SSOT 登记，请改 [`config/ssot.yaml`](../config/ssot.yaml) 的 `doc_registry` 段，"
        "再运行 `python scripts/dev/gen_ssot_index.py`。冲突时以 `ssot.yaml` 为准。"
    )
    parts.append("")
    parts.append("## 登记规则")
    parts.append("")
    parts.append("1. 每个领域只允许一个 SSOT 文档")
    parts.append("2. 新增 SSOT 声明必须先在 `config/ssot.yaml` 的 `doc_registry` 登记")
    parts.append(
        "3. `scripts/dev/docs_ssot_lint.py` 直接读 `ssot.yaml` 的 `doc_registry`，"
        "扫描所有 md 文件中的 SSOT 声明并比对"
    )
    parts.append("4. 冲突时以 `config/ssot.yaml` 为准")
    parts.append("")
    parts.append("## 领域 SSOT 登记表")
    parts.append("")
    parts.append("| 领域 | SSOT 文档 | 说明 |")
    parts.append("|------|----------|------|")
    for entry in registry:
        label = entry.get("label") or entry.get("key", "")
        doc = entry.get("doc", "")
        desc = entry.get("desc", "")
        target = _md_link_target(doc) if doc else ""
        parts.append(f"| {label} | [{target}]({target}) | {desc} |")
    parts.append("")
    parts.append("## 已退役 SSOT（指针化）")
    parts.append("")
    parts.append("| 原文档 | 指向 | 原因 |")
    parts.append("|--------|------|------|")
    for entry in retired:
        src = _md_link_target(entry["from"]) if entry.get("from") else ""
        note = entry.get("note")
        src_cell = f"{src}（{note}）" if note else src
        to_target = _md_link_target(entry["to"]) if entry.get("to") else ""
        reason = entry.get("reason", "")
        parts.append(f"| {src_cell} | [{to_target}]({to_target}) | {reason} |")
    parts.append("")
    return "\n".join(parts) + "\n"


def _strip_gen_line(text: str) -> str:
    """移除「生成于」时间戳所在行，供 --check 比对（忽略时间戳）。"""
    return "\n".join(ln for ln in text.splitlines() if not ln.startswith(GEN_LINE_PREFIX))


def is_fresh() -> bool:
    """SSOT_INDEX.md 是否与 ssot.yaml 同步（忽略时间戳行）。"""
    if not OUTPUT_DOC.exists():
        return False
    existing = OUTPUT_DOC.read_text(encoding="utf-8")
    return _strip_gen_line(existing) == _strip_gen_line(render_doc())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="重新生成并与现有文件比对（忽略生成时间戳行），不一致 exit 1（CI 门禁）",
    )
    args = parser.parse_args()

    if args.check:
        if not OUTPUT_DOC.exists():
            print(f"[FAIL] {OUTPUT_DOC} 不存在，请先运行 gen_ssot_index.py 生成")
            return 1
        if is_fresh():
            print(f"[OK] {OUTPUT_DOC} 与 config/ssot.yaml 一致")
            return 0
        print(
            f"[FAIL] {OUTPUT_DOC} 已过期，与 config/ssot.yaml 不一致；"
            "请运行 python scripts/dev/gen_ssot_index.py 重新生成"
        )
        return 1

    OUTPUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_DOC.write_text(render_doc(), encoding="utf-8")
    print(f"[OK] 已生成 {OUTPUT_DOC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
