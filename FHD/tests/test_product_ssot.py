# -*- coding: utf-8 -*-
"""产品 SSOT 守卫：config/product.yaml 自洽 + personal 停产防漂移。

真相源 config/product.yaml；散文口径 specs/product-lines-3-plus-2.md。
本测试让 product 域校验随后端测试套阻断式运行（不止 advisory ssot gate）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

FHD_ROOT = Path(__file__).resolve().parents[1]
PRODUCT_YAML = FHD_ROOT / "config" / "product.yaml"
PRODUCT_PLUGIN = FHD_ROOT / "scripts" / "dev" / "ssot_plugins" / "product.py"


def _load() -> dict:
    return yaml.safe_load(PRODUCT_YAML.read_text(encoding="utf-8"))


def test_product_ssot_lint_passes():
    """product 域 lint 守卫必须绿（版本三渠道同步 + personal 停产对齐代码/CI/构建）。"""
    proc = subprocess.run(
        [sys.executable, str(PRODUCT_PLUGIN), "check"],
        capture_output=True,
        text=True,
        cwd=str(FHD_ROOT),
    )
    assert proc.returncode == 0, f"product.py check 失败:\n{proc.stdout}\n{proc.stderr}"


def test_three_ends_declared():
    ends = _load()["ends"]
    assert set(ends) == {"server", "desktop", "mobile"}


def test_server_has_no_edition_split():
    """服务器官网端无个人/企业强区分。"""
    assert _load()["ends"]["server"]["edition_split"] is False


def test_desktop_enterprise_only_on_win_and_mac():
    desktop = _load()["ends"]["desktop"]
    assert desktop["editions"] == ["enterprise"]
    assert set(desktop["platforms"]) == {"windows", "macos"}


def test_mobile_three_channels_enterprise_only():
    mobile = _load()["ends"]["mobile"]
    assert mobile["editions"] == ["enterprise"]
    assert mobile["sync_required"] is True
    assert set(mobile["channels"]) == {"android", "ios", "harmony"}


def test_personal_discontinued_everywhere():
    """个人版停产：SSOT 声明 ↔ 代码 SKU_STATUS 对齐，且不被任一端列为在产发行版。"""
    data = _load()
    assert data["editions"]["personal"]["status"] == "discontinued"
    active = {n for n, m in data["editions"].items() if m.get("status") == "active"}
    for end in data["ends"].values():
        for ed in end.get("editions", []) or []:
            assert ed in active, f"非 active 发行版被列入端 editions: {ed}"

    from app.mod_sdk.product_skus import ACTIVE_SKUS, SKU_STATUS, is_sku_active

    assert SKU_STATUS["personal"] == "discontinued"
    assert SKU_STATUS["enterprise"] == "active"
    assert "personal" not in ACTIVE_SKUS
    assert is_sku_active("enterprise") and not is_sku_active("personal")
