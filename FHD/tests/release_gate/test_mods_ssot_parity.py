"""Release-gate test: FHD/mods (SSOT) 必须与 FHD/XCAGI/mods (导出副本) 保持一致。

背景：此前 mod parity 检查只挂在 advisory 的 `ssot-drift-gate` CI job
（`continue-on-error: true`），SSOT 与其派生副本之间的漂移可以合进 main，
事后才人肉修。本测试把同一份检查提升进 "Release gate (hard block)" 硬门。

漂移修复方式：  python scripts/dev/mods_ssot.py sync
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.release_gate

_FHD_ROOT = Path(__file__).resolve().parents[2]
_MODS_SSOT = _FHD_ROOT / "scripts" / "dev" / "mods_ssot.py"


def _load_mods_ssot():
    """按文件路径加载 mods_ssot.py，复用其与 CI 完全相同的比对逻辑。"""
    spec = importlib.util.spec_from_file_location("_mods_ssot_release_gate", _MODS_SSOT)
    assert spec and spec.loader, f"无法加载 {_MODS_SSOT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mods_ssot_in_parity_with_export() -> None:
    mod = _load_mods_ssot()

    mod_ids = mod.list_mod_ids(mod.SSOT_ROOT)
    assert mod_ids, f"SSOT 根目录未发现任何带 manifest.json 的 Mod：{mod.SSOT_ROOT}"

    issues: list[str] = []
    for mod_id in mod_ids:
        issues.extend(mod.compare_mod(mod_id))

    export_only = sorted(set(mod.list_mod_ids(mod.EXPORT_ROOT)) - set(mod_ids))
    issues.extend(
        f"{m}: 仅存在于 XCAGI/mods（SSOT 中无此 Mod，应删除或移回 mods/）"
        for m in export_only
    )

    assert not issues, (
        "Mod SSOT 与导出副本漂移（改 FHD/mods 后运行 "
        "`python scripts/dev/mods_ssot.py sync`）：\n"
        + "\n".join(f"  - {i}" for i in issues)
    )
