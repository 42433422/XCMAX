"""回归保护：后端 CI 的依赖必须钉住会导致门禁翻红的浮动版本。

事故（2026-09-25，WO-0f1b3d12bab4）：`CI - Backend Python / modstore-backend-test`
在 **零代码变更** 的 main 上由绿转红。

两次 run 的依赖集合逐项比对后，**唯一**差异是：

    绿灯 313655b20（09-24，mypy 步骤 success）：greenlet-3.5.6 + sqlalchemy-2.0.54
    红灯 d34c354d1（09-25，mypy 步骤 failure，56 条错误）：sqlalchemy-2.1.0

mypy 在两次 run 中都是 2.3.1，不是变量（首轮曾误判为 mypy，CI 实测证伪）。
因此本测试锁两件事：

1. sqlalchemy 必须有显式上界（把已知会翻红的 2.1.x 挡在门外）；
2. lint/gate 类工具与 black/isort 同规则精确固定，避免工具发版静默改判定。

出界即红。sqlalchemy 2.1 的类型迁移是独立立项，不在本门禁内放宽。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEPLOY = _REPO_ROOT / "成都修茈科技有限公司" / "MODstore_deploy"
_PYPROJECT = _DEPLOY / "pyproject.toml"

# sqlalchemy 2.1.0 收紧 Query 类型推断，使 ~30 个既有模块被判 56 条错误
_SQLALCHEMY_MAX_EXCLUSIVE = (2, 1)


def _requirement(name: str) -> str:
    text = _PYPROJECT.read_text(encoding="utf-8")
    match = re.search(rf'^\s*"{re.escape(name)}[^"]*",', text, re.MULTILINE)
    assert match, f"{_PYPROJECT} 未声明 {name} 依赖"
    return match.group(0).strip().strip(",").strip('"')


def test_sqlalchemy_has_upper_bound() -> None:
    requirement = _requirement("sqlalchemy")
    assert "<" in requirement, (
        f"sqlalchemy 未设上界（{requirement}）：2.1.0 收紧 Query 类型推断会把既有"
        f"模块判红，而代码零变更。必须显式排除已知会翻红的版本。"
    )
    bound = re.search(r"<\s*(\d+)\.(\d+)", requirement)
    assert bound, f"sqlalchemy 上界不可解析：{requirement}"
    assert (int(bound.group(1)), int(bound.group(2))) <= _SQLALCHEMY_MAX_EXCLUSIVE, (
        f"sqlalchemy 上界 {requirement} 放行了已知会翻红的 2.1.x 及以上"
    )


@pytest.mark.parametrize("tool", ["mypy", "black", "isort"])
def test_lint_tools_are_exactly_pinned(tool: str) -> None:
    requirement = _requirement(tool)
    assert "==" in requirement, (
        f"{tool} 未精确固定（{requirement}）：lint/gate 类工具必须与 black/isort 同规则"
        f"钉死，否则工具发新版会在零代码变更的 main 上改变判定"
    )