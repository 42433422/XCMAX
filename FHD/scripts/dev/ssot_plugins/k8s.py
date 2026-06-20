"""k8s-manifests 域适配器：check 比较 FHD/k8s/ 与 FHD/XCAGI/k8s/。

derived (FHD/XCAGI/k8s/) 已被 README 声明弃用，sync 设为 null（不自动同步）。
check 只读比较两个目录的文件内容，检测漂移。
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

_FHD_ROOT = Path(__file__).resolve().parents[3]
if str(_FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(_FHD_ROOT))
from scripts.dev.ssot_plugins.base import ROOT  # noqa: E402

SSOT_ROOT = ROOT / "k8s"
DERIVED_ROOT = ROOT / "XCAGI" / "k8s"

SKIP_DIR_NAMES = frozenset({"__pycache__", "node_modules", ".git"})
SKIP_FILE_NAMES = frozenset({".DS_Store"})


def _skip_path(rel: Path) -> bool:
    if rel.name in SKIP_FILE_NAMES:
        return True
    return any(part in SKIP_DIR_NAMES for part in rel.parts)


def _iter_files(root: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    if not root.is_dir():
        return files
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if _skip_path(rel):
            continue
        files[rel.as_posix()] = path
    return files


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def check_drift() -> int:
    """只读检查：比较 SSOT 与 derived 的文件内容。

    derived 已弃用并清理（git rm）。若 derived 不存在，视为已清理完成，返回 OK。
    若 derived 仍存在（残留），报告漂移以提醒清理。
    """
    if not SSOT_ROOT.is_dir():
        print(f"k8s-manifests: SSOT 目录不存在 {SSOT_ROOT}", flush=True)
        return 2

    src_files = _iter_files(SSOT_ROOT)

    # derived 已清理（目录不存在或为空）→ OK
    if not DERIVED_ROOT.is_dir():
        print(f"k8s-manifests: OK（{len(src_files)} 个文件，derived 已清理）", flush=True)
        return 0

    dst_files = _iter_files(DERIVED_ROOT)
    if not dst_files:
        print(f"k8s-manifests: OK（{len(src_files)} 个文件，derived 已清理）", flush=True)
        return 0

    errors: list[str] = []

    # derived 缺少的文件
    for rel in sorted(set(src_files) - set(dst_files)):
        errors.append(f"derived 缺少 {rel}")

    # derived 多余的文件
    for rel in sorted(set(dst_files) - set(src_files)):
        errors.append(f"derived 多余 {rel}")

    # 内容不一致
    for rel in sorted(set(src_files) & set(dst_files)):
        if _digest(src_files[rel]) != _digest(dst_files[rel]):
            errors.append(f"内容不一致 {rel}")

    if errors:
        print(f"k8s-manifests: {len(errors)} 处漂移（derived 已弃用，建议 git rm FHD/XCAGI/k8s/）", flush=True)
        for e in errors[:20]:  # 最多显示 20 条
            print(f"  - {e}", flush=True)
        if len(errors) > 20:
            print(f"  ... 还有 {len(errors) - 20} 条", flush=True)
        return 1

    print(f"k8s-manifests: OK（{len(src_files)} 个文件一致）", flush=True)
    return 0


def run(action: str, domain: dict[str, Any], *, dry_run: bool = True) -> int:
    if action == "check":
        return check_drift()
    if action == "sync":
        print("k8s-manifests: derived 已弃用，不自动 sync（建议 git rm FHD/XCAGI/k8s/）", flush=True)
        return 0
    return 2


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    raise SystemExit(run(action, {}, dry_run=True))
