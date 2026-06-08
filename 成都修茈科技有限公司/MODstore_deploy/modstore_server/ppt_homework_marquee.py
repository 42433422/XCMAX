"""Homework-style PPT marquee: preserve uploaded media, layout strip, inject click + motion timing."""

from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
P = f"{{{NS['p']}}}"
A = f"{{{NS['a']}}}"
R = f"{{{NS['r']}}}"

MARQUEE_Y = 2_667_000
IMG_CX = 1_905_000
IMG_CY = 1_270_000
MARQUEE_X = (317_500, 2_730_500, 5_143_500, 7_556_500, 9_969_500)
LOOP_X = (12_382_500, 14_795_500, 17_208_500, 19_621_500, 22_034_500)
PLAY_X = 698_500
PLAY_Y = 5_689_600
GRP_OFF_X = 317_500
GRP_EXT_CX = 23_622_000
GRP_EXT_CY = 1_270_000

TIMING_XML = (
    '<p:timing><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot">'
    '<p:childTnLst><p:seq concurrent="1" nextAc="seek"><p:cTn id="2" restart="whenNotActive" '
    'fill="hold" evtFilter="cancelBubble" nodeType="interactiveSeq"><p:stCondLst><p:cond evt="onClick" '
    'delay="0"><p:tgtEl><p:spTgt spid="8"/></p:tgtEl></p:cond></p:stCondLst><p:endSync evt="end" '
    'delay="0"><p:rtn val="all"/></p:endSync><p:childTnLst><p:par><p:cTn id="3" fill="hold">'
    '<p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst><p:par><p:cTn id="4" fill="hold">'
    '<p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst><p:par><p:cTn id="5" presetID="35" '
    'presetClass="path" presetSubtype="0" repeatCount="100000" fill="remove" nodeType="clickEffect">'
    '<p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst><p:animMotion origin="layout" '
    'path="M 0 0 L -0.989583 0 E" pathEditMode="relative" ptsTypes=""><p:cBhvr><p:cTn id="6" '
    'dur="8000" fill="hold"/><p:tgtEl><p:spTgt spid="14"/></p:tgtEl><p:attrNameLst><p:attrName>ppt_x</p:attrName>'
    "<p:attrName>ppt_y</p:attrName></p:attrNameLst></p:cBhvr></p:animMotion></p:childTnLst></p:cTn></p:par>"
    "</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn><p:nextCondLst>"
    '<p:cond evt="onClick" delay="0"><p:tgtEl><p:spTgt spid="8"/></p:tgtEl></p:cond></p:nextCondLst>'
    "</p:seq></p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>"
)

HOMEWORK_MARQUEE_RE = re.compile(
    r"动画|跑马灯|特效|过渡|补全|完善|改好|做成|做完|完成作业|作业.*(?:加|做|改|完成)|"
    r"(?:加|做|改|完成).*作业|美化|润色|排版|填充|补齐|"
    r"更新.*(?:pptx?|幻灯片)|(?:pptx?|幻灯片).*(?:改|加|做)|帮我做|帮我完成|"
    r"将.{0,12}制作|制作.{0,12}动画|带动画|均匀排列|播放.*动画|单击",
    re.I,
)


def is_homework_marquee_request(user_query: str) -> bool:
    t = str(user_query or "").strip()
    if not t:
        return True
    if HOMEWORK_MARQUEE_RE.search(t):
        return True
    if re.search(r"^完成[\s!！。.，,]*$", t, re.I):
        return True
    return False


def _embed_attr(pic: ET.Element) -> str:
    for el in pic.iter():
        tag = el.tag
        if tag.endswith("}blip") or tag.endswith("}svgBlip"):
            val = el.get(f"{{{NS['r']}}}embed") or el.get("embed")
            if val:
                return str(val)
    return ""


def _pic_layout(pic: ET.Element) -> Tuple[int, str, str, int, int]:
    cnv = pic.find(f".//{P}cNvPr")
    name = str(cnv.get("name") or "") if cnv is not None else ""
    sid = int(cnv.get("id") or 0) if cnv is not None else 0
    off = pic.find(f".//{A}off")
    x = int(off.get("x") or 0) if off is not None else 0
    y = int(off.get("y") or 0) if off is not None else 0
    return sid, name, _embed_attr(pic), x, y


def _parse_ooxml_fragment(fragment: str) -> ET.Element:
    wrapper = (
        f'<root xmlns:p="{NS["p"]}" xmlns:a="{NS["a"]}" xmlns:r="{NS["r"]}">' f"{fragment}</root>"
    )
    root = ET.fromstring(wrapper)
    return list(root)[0]


def _pic_xml(shape_id: int, name: str, embed: str, x: int, y: int) -> str:
    return (
        f'<p:pic><p:nvPicPr><p:cNvPr id="{shape_id}" name="{name}"/>'
        f'<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>'
        f'<p:blipFill><a:blip r:embed="{embed}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
        f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/>'
        f'<a:ext cx="{IMG_CX}" cy="{IMG_CY}"/></a:xfrm>'
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>'
    )


def _set_play_button_layout(play_xml: str) -> str:
    play_xml = re.sub(
        r"(<a:off x=\")(\d+)(\" y=\")(\d+)(\"/>)",
        lambda m: f"{m.group(1)}{PLAY_X}{m.group(3)}{PLAY_Y}{m.group(5)}",
        play_xml,
        count=1,
    )
    if 'id="8"' not in play_xml:
        play_xml = re.sub(
            r'(<p:cNvPr id=")(\d+)(" name=")',
            r"\g<1>8\g<3>",
            play_xml,
            count=1,
        )
    if "PlayButton" not in play_xml:
        play_xml = play_xml.replace('name="图片', 'name="PlayButton_ClickToStart', 1)
    return play_xml


def _build_marquee_group(flower_embeds: List[str]) -> str:
    pics: List[str] = []
    for i, embed in enumerate(flower_embeds[:5]):
        pics.append(_pic_xml(3 + i, f"MarqueeImg{i + 1}", embed, MARQUEE_X[i], MARQUEE_Y))
    for i, embed in enumerate(flower_embeds[:5]):
        pics.append(_pic_xml(9 + i, f"MarqueeImg{i + 1}_LoopCopy", embed, LOOP_X[i], MARQUEE_Y))
    inner = "".join(pics)
    return (
        '<p:grpSp><p:nvGrpSpPr><p:cNvPr id="14" name="MarqueeStrip_ClickPlay"/>'
        "<p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>"
        f'<p:grpSpPr><a:xfrm><a:off x="{GRP_OFF_X}" y="{MARQUEE_Y}"/>'
        f'<a:ext cx="{GRP_EXT_CX}" cy="{GRP_EXT_CY}"/>'
        f'<a:chOff x="{GRP_OFF_X}" y="{MARQUEE_Y}"/>'
        f'<a:chExt cx="{GRP_EXT_CX}" cy="{GRP_EXT_CY}"/></a:xfrm></p:grpSpPr>'
        f"{inner}</p:grpSp>"
    )


def rebuild_slide_xml(slide_xml: bytes) -> bytes:
    root = ET.fromstring(slide_xml)
    sp_tree = root.find(f".//{P}spTree")
    if sp_tree is None:
        raise ValueError("slide 缺少 p:spTree")

    title_sp: Optional[ET.Element] = None
    play_pic_xml = ""
    flower_candidates: List[Tuple[int, int, str, ET.Element]] = []

    for child in list(sp_tree):
        tag = child.tag
        if tag == f"{P}sp":
            ph = child.find(f".//{P}ph")
            if ph is not None and str(ph.get("type") or "") == "title":
                title_sp = child
            continue
        if tag != f"{P}pic":
            continue
        sid, name, embed, x, y = _pic_layout(child)
        if not embed:
            continue
        flower_candidates.append((y, x, embed, child))

    if len(flower_candidates) < 2:
        raise ValueError("未在幻灯片中找到足够的图片对象")

    flower_candidates.sort(key=lambda t: (t[0], t[1]))
    play_entry = flower_candidates[-1]
    play_pic_xml = ET.tostring(play_entry[3], encoding="unicode", method="xml")
    play_pic_xml = _set_play_button_layout(play_pic_xml)

    flowers_sorted = sorted(flower_candidates[:-1], key=lambda t: t[1])
    if len(flowers_sorted) < 5:
        flowers_sorted = sorted(flower_candidates, key=lambda t: t[1])[:5]
        play_entry = max(flower_candidates, key=lambda t: t[0])
        play_pic_xml = ET.tostring(play_entry[3], encoding="unicode", method="xml")
        play_pic_xml = _set_play_button_layout(play_pic_xml)
        flowers_sorted = [f for f in flowers_sorted if f[2] != play_entry[2]][:5]
        if len(flowers_sorted) < 5:
            flowers_sorted = sorted(flower_candidates, key=lambda t: t[1])[:5]

    flower_embeds = [f[2] for f in flowers_sorted[:5]]
    while len(flower_embeds) < 5:
        flower_embeds.append(flower_embeds[-1])

    for child in list(sp_tree):
        if child.tag in (f"{P}pic", f"{P}grpSp"):
            sp_tree.remove(child)

    if title_sp is not None:
        cnv = title_sp.find(f".//{P}cNvPr")
        if cnv is not None:
            cnv.set("id", "2")

    group_el = _parse_ooxml_fragment(_build_marquee_group(flower_embeds))
    play_el = _parse_ooxml_fragment(play_pic_xml)
    if title_sp is not None:
        idx = list(sp_tree).index(title_sp) + 1
        sp_tree.insert(idx, play_el)
        sp_tree.insert(idx + 1, group_el)
    else:
        sp_tree.append(play_el)
        sp_tree.append(group_el)

    c_sld = root.find(f".//{P}cSld")
    if c_sld is not None:
        for old in c_sld.findall(f"{P}timing"):
            c_sld.remove(old)
        timing_el = _parse_ooxml_fragment(TIMING_XML)
        sp_tree_parent = c_sld
        sp_tree_parent.append(timing_el)

    ET.register_namespace("p", NS["p"])
    ET.register_namespace("a", NS["a"])
    ET.register_namespace("r", NS["r"])
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def enhance_pptx_homework_marquee(src_path: Path, output_path: Path) -> Dict[str, Any]:
    src_path = Path(src_path)
    output_path = Path(output_path)
    if not src_path.is_file():
        raise FileNotFoundError(f"源 PPT 不存在：{src_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_path, output_path)

    slide_name = "ppt/slides/slide1.xml"
    with zipfile.ZipFile(output_path, "r") as zin:
        names = zin.namelist()
        if slide_name not in names:
            raise ValueError("仅支持单页作业模板（缺少 slide1.xml）")
        slide_xml = zin.read(slide_name)
        other = {n: zin.read(n) for n in names if n != slide_name}

    new_slide = rebuild_slide_xml(slide_xml)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for name, data in other.items():
            zout.writestr(name, data)
        zout.writestr(slide_name, new_slide)

    has_timing = b"timing>" in new_slide
    return {
        "output_path": str(output_path),
        "enhance_mode": "homework_marquee",
        "slide_count": 1,
        "has_animation": has_timing,
        "flower_count": 5,
    }
