"""回归保护：后端 CI 的 mypy 门禁必须可复现（工具版本精确固定）。

事故（2026-09-25，WO-0f1b3d12bab4）：`CI - Backend Python / modstore-backend-test`
在 **零代码变更** 的 main 上由绿转红——09-24 绿灯提交 313655b20 与 09-25 红灯提交
d34c354d1 之间，`成都修茈科技有限公司/MODstore_deploy` 的 diff 为 0 个文件；
唯一变量是 CI 里未固定版本的 `pip install mypy` 拉到了 mypy 2.3.1，同一份代码被
判出 56 条类型错误，发布门全线阻塞。

仓库对 black / isort 已是精确固定（`black==26.3.1` / `isort==6.1.0`），mypy 是
唯一漏网的 lint 类工具。本测试把这条约定锁死：漏固定即红，防止静默复发。
mypy 2.x 的迁移是独立立项，不在本门禁内放宽。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEPLOY = _REPO_ROOT / "成都修茈科技有限公司" / "MODstore_deploy"
_PYPROJECT = _DEPLOY / "pyproject.toml"
_WORKFLOW = _DEPLOY / ".github" / "workflows" / "ci-backend-python.yml"

_EXACT_PIN = re.compile(r"^mypy==\d+\.\d+\.\d+$")


def _dev_requirement(name: str) -> str:
    text = _PYPROJECT.read_text(encoding="utf-8")
    match = re.search(rf'^\s*"{re.escape(name)}[^"]*",', text, re.MULTILINE)
    assert match, f"{_PYPROJECT} 未声明 {name} 依赖"
    return match.group(0).strip().strip(",").strip('"')


@pytest.mark.parametrize("tool", ["mypy", "black", "isort"])
def test_lint_tools_are_exactly_pinned(tool: str) -> None:
    requirement = _dev_requirement(tool)
    assert "==" in requirement, (
        f"{tool} 未精确固定（{requirement}）：lint/gate 类工具必须与 "
        f"black/isort 同规则钉死版本，否则工具发新版会在零代码变更的 main 上翻红"
    )


def test_ci_mypy_install_is_pinned() -> None:
    text = _WORKFLOW.read_text(encoding="utf-8")
    lines = [ln.strip() for ln in text.splitlines() if "pip install" in ln and "mypy" in ln]
    assert lines, "CI 工作流未找到 mypy 安装步骤（门禁消失同样是回归）"
    for line in lines:
        pinned = [tok for tok in line.split() if tok.startswith("mypy")]
        assert pinned and all(_EXACT_PIN.match(tok) for tok in pinned), (
            f"CI mypy 安装未精确固定：{line!r}；必须写成 mypy==X.Y.Z，"
            f"否则 mypy 发新版会在零代码变更时把 main 打红"
        )