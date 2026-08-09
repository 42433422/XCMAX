"""ssot_inventory 盘点脚本单测。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_classify_returns_three_groups():
    """classify 返回 registered/managed/orphan 三组，且 accountable 总数一致。"""
    from scripts.dev.ssot_inventory import classify

    registered, managed, orphan = classify()
    # ssot.yaml 里被 check/sync 命令引用的脚本应进入 registered
    assert registered, "应至少有一个已纳入 ssot 的规范性脚本"
    # 存量脚本应全部被登记（registered + managed），孤儿应为 0（--seed 已建基线）
    assert not orphan, f"不应存在孤儿脚本：{orphan}"


def test_check_returns_zero_when_no_orphan():
    """--check 在无孤儿时返回 0。"""
    from scripts.dev.ssot_inventory import cmd_check

    assert cmd_check() == 0


def test_is_normative_recognizes_patterns():
    """规范性命名识别：guard/check/count/ratchet/ssot/verify 前缀。"""
    from scripts.dev.ssot_inventory import _is_normative

    assert _is_normative("guard_mods_inline_ui.py")
    assert _is_normative("check_layer_ratchet.py")
    assert _is_normative("count_raw_sql.py")
    assert _is_normative("coverage_ratchet.py")
    assert _is_normative("service_topology_ssot.py")
    assert _is_normative("verify_doc_claims.py")
    assert not _is_normative("run_server.py")
    assert not _is_normative("make_foo.sh")


def test_domain_registered_in_registry():
    """dev-inventory 域已在 ssot.yaml 注册且 enabled。"""
    from scripts.dev.ssot_plugins.base import find_domain, load_registry

    d = find_domain(load_registry(), "dev-inventory")
    assert d is not None, "dev-inventory 域未注册"
    assert d.get("enabled", True), "dev-inventory 域未启用"


def test_ssot_gate_checks_dev_inventory():
    """ssot_cli check dev-inventory 可执行（返回 0 或 1）。"""
    from scripts.dev.ssot_cli import main

    code = main(["check", "dev-inventory"])
    assert code in (0, 1)
