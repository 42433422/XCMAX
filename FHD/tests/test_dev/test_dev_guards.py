"""dev_guards 聚合守卫脚本单测。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_guards_include_static_guards():
    """dev-guards 聚合了游离的静态守卫脚本。"""
    from scripts.dev.dev_guards import GUARDS

    names = {g[0] for g in GUARDS}
    for expected in (
        "layer-ratchet",
        "type-debt",
        "raw-sql",
        "coverage-ramp-stubs",
        "test-bloat",
        "requirements-lock",
        "mods-inline-ui",
        "utils-boundary",
    ):
        assert expected in names, f"缺少守卫: {expected}"


def test_every_guard_has_argv_and_blocking():
    """每个守卫都有 argv 与 blocking 标志。"""
    from scripts.dev.dev_guards import GUARDS

    for name, argv, blocking in GUARDS:
        assert argv and argv[0] == "python"
        assert isinstance(blocking, bool)


def test_run_all_returns_int():
    """run_all 返回 (退出码, 结果列表)，退出码为 0/1/2。"""
    from scripts.dev.dev_guards import run_all

    code, results = run_all(verbose=False)
    assert code in (0, 1, 2)
    assert len(results) == len(__import__("scripts.dev.dev_guards", fromlist=["GUARDS"]).GUARDS)
    # 至少 1 个 blocking 守卫通过
    assert any(r["blocking"] and r["status"] == "ok" for r in results)


def test_domain_registered_in_registry():
    """dev-guards 域已在 ssot.yaml 注册且 enabled。"""
    from scripts.dev.ssot_plugins.base import find_domain, load_registry

    d = find_domain(load_registry(), "dev-guards")
    assert d is not None, "dev-guards 域未注册"
    assert d.get("enabled", True), "dev-guards 域未启用"


def test_ssot_gate_checks_dev_guards():
    """ssot_cli check dev-guards 可执行（返回 0 或 1）。"""
    from scripts.dev.ssot_cli import main

    code = main(["check", "dev-guards"])
    assert code in (0, 1)
