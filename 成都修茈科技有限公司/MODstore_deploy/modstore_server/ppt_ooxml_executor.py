"""Apply ppt_edit_plan ops to an on-disk PPTX (OOXML + zip)."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

from modstore_server.ppt_edit_plan import validate_ooxml_fragment
from modstore_server.ppt_homework_marquee import TIMING_XML, enhance_pptx_homework_marquee

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
P = f"{{{NS['p']}}}"
A = f"{{{NS['a']}}}"
R = f"{{{NS['r']}}}"


def _parse_fragment(fragment: str) -> ET.Element:
    wrapper = (
        f'<root xmlns:p="{NS["p"]}" xmlns:a="{NS["a"]}" xmlns:r="{NS["r"]}">' f"{fragment}</root>"
    )
    return list(ET.fromstring(wrapper))[0]


PRESET_TIMING = {
    "marquee_path": TIMING_XML,
    "homework_marquee": TIMING_XML,
}


def _slide_path(slide_index: int) -> str:
    return f"ppt/slides/slide{slide_index}.xml"


def _inject_timing_on_slide(slide_xml: bytes, timing_fragment: str) -> bytes:
    root = ET.fromstring(slide_xml)
    c_sld = root.find(f".//{P}cSld")
    if c_sld is None:
        raise ValueError("slide 缺少 cSld")
    for old in c_sld.findall(f"{P}timing"):
        c_sld.remove(old)
    err = validate_ooxml_fragment(timing_fragment)
    if err:
        raise ValueError(f"timing fragment 无效：{err}")
    timing_el = _parse_fragment(
        timing_fragment
        if timing_fragment.strip().startswith("<p:timing")
        else f"<p:timing>{timing_fragment}</p:timing>"
    )
    c_sld.append(timing_el)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def apply_edit_plan(
    pptx_path: Path,
    plan: Dict[str, Any],
    *,
    workspace_root: Optional[Path] = None,
) -> Dict[str, Any]:
    pptx_path = Path(pptx_path)
    if not pptx_path.is_file():
        raise FileNotFoundError(f"pptx 不存在：{pptx_path}")

    warnings: List[str] = []
    applied = 0
    has_timing = False
    ops = plan.get("ops") if isinstance(plan.get("ops"), list) else []

    timing_ops = [o for o in ops if isinstance(o, dict) and o.get("op") == "inject_timing"]
    other_ops = [o for o in ops if isinstance(o, dict) and o.get("op") != "inject_timing"]
    if other_ops:
        warnings.append(f"跳过 {len(other_ops)} 条尚未实现的结构 op（已写入 compose 骨架）")

    if not timing_ops:
        with zipfile.ZipFile(pptx_path, "r") as z:
            for name in z.namelist():
                if name.startswith("ppt/slides/slide") and z.read(name).find(b"timing>") >= 0:
                    has_timing = True
        return {
            "applied_ops": applied,
            "has_animation": has_timing,
            "warnings": warnings,
        }

    slide_index = 1
    for op in timing_ops:
        preset = str(op.get("preset") or "").strip()
        fragment = str(op.get("ooxml_fragment") or "").strip()
        if preset in PRESET_TIMING:
            fragment = PRESET_TIMING[preset]
        elif preset == "homework_marquee":
            enhance_pptx_homework_marquee(pptx_path, pptx_path)
            applied += 1
            has_timing = True
            continue
        if not fragment:
            warnings.append("inject_timing 无 preset/fragment，已跳过")
            continue
        slide_index = int(op.get("slide") or slide_index)
        slide_name = _slide_path(slide_index)

        with zipfile.ZipFile(pptx_path, "r") as zin:
            if slide_name not in zin.namelist():
                warnings.append(f"缺少 {slide_name}，无法注入动画")
                continue
            names = zin.namelist()
            files = {n: zin.read(n) for n in names}
        try:
            files[slide_name] = _inject_timing_on_slide(files[slide_name], fragment)
            applied += 1
            has_timing = True
        except Exception as exc:
            warnings.append(f"inject_timing 失败：{exc}")
            continue
        with zipfile.ZipFile(pptx_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for name, data in files.items():
                zout.writestr(name, data)

    return {
        "applied_ops": applied,
        "has_animation": has_timing,
        "warnings": warnings,
    }


def validate_pptx_package(pptx_path: Path) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    pptx_path = Path(pptx_path)
    if not pptx_path.is_file():
        return False, ["文件不存在"]
    try:
        with zipfile.ZipFile(pptx_path, "r") as z:
            names = z.namelist()
            if "ppt/presentation.xml" not in names:
                errors.append("缺少 ppt/presentation.xml")
            slides = [n for n in names if re.match(r"ppt/slides/slide\d+\.xml", n)]
            if not slides:
                errors.append("无幻灯片 XML")
    except zipfile.BadZipFile:
        return False, ["损坏的 zip/pptx"]
    except Exception as exc:
        return False, [str(exc)]
    return len(errors) == 0, errors
