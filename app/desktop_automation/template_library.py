"""模板库：VLM/人工切图 crop + meta，供 ElementResolver 匹配。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.desktop_automation.paths import templates_dir

logger = logging.getLogger(__name__)

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore

try:
    import cv2

    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


class TemplateLibrary:
    def __init__(self, root: Path | None = None):
        self.root = root or templates_dir()

    def element_dir(self, app_id: str, element_id: str) -> Path:
        d = self.root / app_id / element_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_crop(
        self,
        app_id: str,
        element_id: str,
        image_bytes: bytes,
        *,
        bbox_norm: tuple[float, float, float, float] | None = None,
        source: str = "vlm",
        platform: str = "any",
        window_size_hash: str = "",
        yolo_class_id: int | None = None,
        description: str = "",
    ) -> Path:
        elem_dir = self.element_dir(app_id, element_id)
        crop_path = elem_dir / "crop.png"
        crop_path.write_bytes(image_bytes)
        meta = {
            "element_id": element_id,
            "app_id": app_id,
            "bbox_norm": list(bbox_norm) if bbox_norm else None,
            "source": source,
            "platform": platform,
            "window_size_hash": window_size_hash,
            "yolo_class_id": yolo_class_id,
            "description": description,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        (elem_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return crop_path

    def load_meta(self, app_id: str, element_id: str) -> dict[str, Any] | None:
        meta_path = self.element_dir(app_id, element_id) / "meta.json"
        if not meta_path.is_file():
            return None
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def list_elements(self, app_id: str) -> list[str]:
        base = self.root / app_id
        if not base.is_dir():
            return []
        return sorted([p.name for p in base.iterdir() if p.is_dir() and (p / "crop.png").is_file()])

    def match_template(
        self,
        screenshot_rgb: Any,
        app_id: str,
        element_id: str,
        *,
        threshold: float = 0.72,
    ) -> tuple[int, int, float] | None:
        """在截图中匹配模板，返回 (screen_x, screen_y, confidence) 或 None。"""
        if not HAS_CV2 or np is None:
            return None
        crop_path = self.element_dir(app_id, element_id) / "crop.png"
        if not crop_path.is_file():
            return None
        try:
            hay = np.array(screenshot_rgb)
            if hay.ndim == 3 and hay.shape[2] == 4:
                hay = cv2.cvtColor(hay, cv2.COLOR_RGBA2RGB)
            needle = cv2.imread(str(crop_path))
            if needle is None:
                return None
            needle = cv2.cvtColor(needle, cv2.COLOR_BGR2RGB)
            best_val = -1.0
            best_loc = (0, 0)
            for scale in (1.0, 0.9, 1.1, 0.8, 1.2):
                w = max(8, int(needle.shape[1] * scale))
                h = max(8, int(needle.shape[0] * scale))
                tpl = cv2.resize(needle, (w, h))
                if tpl.shape[0] >= hay.shape[0] or tpl.shape[1] >= hay.shape[1]:
                    continue
                res = cv2.matchTemplate(hay, tpl, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val > best_val:
                    best_val = float(max_val)
                    best_loc = (max_loc[0] + w // 2, max_loc[1] + h // 2)
            if best_val >= threshold:
                return best_loc[0], best_loc[1], best_val
        except Exception as exc:
            logger.debug("template match failed %s/%s: %s", app_id, element_id, exc)
        return None

    def export_yolo_dataset(self, app_id: str, class_map: dict[str, int]) -> Path:
        """从模板库 meta 导出 YOLO 训练样本目录结构。"""
        from app.desktop_automation.paths import yolo_export_dir

        out = yolo_export_dir() / app_id
        img_dir = out / "images"
        lbl_dir = out / "labels"
        img_dir.mkdir(parents=True, exist_ok=True)
        lbl_dir.mkdir(parents=True, exist_ok=True)
        names = {v: k for k, v in class_map.items()}
        (out / "classes.json").write_text(
            json.dumps({"names": names}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        idx = 0
        for element_id in self.list_elements(app_id):
            meta = self.load_meta(app_id, element_id) or {}
            bbox = meta.get("bbox_norm")
            cid = meta.get("yolo_class_id")
            if cid is None:
                cid = class_map.get(element_id)
            if not bbox or cid is None:
                continue
            src = self.element_dir(app_id, element_id) / "crop.png"
            # 需要全窗图；此处仅复制 crop 作占位，训练脚本可合并全窗
            dst_img = img_dir / f"{element_id}_{idx}.png"
            try:
                import shutil

                shutil.copy2(src, dst_img)
                xc, yc, ww, hh = bbox
                line = f"{int(cid)} {xc} {yc} {ww} {hh}\n"
                (lbl_dir / f"{element_id}_{idx}.txt").write_text(line, encoding="utf-8")
                idx += 1
            except Exception as exc:
                logger.warning("yolo export skip %s: %s", element_id, exc)
        return out
