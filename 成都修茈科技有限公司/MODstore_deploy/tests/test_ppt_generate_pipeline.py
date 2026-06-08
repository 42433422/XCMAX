from __future__ import annotations

import asyncio
import zipfile
from pathlib import Path

import pytest

from modstore_server.ppt_generate_pipeline import run_ppt_generate
from modstore_server.ppt_task_router import resolve_task_route

WECHAT_BASE = (
    "/Users/a4243342/Library/Containers/com.tencent.xinWeChat/Data/Documents/"
    "xwechat_files/wxid_tfxzqdqt87oa22_62ce/temp/drag"
)
ORIGINAL = Path(WECHAT_BASE) / "PPT课堂练习作业 (2).pptx"


def test_route_compose_without_template():
    r = resolve_task_route(user_query="做一份5页产品介绍PPT", template_path=None)
    assert r["mode"] == "compose"


def test_route_homework_recipe():
    r = resolve_task_route(
        user_query="完成跑马灯", template_path=ORIGINAL if ORIGINAL.is_file() else None
    )
    if ORIGINAL.is_file():
        assert r["recipe"] == "homework_marquee"


@pytest.mark.asyncio
async def test_compose_pipeline_no_llm(tmp_path: Path):
    src = tmp_path / "input.txt"
    src.write_text("做一份3页产品介绍PPT", encoding="utf-8")
    out = tmp_path / "outputs" / "output.pptx"
    out.parent.mkdir(parents=True, exist_ok=True)
    result = await run_ppt_generate(
        src,
        out,
        template_path=None,
        payload={"user_query": "做一份3页产品介绍PPT", "workspace_root": str(tmp_path)},
        ctx={},
        rule_spec={"default_output_relpath": "outputs/output.pptx", "output_schema": []},
    )
    assert Path(result["output_path"]).is_file()
    assert result.get("slide_count", 0) >= 1
    assert (tmp_path / "outputs" / "ppt_edit_plan.json").is_file()


@pytest.mark.asyncio
@pytest.mark.skipif(not ORIGINAL.is_file(), reason="local homework pptx not present")
async def test_enhance_homework_pipeline(tmp_path: Path):
    src = tmp_path / "plan.json"
    src.write_text(
        '{"title":"作业","slides":[{"index":1,"title":"t","bullets":[]}]}', encoding="utf-8"
    )
    out = tmp_path / "outputs" / "output.pptx"
    out.parent.mkdir(parents=True, exist_ok=True)
    result = await run_ppt_generate(
        src,
        out,
        template_path=ORIGINAL,
        payload={"user_query": "完成跑马灯动画", "workspace_root": str(tmp_path)},
        ctx={},
        rule_spec={"default_output_relpath": "outputs/output.pptx", "output_schema": []},
    )
    pptx = Path(result["output_path"])
    assert pptx.stat().st_size > 100_000
    with zipfile.ZipFile(pptx) as z:
        assert b"timing>" in z.read("ppt/slides/slide1.xml")
