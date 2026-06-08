from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from modstore_server.ppt_compose_base import create_compose_deck
from modstore_server.ppt_edit_plan import validate_edit_plan
from modstore_server.ppt_ooxml_executor import apply_edit_plan, validate_pptx_package

WECHAT_BASE = (
    "/Users/a4243342/Library/Containers/com.tencent.xinWeChat/Data/Documents/"
    "xwechat_files/wxid_tfxzqdqt87oa22_62ce/temp/drag"
)
ORIGINAL = Path(WECHAT_BASE) / "PPT课堂练习作业 (2).pptx"


def test_validate_pptx_after_compose(tmp_path: Path):
    plan, _ = validate_edit_plan(
        {
            "mode": "compose",
            "title": "Test",
            "slides": [{"index": 1, "title": "One", "bullets": ["a"]}],
            "ops": [],
        }
    )
    out = tmp_path / "out.pptx"
    create_compose_deck(plan, out, workspace_root=tmp_path)
    ok, errs = validate_pptx_package(out)
    assert ok, errs
    with zipfile.ZipFile(out) as z:
        assert any(n.startswith("ppt/slides/") for n in z.namelist())


@pytest.mark.skipif(not ORIGINAL.is_file(), reason="local homework pptx not present")
def test_apply_marquee_preset_on_template(tmp_path: Path):
    import shutil

    out = tmp_path / "homework.pptx"
    shutil.copy2(ORIGINAL, out)
    plan, _ = validate_edit_plan(
        {
            "mode": "enhance",
            "ops": [{"op": "inject_timing", "slide": 1, "preset": "homework_marquee"}],
            "slides": [],
        }
    )
    result = apply_edit_plan(out, plan, workspace_root=tmp_path)
    assert result["has_animation"] is True
    with zipfile.ZipFile(out) as z:
        slide = z.read("ppt/slides/slide1.xml")
        assert b"timing>" in slide
