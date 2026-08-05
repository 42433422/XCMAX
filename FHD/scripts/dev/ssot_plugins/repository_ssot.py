"""repository-ssot 域：强制仓储实现唯一真相源（禁止重复造轮子）。

铁律（保新建删 / DDD 演进）：
- 唯一规范目录 = app/infrastructure/repositories/（SSOT）。
- 任一 <Entity>Repository port（app/application/ports/）最多只能有一个实现模块。
- 领域仓储实现不得散落在遗留目录 app/infrastructure/persistence/。

检查规则（AST 静态扫描，不 import 业务代码）：
1. 重复实现（阻断）：同一 port 类被 >1 个 _impl 模块继承 → DRIFT（重复造轮子）。
2. 遗留位置（阻断）：port 类实现模块位于 persistence/，而规范目录应承载 → DRIFT（迁移目标）。
   - 其他专属目录（如 persona/ 的 Redis-first 异步架构）不算违规，避免误报。

用法: python scripts/dev/ssot_plugins/repository_ssot.py check
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

_FHD_ROOT = Path(__file__).resolve().parents[3]
if str(_FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(_FHD_ROOT))

ROOT = _FHD_ROOT

CANONICAL_DIR = ROOT / "app" / "infrastructure" / "repositories"
LEGACY_DIR = ROOT / "app" / "infrastructure" / "persistence"
PORTS_DIR = ROOT / "app" / "application" / "ports"
INFRA_DIR = ROOT / "app" / "infrastructure"


def _port_classes(port_file: Path) -> list[str]:
    """从 port 文件提取实际仓储接口类名（如 PersonaProfileRepository）。"""
    try:
        tree = ast.parse(port_file.read_text(encoding="utf-8"), filename=str(port_file))
    except (OSError, SyntaxError):
        return []
    return [
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name.endswith("Repository")
    ]


def _impl_files_recursive() -> list[Path]:
    """递归收集 app/infrastructure/ 下所有 _impl.py 文件。"""
    if not INFRA_DIR.is_dir():
        return []
    return sorted(INFRA_DIR.rglob("*_impl.py"))


def _class_implemented_in(port_class: str, impl_files: list[Path]) -> list[Path]:
    """翻出继承了某 port 类的实现文件。"""
    hits: list[Path] = []
    for f in impl_files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases = [ast.unparse(b) for b in node.bases]
                if any(b == port_class or b.endswith("." + port_class) for b in bases):
                    hits.append(f)
                    break
    return hits


def check_drift() -> int:
    impl_files = _impl_files_recursive()
    errors: list[str] = []

    ports = sorted(PORTS_DIR.glob("*_repository.py")) if PORTS_DIR.is_dir() else []
    if not ports:
        print("repository-ssot: 未找到任何 *Repository port", flush=True)
        return 0

    classified: set[str] = set()
    for port_file in ports:
        for port_class in _port_classes(port_file):
            classified.add(port_class)
            impls = _class_implemented_in(port_class, impl_files)
            if not impls:
                errors.append(f"port {port_class}: 无任何实现模块（{port_file.name}）")
                continue
            # 规则 1：重复实现（唯一直真相源被破坏）
            if len(impls) > 1:
                rel = ", ".join(str(p.relative_to(ROOT)) for p in impls)
                errors.append(f"port {port_class}: 重复实现 → {rel}")
                continue
            # 规则 2：遗留位置（persistence/ 不应承载领域仓储实现）
            impl = impls[0]
            try:
                impl.relative_to(LEGACY_DIR)
            except ValueError:
                continue
            errors.append(
                f"port {port_class}: 实现位于遗留目录 persistence/（{impl.relative_to(ROOT)}），"
                "需迁移到 app/infrastructure/repositories/（保新建删）"
            )

    if errors:
        print(f"repository-ssot: {len(errors)} 个仓储唯一真相源问题（保新建删）", flush=True)
        for e in errors:
            print(f"  - {e}", flush=True)
        return 1

    print(
        f"repository-ssot: OK（{len(classified)} 个 port，全部唯一且位置规范）",
        flush=True,
    )
    return 0


def run(action: str, domain: dict[str, Any], *, dry_run: bool = True) -> int:
    if action == "check":
        return check_drift()
    if action == "sync":
        print("repository-ssot: lint 模式无 sync（迁移为人工代码改动）", flush=True)
        return 0
    return 2


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    raise SystemExit(run(action, {}, dry_run=True))
