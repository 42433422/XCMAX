"""SSOT 框架清单生成器测试。"""

from __future__ import annotations

from scripts.dev import generate_ssot_framework as generator


def test_render_inventory_uses_registry_counts_and_rows():
    domains = [
        {
            "name": "alpha",
            "enabled": True,
            "owner": "qa",
            "mode": "verify",
            "ssot": "alpha.json",
            "derived": ["one", "two"],
            "check": "python check.py",
            "sync": None,
        },
        {
            "name": "beta",
            "enabled": False,
            "owner": "docs",
            "mode": "lint",
            "ssot": "beta.md",
            "derived": [],
            "check": "python lint.py",
            "sync": None,
        },
    ]

    rendered = generator.render_inventory(domains)

    assert "当前共 **2** 个域：**1** 个启用、**1** 个禁用" in rendered
    assert "| alpha | 是 | qa | verify | alpha.json | 2 |" in rendered
    assert "| beta | 否 | docs | lint | beta.md | 0 |" in rendered


def test_replace_inventory_only_rewrites_generated_block():
    document = f"before\n{generator.BEGIN}\nstale\n{generator.END}\nafter\n"
    inventory = f"{generator.BEGIN}\nfresh\n{generator.END}"

    assert generator.replace_inventory(document, inventory) == "before\n" + inventory + "\nafter\n"


def test_committed_framework_inventory_is_current():
    assert generator.main(["--check"]) == 0
