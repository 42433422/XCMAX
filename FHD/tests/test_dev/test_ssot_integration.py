"""SSOT 框架全量集成测：ssot check 跑所有 enabled 域。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_ssot_list_shows_13_enabled(capsys):
    """list 输出 13 域，全部 enabled。"""
    from scripts.dev.ssot_cli import main

    main(["list"])
    out = capsys.readouterr().out
    # 13 行域（不含表头与分隔线）
    domain_lines = [
        l for l in out.splitlines() if l and not l.startswith("name") and not l.startswith("-")
    ]
    assert len(domain_lines) == 13
    yes_count = sum(1 for l in domain_lines if l.split()[1] == "yes")
    assert yes_count == 13  # 全部启用


def test_ssot_gate_returns_0_or_1(capsys):
    """gate 跑完所有 enabled 域，返回 0（一致）或 1（漂移），不返回 2/3。"""
    from scripts.dev.ssot_cli import main

    code = main(["gate"])
    assert code in (0, 1), f"gate 返回 {code}，应为 0 或 1"


def test_ssot_check_specific_domain():
    """check mods 单域可执行。"""
    from scripts.dev.ssot_cli import main

    code = main(["check", "mods"])
    assert code in (0, 1)
