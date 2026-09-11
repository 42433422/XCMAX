"""desktop-platform-parity 域适配器:校验 Windows/macOS 双端平级发布 SSOT。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_FHD_ROOT = Path(__file__).resolve().parents[3]
if str(_FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(_FHD_ROOT))
from scripts.dev.ssot_plugins.base import ROOT, load_registry  # noqa: E402

SSOT_DOC = ROOT / "docs" / "desktop_platform_parity_ssot.md"
SSOT_INDEX = ROOT / "docs" / "SSOT_INDEX.md"
RELEASE_DESKTOP_WORKFLOW = ROOT / ".github" / "workflows" / "release-desktop.yml"

REQUIRED_DOC_SNIPPETS = (
    "唯一真相源",
    "Windows 与 macOS 平级发布",
    "双端验证通过才算完成",
    "FHD/desktop/platform/",
    "process.platform",
    "release_sha",
)


def _read_text(path: Path, errors: list[str]) -> str:
    if not path.is_file():
        errors.append(f"缺少文件: {path.relative_to(ROOT)}")
        return ""
    return path.read_text(encoding="utf-8")


def _check_registry(errors: list[str]) -> None:
    domains = load_registry()
    domain = next((d for d in domains if d.get("name") == "desktop-platform-parity"), None)
    if not domain:
        errors.append("config/ssot.yaml 未登记 desktop-platform-parity 域")
        return
    if domain.get("ssot") != "FHD/docs/desktop_platform_parity_ssot.md":
        errors.append("desktop-platform-parity.ssot 必须指向 FHD/docs/desktop_platform_parity_ssot.md")
    if "desktop_platform_parity.py check" not in str(domain.get("check") or ""):
        errors.append("desktop-platform-parity.check 必须调用 desktop_platform_parity.py check")
    derived = set(domain.get("derived") or [])
    # 平台适配层 desktop/platform/ 是规则三的目标位置，创建后须补登 derived（ssot_cli 要求派生路径存在）。
    for rel in ("FHD/.github/workflows/release-desktop.yml",):
        if rel not in derived:
            errors.append(f"desktop-platform-parity.derived 缺少 {rel}")


def _check_doc(errors: list[str]) -> None:
    text = _read_text(SSOT_DOC, errors)
    if text:
        for snippet in REQUIRED_DOC_SNIPPETS:
            if snippet not in text:
                errors.append(f"desktop_platform_parity_ssot.md 缺少片段: {snippet}")

    index_text = _read_text(SSOT_INDEX, errors)
    if "desktop_platform_parity_ssot.md" not in index_text:
        errors.append("SSOT_INDEX.md 未登记 desktop_platform_parity_ssot.md")


def _check_peer_release_workflow(errors: list[str]) -> None:
    """平级发布锚点:桌面发布流水线必须双 runner 并存、由同一 release_sha 驱动。"""
    text = _read_text(RELEASE_DESKTOP_WORKFLOW, errors)
    if not text:
        return
    for runner in ("runs-on: windows-latest", "runs-on: macos-latest"):
        if runner not in text:
            errors.append(f"release-desktop.yml 缺少平级发布 runner: {runner}")
    if "release_sha" not in text:
        errors.append("release-desktop.yml 缺少统一 release_sha 输入(双端同源锚点)")


def check_drift() -> int:
    errors: list[str] = []
    _check_registry(errors)
    _check_doc(errors)
    _check_peer_release_workflow(errors)

    if errors:
        print(f"desktop-platform-parity: {len(errors)} 处漂移", flush=True)
        for error in errors[:50]:
            print(f"  - {error}", flush=True)
        return 1
    print(
        "desktop-platform-parity: OK(双端平级发布 / 双端 DoD / 平台适配层规则已登记,发布流水线双 runner 一致)",
        flush=True,
    )
    return 0


def run(action: str, domain: dict[str, Any], *, dry_run: bool = True) -> int:
    if action == "check":
        return check_drift()
    if action == "sync":
        print("desktop-platform-parity: lint 模式无 sync", flush=True)
        return 0
    return 2


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    raise SystemExit(run(action, {}, dry_run=True))
