"""OCR backend initialization and macOS Vision adapter."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger("app.services.ocr_service")

_MACOS_VISION_OCR_JXA = r"""
function run(argv) {
  ObjC.import('Vision');
  ObjC.import('CoreImage');
  const path = String(argv[0] || '');
  if (!path) return '';
  const imageUrl = $.NSURL.fileURLWithPath(path);
  const image = $.CIImage.imageWithContentsOfURL(imageUrl);
  if (!image) return '';
  const lines = [];
  const request = $.VNRecognizeTextRequest.alloc.init;
  request.recognitionLevel = $.VNRequestTextRecognitionLevelAccurate;
  request.usesLanguageCorrection = true;
  const handler = $.VNImageRequestHandler.alloc.initWithCIImageOptions(
    image, $.NSDictionary.dictionary
  );
  const error = Ref();
  if (!handler.performRequestsError($([request]), error)) return '';
  const observations = request.results;
  for (let i = 0; i < observations.count; i += 1) {
    const candidates = observations.objectAtIndex(i).topCandidates(1);
    if (candidates.count > 0) {
      lines.push(ObjC.unwrap(candidates.objectAtIndex(0).string));
    }
  }
  return lines.join('\n');
}
"""


def initialize_engines(service: Any) -> None:
    backend = os.environ.get("XCAGI_OCR_BACKEND", "auto").lower().strip() or "auto"
    if backend in ("auto", "paddle"):
        try:
            from app.services.paddle_ocr_runner import (
                check_paddle_available,
                get_paddle_ocr_instance,
            )

            if check_paddle_available():
                get_paddle_ocr_instance()
                service._paddle_enabled = True
                logger.info("OCR 主引擎：PaddleOCR")
        except RECOVERABLE_ERRORS as exc:
            logger.warning("PaddleOCR 初始化失败: %s", exc)
    if backend == "paddle" and not service._paddle_enabled:
        logger.error("XCAGI_OCR_BACKEND=paddle 但 PaddleOCR 不可用，请安装 paddlepaddle paddleocr")
    if backend in ("auto", "easyocr") and not service._paddle_enabled:
        service._init_easyocr()
    if (
        backend in ("auto", "macos_vision")
        and not service._paddle_enabled
        and service.reader is None
    ):
        service._init_macos_vision()
    if backend in ("auto", "tesseract") and not service._paddle_enabled and service.reader is None:
        service._init_tesseract()
    if (
        not service._paddle_enabled
        and service.reader is None
        and not getattr(service, "macos_vision_available", False)
        and not service.tesseract_available
    ):
        service._init_tesseract()


def initialize_easyocr(service: Any) -> None:
    try:
        import easyocr

        service.reader = easyocr.Reader(["ch_sim", "en"], gpu=service.use_gpu)
        logger.info("OCR 回退引擎：EasyOCR")
    except ImportError:
        logger.warning("EasyOCR 未安装")
        service.reader = None
    except RECOVERABLE_ERRORS as exc:
        logger.error("EasyOCR 初始化失败: %s", exc)
        service.reader = None


def initialize_tesseract(service: Any) -> None:
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        service.tesseract_available = True
        logger.info("OCR 回退引擎：Tesseract")
    except RECOVERABLE_ERRORS:
        service.tesseract_available = False


def initialize_macos_vision(service: Any) -> None:
    service.macos_vision_available = bool(
        sys.platform == "darwin" and os.path.isfile("/usr/bin/osascript")
    )
    if service.macos_vision_available:
        logger.info("OCR 回退引擎：macOS Vision")


def recognize_macos_vision(service: Any, image_array: np.ndarray) -> str:
    if not getattr(service, "macos_vision_available", False):
        return ""
    tmp_path = ""
    try:
        from PIL import Image

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        Image.fromarray(image_array).save(tmp_path, format="PNG")
        proc = subprocess.run(
            [
                "/usr/bin/osascript",
                "-l",
                "JavaScript",
                "-e",
                _MACOS_VISION_OCR_JXA,
                tmp_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0:
            logger.warning("macOS Vision OCR 失败: %s", (proc.stderr or "").strip()[:500])
            return ""
        return service._clean_text(proc.stdout or "")
    except (subprocess.SubprocessError, *RECOVERABLE_ERRORS) as exc:
        logger.warning("macOS Vision OCR 异常: %s", exc)
        return ""
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


__all__ = [
    "initialize_easyocr",
    "initialize_engines",
    "initialize_macos_vision",
    "initialize_tesseract",
    "recognize_macos_vision",
]
