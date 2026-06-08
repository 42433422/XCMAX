from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest

from modstore_server.ppt_homework_marquee import (
    enhance_pptx_homework_marquee,
    is_homework_marquee_request,
    rebuild_slide_xml,
)

WECHAT_BASE = (
    "/Users/a4243342/Library/Containers/com.tencent.xinWeChat/Data/Documents/"
    "xwechat_files/wxid_tfxzqdqt87oa22_62ce/temp/drag"
)
ORIGINAL = Path(WECHAT_BASE) / "PPT课堂练习作业 (2).pptx"


def test_homework_intent_detection():
    assert is_homework_marquee_request("完成")
    assert is_homework_marquee_request("做成跑马灯动画")
    assert not is_homework_marquee_request("总结这份幻灯片要点")


@pytest.mark.skipif(not ORIGINAL.is_file(), reason="local homework pptx not present")
def test_enhance_preserves_media_and_adds_timing(tmp_path: Path):
    out = tmp_path / "output.pptx"
    result = enhance_pptx_homework_marquee(ORIGINAL, out)
    assert result["has_animation"] is True
    assert out.stat().st_size > 100_000
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        media = [n for n in names if n.startswith("ppt/media/")]
        assert len(media) >= 5
        slide = z.read("ppt/slides/slide1.xml")
        assert b"timing>" in slide
        assert b"MarqueeStrip_ClickPlay" in slide


@pytest.mark.skipif(not ORIGINAL.is_file(), reason="local homework pptx not present")
def test_rebuild_slide_xml_structure():
    slide = ORIGINAL.read_bytes()
    # zip read
    import zipfile

    with zipfile.ZipFile(ORIGINAL) as z:
        slide = z.read("ppt/slides/slide1.xml")
    rebuilt = rebuild_slide_xml(slide)
    assert b'spid="14"' in rebuilt or b"MarqueeStrip_ClickPlay" in rebuilt
    assert b"<p:timing>" in rebuilt
