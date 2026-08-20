#!/usr/bin/env python3
"""SSOT 工程盘点：把分散的规范性"轮子"（守卫/棘轮/校验脚本）统一登记。

扫描 ``scripts/dev`` / ``scripts/ci`` / ``scripts/`` 下的规范性脚本，对照
``config/ssot.yaml`` 已登记域，分类为：

* ``registered`` —— 已被某个 ssot 域 check/sync 命令引用（已纳入 SSOT 工程）
* ``managed``   —— 游离于注册表外，但已登记到 ``docs/DEV_TOOLS_INVENTORY.md`` 清单（存量放行）
* ``orphan``    —— 新游离且未登记（只拦新增，防止轮子越滚越多）

生成 ``docs/DEV_TOOLS_INVENTORY.md`` 权威清单（脚本名、位置、角色、是否纳入 ssot、CI 引用、依赖）。

用法::

    python scripts/dev/ssot_inventory.py            # 生成清单（不阻断）
    python scripts/dev/ssot_inventory.py --seed     # 以当前值为基线种子（首次接入）
    python scripts/dev/ssot_inventory.py --check    # 棘轮门禁：新增 orphan 退出码 1
    python scripts/dev/ssot_inventory.py --json     # 以 JSON 输出分类

退出码: 0=一致 1=新增游离 2=用法错。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = FHD_ROOT.parent
REGISTRY = FHD_ROOT / "config" / "ssot.yaml"
INVENTORY_MD = FHD_ROOT / "docs" / "DEV_TOOLS_INVENTORY.md"

EXIT_OK, EXIT_ORPHAN, EXIT_USAGE = 0, 1, 2

# 规范性脚本命名识别（守卫/棘轮/校验类）。排除纯工具/一次性脚本。
NORM_NAME_RES = (
    re.compile(r"^guard_.+\.py$"),
    re.compile(r"^check_.+\.py$"),
    re.compile(r"^count_.+\.py$"),
    re.compile(r"^.*_ratchet.*\.py$"),
    re.compile(r"^.*_ssot.*\.py$"),
    re.compile(r"^arch_fitness\.py$"),
    re.compile(r"^safety_gate\.py$"),
    re.compile(r"^verify_.+\.py$"),
    re.compile(r"^validate_.+\.py$"),
    re.compile(r"^test_bloat_.+\.py$"),
    re.compile(r"^legacy_usage_.+\.py$"),
    re.compile(r"^prune_stale_.+\.py$"),
    re.compile(r"^publish_ci_workflows_to_root\.py$"),
    re.compile(r"^sync_duty_roster\.py$"),
    re.compile(r"^version_sync\.py$"),
    re.compile(r"^verify_version_anchors\.py$"),
    re.compile(r"^mods_ssot\.py$"),
    re.compile(r"^ssot_cli\.py$"),
    re.compile(r"^ssot_registry_crosscheck\.py$"),
    re.compile(r"^ssot_inventory\.py$"),
    re.compile(r"^dev_guards\.py$"),
)

# 跳过目录（一次性/实验/归档/测试辅助）
SKIP_DIRS = {
    "_archived",
    "experiments",
    "legacy",
    "tts",
    "verify",
    "tests",
    "generators",
    "ssot_plugins",
    "__pycache__",
}

# 扫描根目录（相对 FHD/）
SCAN_DIRS = ("scripts/dev", "scripts/ci", "scripts")


def _is_normative(name: str) -> bool:
    return any(r.match(name) for r in NORM_NAME_RES)


def _scan_scripts() -> list[Path]:
    """扫描 FHD 下规范性脚本，返回相对 FHD/ 的路径列表（去重、排序）。"""
    found: dict[str, Path] = {}
    for rel in SCAN_DIRS:
        base = FHD_ROOT / rel
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            if not _is_normative(p.name):
                continue
            rel_path = p.relative_to(FHD_ROOT).as_posix()
            found[rel_path] = p
    return sorted(found.values(), key=lambda p: p.relative_to(FHD_ROOT).as_posix())


def _load_registry_scripts() -> set[str]:
    """从 ssot.yaml 各 enabled 域 check/sync 命令中提取被引用的脚本相对路径。"""
    if not REGISTRY.is_file():
        return set()
    import yaml

    data = yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}
    referenced: set[str] = set()
    for d in data.get("domains") or []:
        if not d.get("enabled", True):
            continue
        for key in ("check", "sync"):
            cmd = d.get(key)
            if not cmd:
                continue
            for tok in cmd.split():
                # 匹配形如 scripts/dev/xxx.py 或 ../scripts/dev/xxx.py 的脚本引用
                m = re.search(r"(?:\.\./)?(scripts/[A-Za-z0-9_./-]+\.py)", tok)
                if m:
                    referenced.add(m.group(1))
                elif (
                    tok.endswith(".py")
                    and tok.startswith("scripts/")
                    or tok.startswith("../scripts/")
                ):
                    normalized = tok[3:] if tok.startswith("../") else tok
                    referenced.add(normalized)
    return referenced


def _parse_inventory_baseline() -> set[str]:
    """从 DEV_TOOLS_INVENTORY.md 的清单表解析已登记脚本相对路径。"""
    if not INVENTORY_MD.is_file():
        return set()
    text = INVENTORY_MD.read_text(encoding="utf-8")
    rows: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) >= 2:
            path = cells[1].strip().strip("`")
            if path.startswith("scripts/"):
                rows.add(path)
    return rows


def classify() -> tuple[list[dict], list[dict], list[dict]]:
    """返回 (registered, managed, orphan) 三个结构化的脚本清单。"""
    scripts = _scan_scripts()
    registry_refs = _load_registry_scripts()
    baseline = _parse_inventory_baseline()

    registered: list[dict] = []
    managed: list[dict] = []
    orphan: list[dict] = []

    for p in scripts:
        rel = p.relative_to(FHD_ROOT).as_posix()
        entry = {
            "script": p.name,
            "path": rel,
            "role": _role_of(p),
            "in_ssot": rel in registry_refs,
            "deps": "stdlib",
        }
        if rel in registry_refs:
            registered.append(entry)
        elif rel in baseline:
            entry["in_inventory"] = True
            managed.append(entry)
        else:
            orphan.append(entry)
    return registered, managed, orphan


def _role_of(p: Path) -> str:
    name = p.name
    if "_ssot" in name or name in (
        "ssot_cli.py",
        "ssot_registry_crosscheck.py",
        "ssot_inventory.py",
    ):
        return "ssot"
    if name.startswith("guard_") or name.startswith("check_") or name.startswith("validate_"):
        return "guard"
    if name.startswith("count_") or "_ratchet" in name:
        return "ratchet"
    if name.startswith("verify_"):
        return "verify"
    return "normative"


def _render_md(registered: list[dict], managed: list[dict], orphan: list[dict]) -> str:
    lines = [
        "# 开发工具盘点（规范性「轮子」登记表）",
        "",
        "> 由 `scripts/dev/ssot_inventory.py` 生成/维护，**请勿手改**。登记所有规范性",
        "> 守卫/棘轮/校验脚本归属，防止新「轮子」游离于 SSOT 工程外。",
        "> 最后更新：由生成时间戳决定。",
        "",
        "| 脚本 | 相对路径 | 角色 | 已纳入 ssot | 依赖 |",
        "|------|----------|------|-------------|------|",
    ]
    all_entries = sorted(registered + managed + orphan, key=lambda e: e["path"])
    for e in all_entries:
        lines.append(
            f"| {e['script']} | `{e['path']}` | {e['role']} | "
            f"{'yes' if e['in_ssot'] else 'no'} | {e['deps']} |"
        )
    lines.append("")
    lines.append(
        f"合计：{len(registered)} 已纳入 ssot / {len(managed)} 已登记清单 / {len(orphan)} 新游离"
    )
    lines.append("")
    return "\n".join(lines)


def cmd_generate() -> int:
    registered, managed, orphan = classify()
    INVENTORY_MD.parent.mkdir(parents=True, exist_ok=True)
    INVENTORY_MD.write_text(_render_md(registered, managed, orphan), encoding="utf-8")
    print(f"[ssot-inventory] 已生成 {INVENTORY_MD.relative_to(FHD_ROOT)}")
    print(
        f"[ssot-inventory] registered={len(registered)} managed={len(managed)} orphan={len(orphan)}"
    )
    return EXIT_OK


def cmd_check() -> int:
    registered, managed, orphan = classify()
    if orphan:
        print("::error::ssot-inventory: 存在未登记的新游离规范性脚本：", file=sys.stderr)
        for e in orphan:
            print(f"  - {e['path']}（角色={e['role']}）", file=sys.stderr)
        print(
            "修复：确认应纳入 ssot 工程（登记 ssot.yaml 或加入清单），或调整命名。", file=sys.stderr
        )
        return EXIT_ORPHAN
    print(f"[ssot-inventory] OK — registered={len(registered)} managed={len(managed)} orphan=0")
    return EXIT_OK


def cmd_json() -> int:
    registered, managed, orphan = classify()
    print(
        json.dumps(
            {"registered": registered, "managed": managed, "orphan": orphan},
            ensure_ascii=False,
            indent=2,
        )
    )
    return EXIT_OK if not orphan else EXIT_ORPHAN


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", action="store_true", help="以当前值为基线（= generate）")
    parser.add_argument("--check", action="store_true", help="棘轮门禁：新增孤儿退出码 1")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出分类")
    args = parser.parse_args(argv)

    if args.json:
        return cmd_json()
    if args.check:
        return cmd_check()
    return cmd_generate()  # 默认 generate（含 --seed）


if __name__ == "__main__":
    raise SystemExit(main())
