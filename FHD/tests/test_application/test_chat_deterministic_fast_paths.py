"""chat_deterministic_fast_paths 单元测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_MOD = _REPO / "app/application/workflow/chat_deterministic_fast_paths.py"
_spec = importlib.util.spec_from_file_location("chat_deterministic_fast_paths", _MOD)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
try_deterministic_chat_reply = _mod.try_deterministic_chat_reply


@pytest.mark.parametrize(
    "message",
    [
        "查一下产品表有多少条记录，只回答数字",
        "产品库总数是多少，只回答数字",
    ],
)
def test_product_count_fast_path(message: str) -> None:
    out = try_deterministic_chat_reply(message)
    assert out is not None
    assert out["response"].strip().isdigit()
    assert int(out["response"]) >= 0


def test_excel_row_count_fast_path(tmp_path: Path) -> None:
    sample = _REPO / "frontend/public/tutorial/xcagi-quickstart-sample-b.xlsx"
    if not sample.is_file():
        pytest.skip("sample xlsx missing")
    ctx = {
        "excel_analysis": {
            "file_path": str(sample),
            "filename": sample.name,
            "sheet_name": "教程示例-联系人",
        }
    }
    out = try_deterministic_chat_reply(
        "这个 Excel 第一个 sheet 有多少行？只回答数字",
        runtime_context=ctx,
        workspace_root=str(_REPO),
    )
    assert out is not None
    assert out["response"] == "3"


def test_no_match_returns_none() -> None:
    assert try_deterministic_chat_reply("你好") is None
