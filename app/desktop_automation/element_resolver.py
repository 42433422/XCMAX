"""运行时元素解析：模板 > YOLO > 缓存 > fallback。"""

from __future__ import annotations

import logging
from typing import Any

from app.desktop_automation.models import AppProfile, ElementMatch, WindowInfo
from app.desktop_automation.template_library import TemplateLibrary
from app.desktop_automation.yolo_resolver import detect_element

logger = logging.getLogger(__name__)

_COORD_CACHE: dict[str, tuple[int, int, str]] = {}


class ElementResolver:
    def __init__(self, library: TemplateLibrary, profile: AppProfile):
        self.library = library
        self.profile = profile

    def resolve(
        self,
        screenshot: Any,
        window: WindowInfo,
        element_id: str,
        *,
        driver_cache_key: str = "",
    ) -> ElementMatch | None:
        cache_key = f"{self.profile.app_id}:{element_id}:{driver_cache_key or window.size_hash}"
        if cache_key in _COORD_CACHE:
            x, y, src = _COORD_CACHE[cache_key]
            return ElementMatch(element_id, x, y, 0.85, src)

        # 1) 模板库
        tpl = self.library.match_template(screenshot, self.profile.app_id, element_id)
        if tpl:
            sx, sy, conf = tpl
            abs_x = window.x + sx
            abs_y = window.y + sy
            _COORD_CACHE[cache_key] = (abs_x, abs_y, "template")
            return ElementMatch(element_id, abs_x, abs_y, conf, "template")

        # 2) YOLO 多类
        yolo = detect_element(screenshot, element_id)
        if yolo:
            sx, sy, conf = yolo
            abs_x = window.x + sx
            abs_y = window.y + sy
            _COORD_CACHE[cache_key] = (abs_x, abs_y, "yolo")
            return ElementMatch(element_id, abs_x, abs_y, conf, "yolo")

        # 3) profile fallback 归一化坐标
        elem = self.profile.elements.get(element_id)
        if elem:
            fb = (
                elem.fallback_norm_mac
                if window.platform == "mac" and elem.fallback_norm_mac
                else elem.fallback_norm
            )
            if fb:
                nx, ny = fb
                abs_x = window.x + int(window.width * nx)
                abs_y = window.y + int(window.height * ny)
                _COORD_CACHE[cache_key] = (abs_x, abs_y, "fallback")
                return ElementMatch(element_id, abs_x, abs_y, 0.5, "fallback")

        return None

    def clear_cache(self, app_id: str | None = None) -> None:
        if not app_id:
            _COORD_CACHE.clear()
            return
        keys = [k for k in _COORD_CACHE if k.startswith(f"{app_id}:")]
        for k in keys:
            del _COORD_CACHE[k]
