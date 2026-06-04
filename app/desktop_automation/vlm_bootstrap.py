"""VLM 切图建库（混合：API vision + 本地难例 + profile fallback）。"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
from typing import Any, Awaitable, Callable, Optional, Union

from app.desktop_automation.app_profile import load_profile
from app.desktop_automation.drivers import MacDriver, WindowsDriver
from app.desktop_automation.models import AppProfile
from app.desktop_automation.template_library import TemplateLibrary
from app.desktop_automation.yolo_resolver import NAME_TO_CLASS

logger = logging.getLogger(__name__)

VisionCallable = Callable[[str, str], Union[Awaitable[str], str]]

VLM_SPLIT_PROMPT = """你是桌面 UI 分析助手。请根据截图，将可交互 UI 功能块切分并返回 JSON（不要 markdown）：
{
  "regions": [
    {"id": "search_box", "label": "搜索框", "bbox_norm": [x_center, y_center, width, height], "confidence": 0.9, "description": "..."}
  ]
}
bbox_norm 均为 0~1 归一化（相对整窗宽高）。id 优先使用：search_box, contact_card, input_area, send_button, toolbar, sidebar。"""


class VLMBootstrapService:
    def __init__(self, library: TemplateLibrary | None = None):
        self.library = library or TemplateLibrary()

    def _pick_driver(self):
        win = WindowsDriver()
        if win.is_available():
            return win
        mac = MacDriver()
        if mac.is_available():
            return mac
        return None

    async def bootstrap_app(
        self,
        app_id: str,
        *,
        vision_call: Optional[VisionCallable] = None,
        use_profile_fallback: bool = True,
    ) -> dict[str, Any]:
        profile = load_profile(app_id)
        if not profile:
            return {"success": False, "error": f"profile not found: {app_id}"}

        driver = self._pick_driver()
        if not driver:
            if use_profile_fallback:
                return self._bootstrap_from_profile(profile)
            return {"success": False, "error": "no desktop driver available"}

        platform_key = "win" if driver.platform == "win" else "mac"
        match = (
            profile.window_match.get(platform_key)
            or profile.window_match.get("mac")
            or profile.window_match.get("win")
            or []
        )
        window = driver.find_window({platform_key: match})
        if not window:
            if use_profile_fallback:
                return self._bootstrap_from_profile(profile)
            return {"success": False, "error": f"window not found for {app_id}"}

        driver.focus_window(window)
        shot = driver.capture_window(window)
        regions = await self._split_regions(shot, profile, vision_call=vision_call)
        if not regions and use_profile_fallback:
            return self._bootstrap_from_profile(profile)

        saved = []
        for reg in regions:
            eid = str(reg.get("id") or "").strip()
            bbox = reg.get("bbox_norm")
            if not eid or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                continue
            crop_bytes = self._crop_png(shot, bbox, window)
            if not crop_bytes:
                continue
            yolo_id = NAME_TO_CLASS.get(eid)
            path = self.library.save_crop(
                app_id,
                eid,
                crop_bytes,
                bbox_norm=(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
                source=str(reg.get("source") or "vlm"),
                platform=driver.platform,
                window_size_hash=window.size_hash,
                yolo_class_id=yolo_id,
                description=str(reg.get("description") or reg.get("label") or ""),
            )
            saved.append({"element_id": eid, "path": str(path)})

        export_path = None
        if saved and NAME_TO_CLASS:
            export_path = str(self.library.export_yolo_dataset(app_id, NAME_TO_CLASS))

        return {
            "success": bool(saved),
            "app_id": app_id,
            "saved": saved,
            "yolo_export": export_path,
            "window": {"title": window.title, "size": window.size_hash},
        }

    async def _split_regions(
        self,
        shot: Any,
        profile: AppProfile,
        *,
        vision_call: Optional[VisionCallable] = None,
    ) -> list[dict[str, Any]]:
        if vision_call:
            try:
                img_b64 = self._image_to_b64(shot)
                hints = ", ".join(f"{k}({v.vlm_hint})" for k, v in profile.elements.items())
                prompt = f"{VLM_SPLIT_PROMPT}\n期望元素：{hints}"
                raw = vision_call(prompt, img_b64)
                if hasattr(raw, "__await__"):
                    raw = await raw  # type: ignore
                parsed = self._parse_regions_json(str(raw))
                for r in parsed:
                    r["source"] = "vlm_api"
                if parsed:
                    return parsed
            except Exception as exc:
                logger.warning("VLM API split failed: %s", exc)

        return self._local_heuristic_regions(profile)

    def _bootstrap_from_profile(self, profile: AppProfile) -> dict[str, Any]:
        saved = []
        for eid, elem in profile.elements.items():
            if not elem.fallback_norm:
                continue
            nx, ny = elem.fallback_norm
            meta_bbox = (nx, ny, 0.08, 0.05)
            placeholder = self._placeholder_png()
            path = self.library.save_crop(
                profile.app_id,
                eid,
                placeholder,
                bbox_norm=meta_bbox,
                source="profile_fallback",
                platform="any",
                yolo_class_id=NAME_TO_CLASS.get(eid),
                description=elem.vlm_hint,
            )
            saved.append({"element_id": eid, "path": str(path), "source": "profile_fallback"})
        export_path = (
            str(self.library.export_yolo_dataset(profile.app_id, NAME_TO_CLASS)) if saved else None
        )
        return {
            "success": bool(saved),
            "app_id": profile.app_id,
            "saved": saved,
            "yolo_export": export_path,
            "source": "profile_fallback",
        }

    def _local_heuristic_regions(self, profile: AppProfile) -> list[dict[str, Any]]:
        out = []
        for eid, elem in profile.elements.items():
            if not elem.fallback_norm:
                continue
            nx, ny = elem.fallback_norm
            out.append(
                {
                    "id": eid,
                    "label": elem.vlm_hint or eid,
                    "bbox_norm": [nx, ny, 0.08, 0.05],
                    "confidence": 0.6,
                    "description": elem.vlm_hint,
                    "source": "local_heuristic",
                }
            )
        return out

    @staticmethod
    def _parse_regions_json(text: str) -> list[dict[str, Any]]:
        text = text.strip()
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
        regions = data.get("regions") if isinstance(data, dict) else None
        return list(regions) if isinstance(regions, list) else []

    @staticmethod
    def _image_to_b64(shot: Any) -> str:
        from PIL import Image

        if not isinstance(shot, Image.Image):
            shot = Image.fromarray(shot)
        buf = io.BytesIO()
        shot.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")

    @staticmethod
    def _crop_png(shot: Any, bbox_norm: list | tuple, window: Any) -> bytes | None:
        from PIL import Image

        try:
            if not isinstance(shot, Image.Image):
                shot = Image.fromarray(shot)
            w, h = shot.size
            xc, yc, bw, bh = [float(x) for x in bbox_norm]
            x0 = max(0, int((xc - bw / 2) * w))
            y0 = max(0, int((yc - bh / 2) * h))
            x1 = min(w, int((xc + bw / 2) * w))
            y1 = min(h, int((yc + bh / 2) * h))
            if x1 <= x0 or y1 <= y0:
                return None
            crop = shot.crop((x0, y0, x1, y1))
            buf = io.BytesIO()
            crop.save(buf, format="PNG")
            return buf.getvalue()
        except Exception as exc:
            logger.debug("crop failed: %s", exc)
            return None

    @staticmethod
    def _placeholder_png() -> bytes:
        from PIL import Image

        img = Image.new("RGB", (32, 32), color=(200, 210, 230))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
