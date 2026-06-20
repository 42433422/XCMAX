"""ssot_cli 单测。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_cli_list_prints_all_domains(capsys):
    """list 打印所有域（含 enabled 状态）。"""
    from scripts.dev.ssot_cli import main

    code = main(["list"])
    out = capsys.readouterr().out
    assert code == 0
    assert "mods" in out and "version" in out
    assert "test-files" in out  # disabled 域也列出


def test_cli_check_unknown_domain_returns_2(capsys):
    """check 不存在的域返回退出码 2。"""
    from scripts.dev.ssot_cli import main

    code = main(["check", "no-such-domain"])
    assert code == 2


def test_cli_check_enabled_domain_returns_0_or_1(capsys):
    """check 显式指定 enabled 域返回退出码 0（OK）或 1（DRIFT）。"""
    from scripts.dev.ssot_cli import main

    # test-files 是 enabled 域，check 应返回 0（无禁止文件）
    code = main(["check", "test-files"])
    assert code in (0, 1)


def test_cli_gate_runs_all_enabled(capsys):
    """gate 跑所有 enabled 域的 check，汇总退出码。"""
    from scripts.dev.ssot_cli import main

    # gate 会真实调用 10 个脚本；只要不崩、返回 0 或 1 即可
    code = main(["gate"])
    assert code in (0, 1)
