"""多类 YOLO 推理（search_box / contact_card / input_area / send_button）。"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore

try:
    from ultralytics import YOLO

    HAS_YOLO = True
except ImportError:
    HAS_YOLO = False

_YOLO_MODEL = None

# 与 yolo_ui_dataset/wechat_ui.yaml 对齐
DEFAULT_CLASS_NAMES = {
    0: "search_box",
    1: "contact_card",
    2: "send_button",
    3: "input_area",
}
NAME_TO_CLASS = {v: k for k, v in DEFAULT_CLASS_NAMES.items()}


def _model_paths() -> list[str]:
    from app.utils.path_utils import get_resource_path

    paths = []
    env = os.environ.get("WECHAT_YOLO_MODEL") or os.environ.get("DESKTOP_YOLO_MODEL")
    if env:
        paths.append(env)
    cv = get_resource_path("wechat_cv")
    if cv:
        paths.append(os.path.join(cv, "wechat_ui.pt"))
    from app.desktop_automation.paths import desktop_automation_data_root

    paths.append(str(desktop_automation_data_root() / "models" / "wechat_ui.pt"))
    return paths


def get_yolo_model():
    global _YOLO_MODEL
    if _YOLO_MODEL is not None:
        return _YOLO_MODEL
    if not HAS_YOLO:
        return None
    for p in _model_paths():
        if p and os.path.isfile(p):
            try:
                _YOLO_MODEL = YOLO(p)
                logger.info("loaded YOLO model: %s", p)
                return _YOLO_MODEL
            except Exception as exc:
                logger.warning("load YOLO %s failed: %s", p, exc)
    return None


def detect_element(
    screenshot_rgb: Any,
    element_id: str,
    *,
    class_map: dict[str, int] | None = None,
    conf: float = 0.35,
) -> tuple[int, int, float] | None:
    """
    在截图中检测 element，返回相对截图中心的 (x, y, confidence)。
    坐标为截图内像素，调用方需加上 window offset。
    """
    model = get_yolo_model()
    if model is None or np is None:
        return None
    cmap = class_map or NAME_TO_CLASS
    target = cmap.get(element_id)
    if target is None:
        return None
    try:
        arr = np.array(screenshot_rgb)
        if arr.ndim == 3 and arr.shape[2] == 4:
            import cv2

            arr = cv2.cvtColor(arr, cv2.COLOR_RGBA2RGB)
        results = model(arr, verbose=False, conf=conf)
        best = None
        best_conf = -1.0
        for r in results:
            if r.boxes is None:
                continue
            for box in r.boxes:
                cls_id = int(box.cls.item())
                if cls_id != target:
                    continue
                c = float(box.conf.item())
                if c <= best_conf:
                    continue
                xyxy = box.xyxy[0].tolist()
                cx = int((xyxy[0] + xyxy[2]) / 2)
                cy = int((xyxy[1] + xyxy[3]) / 2)
                best = (cx, cy, c)
                best_conf = c
        return best
    except Exception as exc:
        logger.debug("yolo detect %s failed: %s", element_id, exc)
        return None
