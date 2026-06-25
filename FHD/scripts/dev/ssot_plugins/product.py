"""product 域适配器：校验 config/product.yaml 产品 SSOT 自洽 + 防漂移。

产品 SSOT 真相源：config/product.yaml（三端 × 渠道 × 发行版）。

检查规则：
1. 结构自洽：product_version / editions / ends 齐全；server.edition_split 显式声明。
2. 版本同步：product_version == VERSION.md「XCAGI 总版本」；每个 active 手机渠道的
   version_anchor 文件实际版本 == product_version（落地「三渠道进度须同步」）。
3. 内部一致：任意一端 editions 只能引用 status==active 的发行版（personal 不得复活为某端在产发行版）。
4. personal 停产防漂移（声明 ↔ 代码/CI/构建 三处对齐）：
   - editions.personal.status == "discontinued"
   - app/mod_sdk/product_skus.py 标记 SKU_STATUS["personal"] == "discontinued"
   - 安卓 CI 工作流不再构建 personal（无 assemblePersonalDebug / lintPersonalDebug）
   - 安卓 build.gradle.kts 的 personal flavor 受 includeDiscontinuedSku 网关（默认不生成）
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

_FHD_ROOT = Path(__file__).resolve().parents[3]
if str(_FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(_FHD_ROOT))
from scripts.dev.ssot_plugins.base import ROOT  # noqa: E402

SSOT_FILE = ROOT / "config" / "product.yaml"
VERSION_MD = ROOT / "VERSION.md"
PRODUCT_SKUS_PY = ROOT / "app" / "mod_sdk" / "product_skus.py"
ANDROID_GRADLE = ROOT / "mobile-android" / "app" / "build.gradle.kts"
ANDROID_CI_WORKFLOWS = (
    ROOT / ".github" / "workflows" / "ci-mobile-android.yml",
    ROOT / ".github" / "workflows" / "release-android.yml",
)

# product.yaml 内的 repo/version_anchor 路径以仓根（XCMAX/）为基，带 FHD/ 前缀，
# 与 config/ssot.yaml derived 约定一致；ROOT 是 FHD 根，仓根是其父目录。
REPO_ROOT = ROOT.parent

_VERSION_FIELD_RE = {
    # 兼容 gradle（versionName = "x"）与 json5（"versionName": "x"）两种写法
    "version": re.compile(r'"?version"?\s*[:=]\s*"([\d.]+)"'),
    "versionName": re.compile(r'"?versionName"?\s*[:=]\s*"([\d.]+)"'),
}


def _canonical_version() -> str | None:
    """从 VERSION.md 解析「XCAGI 总版本」锚点（与 verify_version_anchors 一致）。"""
    if not VERSION_MD.is_file():
        return None
    for line in VERSION_MD.read_text(encoding="utf-8").splitlines():
        if "XCAGI 总版本" in line:
            m = re.search(r"`([\d.]+)`", line)
            if m:
                return m.group(1)
    return None


def _anchor_version(anchor: str) -> tuple[str | None, str | None]:
    """解析 'rel/path#field'，读出该文件的版本号。返回 (version, error)。"""
    if "#" not in anchor:
        return None, f"锚点格式应为 path#field：{anchor}"
    rel, field = anchor.split("#", 1)
    path = REPO_ROOT / rel
    if not path.is_file():
        return None, f"锚点文件不存在：{rel}"
    pattern = _VERSION_FIELD_RE.get(field)
    if pattern is None:
        return None, f"未知锚点字段：{field}"
    m = pattern.search(path.read_text(encoding="utf-8"))
    if not m:
        return None, f"{rel} 中未找到 {field}"
    return m.group(1), None


def check_drift() -> int:  # noqa: C901 - 线性校验，逐条独立
    if not SSOT_FILE.is_file():
        print(f"product: SSOT 文件不存在 {SSOT_FILE}", flush=True)
        return 2

    data = yaml.safe_load(SSOT_FILE.read_text(encoding="utf-8")) or {}
    errors: list[str] = []

    # 规则 1：结构
    product_version = str(data.get("product_version") or "").strip()
    if not product_version:
        errors.append("缺少 product_version")
    editions = data.get("editions") or {}
    ends = data.get("ends") or {}
    if not editions:
        errors.append("缺少 editions")
    if not ends:
        errors.append("缺少 ends")

    active_editions = {
        name for name, meta in editions.items() if (meta or {}).get("status") == "active"
    }

    # 规则 2：版本同步
    canonical = _canonical_version()
    if canonical and product_version and canonical != product_version:
        errors.append(f"product_version({product_version}) != VERSION.md 总版本({canonical})")

    mobile = ends.get("mobile") or {}
    for ch_name, ch in (mobile.get("channels") or {}).items():
        ch = ch or {}
        if ch.get("status") != "active":
            continue  # in_development / pending 渠道暂不强校版本
        anchor = str(ch.get("version_anchor") or "")
        if not anchor or anchor == "pending":
            errors.append(f"active 渠道 {ch_name} 缺 version_anchor")
            continue
        ver, err = _anchor_version(anchor)
        if err:
            errors.append(f"渠道 {ch_name}: {err}")
        elif product_version and ver != product_version:
            errors.append(f"渠道 {ch_name} 版本不同步：{anchor} = {ver}，应为 {product_version}")

    # 规则 3：每端 editions ⊆ active_editions
    for end_name, end in ends.items():
        for ed in (end or {}).get("editions", []) or []:
            if ed not in active_editions:
                errors.append(
                    f"端 {end_name} 引用了非 active 发行版 '{ed}'（个人版已停产不得列为在产发行版）"
                )
        if end_name == "server" and "edition_split" not in (end or {}):
            errors.append("server 端须显式声明 edition_split")

    # 规则 4：personal 停产防漂移
    personal = editions.get("personal") or {}
    if personal.get("status") != "discontinued":
        errors.append("editions.personal.status 应为 discontinued")

    if PRODUCT_SKUS_PY.is_file():
        txt = PRODUCT_SKUS_PY.read_text(encoding="utf-8")
        if not re.search(r'"personal"\s*:\s*"discontinued"', txt):
            errors.append("product_skus.py 未在 SKU_STATUS 标记 personal=discontinued")
    else:
        errors.append(f"找不到 {PRODUCT_SKUS_PY}")

    for wf in ANDROID_CI_WORKFLOWS:
        if not wf.is_file():
            continue
        wtxt = wf.read_text(encoding="utf-8")
        for forbidden in ("assemblePersonalDebug", "assemblePersonalRelease", "lintPersonalDebug"):
            if forbidden in wtxt:
                errors.append(f"{wf.name} 仍构建 personal：{forbidden}（个人版已停产）")

    if ANDROID_GRADLE.is_file():
        gtxt = ANDROID_GRADLE.read_text(encoding="utf-8")
        if 'create("personal")' in gtxt and "includeDiscontinuedSku" not in gtxt:
            errors.append(
                "build.gradle.kts 的 personal flavor 未被 includeDiscontinuedSku 网关（默认应不生成）"
            )

    if errors:
        print(f"product: {len(errors)} 个问题", flush=True)
        for e in errors:
            print(f"  - {e}", flush=True)
        return 1

    n_ends = len(ends)
    n_channels = len(mobile.get("channels") or {})
    print(
        f"product: OK（{n_ends} 端 / 手机 {n_channels} 渠道 / 在产发行版 {sorted(active_editions)} "
        f"/ 版本 {product_version} 同步）",
        flush=True,
    )
    return 0


def run(action: str, domain: dict[str, Any], *, dry_run: bool = True) -> int:
    if action == "check":
        return check_drift()
    if action == "sync":
        print("product: lint 模式无 sync", flush=True)
        return 0
    return 2


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    raise SystemExit(run(action, {}, dry_run=True))
