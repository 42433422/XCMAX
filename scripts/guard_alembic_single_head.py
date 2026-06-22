#!/usr/bin/env python3
"""Pre-commit / CI guard: keep every live Alembic tree on a single, connected head.

This catches the failure mode that silently rotted FHD/alembic for months:
multiple heads plus ``down_revision`` references to revisions that were never
authored (e.g. ``xcagi_v5_miniprogram``, ``2026_06_02_tenant_rbac``). When that
happens Alembic can no longer build its revision map at all — ``alembic upgrade
head`` / ``alembic history`` fail outright — yet nothing in CI noticed because no
job ever loaded the chain.

It is intentionally dependency-free (stdlib only): it parses ``revision`` /
``down_revision`` out of each version file rather than importing Alembic or the
app, so it runs anywhere (pre-commit, CI, a bare checkout) without the heavy
app-import chain the migration modules drag in.

Fails (exit 1) on, per tree:
  * a ``down_revision`` pointing at a revision that no file defines (dangling), or
  * more than one head (use a merge migration to unify).

Multiple roots/bases are allowed (Alembic supports several bases merged later).

Run manually:  python3 scripts/guard_alembic_single_head.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Live trees only. FHD/XCAGI/alembic/versions is deliberately excluded: its
# alembic.ini sets script_location=../alembic (-> FHD/alembic), so that copy is
# never loaded — it is dead and should be deleted, not guarded.
LIVE_TREES = (
    "FHD/alembic/versions",
    "成都修茈科技有限公司/MODstore_deploy/alembic/versions",
)

_REV = re.compile(r"^revision\s*[:=]\s*(.+)$", re.MULTILINE)
_DOWN = re.compile(r"^down_revision\s*[:=]\s*(.+?)(?:\n[A-Za-z_#]|\Z)", re.MULTILINE | re.DOTALL)


def _ids(text: str | None) -> list[str]:
    if text is None:
        return []
    return re.findall(r"['\"]([^'\"]+)['\"]", text)


def _parse(path: Path) -> tuple[str | None, list[str]]:
    src = path.read_text(encoding="utf-8", errors="replace")
    rm = _REV.search(src)
    rev = (_ids(rm.group(1)) or [rm.group(1).strip()])[0] if rm else None
    dm = _DOWN.search(src)
    return rev, _ids(dm.group(1) if dm else None)


def check_tree(rel: str, root: Path) -> list[str]:
    d = root / rel
    if not d.is_dir():
        return []  # tree absent in this checkout — not this guard's problem
    nodes: dict[str, list[str]] = {}
    for f in sorted(d.glob("*.py")):
        if f.name == "__init__.py":
            continue
        rev, down = _parse(f)
        if rev:
            nodes[rev] = down
    all_revs = set(nodes)
    referenced: set[str] = set()
    dangling: list[str] = []
    for rev, downs in nodes.items():
        for parent in downs:
            referenced.add(parent)
            if parent not in all_revs:
                dangling.append(f"{rev} -> 不存在的父 {parent!r}")
    heads = sorted(all_revs - referenced)

    errors: list[str] = []
    if dangling:
        errors.append(
            f"[{rel}] 悬空 down_revision(引用了未定义的迁移,链断裂):\n"
            + "\n".join(f"    - {d}" for d in dangling)
        )
    if len(heads) > 1:
        errors.append(
            f"[{rel}] 多头 ({len(heads)} 个 head),alembic upgrade head 不确定。"
            " 请加一个 merge 迁移收口:\n"
            + "\n".join(f"    - {h}" for h in heads)
        )
    return errors


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    all_errors: list[str] = []
    for rel in LIVE_TREES:
        all_errors.extend(check_tree(rel, root))
    if all_errors:
        print("Alembic 迁移链校验失败:\n")
        print("\n\n".join(all_errors))
        print(
            "\n修复指引:悬空父=把 down_revision 指向真实存在的 revision(或删掉幽灵引用);"
            "多头=新建一个 down_revision 为各 head 元组的空 merge 迁移。"
        )
        return 1
    print("Alembic 迁移链 OK:每个活跃树均为单 head、无悬空 down_revision。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
