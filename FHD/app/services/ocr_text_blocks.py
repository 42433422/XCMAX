"""Platform OCR fallbacks that preserve text-block geometry."""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_MACOS_VISION_OCR_BLOCKS_JXA = r"""
function run(argv) {
  ObjC.import('Vision');
  ObjC.import('CoreImage');
  const path = String(argv[0] || '');
  if (!path) return '[]';
  const imageUrl = $.NSURL.fileURLWithPath(path);
  const image = $.CIImage.imageWithContentsOfURL(imageUrl);
  if (!image) return '[]';
  const blocks = [];
  const request = $.VNRecognizeTextRequest.alloc.init;
  request.recognitionLevel = $.VNRequestTextRecognitionLevelAccurate;
  request.usesLanguageCorrection = true;
  request.recognitionLanguages = $(['zh-Hans', 'en-US']);
  const handler = $.VNImageRequestHandler.alloc.initWithCIImageOptions(
    image, $.NSDictionary.dictionary
  );
  const error = Ref();
  if (!handler.performRequestsError($([request]), error)) return '[]';
  const observations = request.results;
  for (let i = 0; i < observations.count; i += 1) {
    const observation = observations.objectAtIndex(i);
    const candidates = observation.topCandidates(1);
    if (candidates.count === 0) continue;
    const candidate = candidates.objectAtIndex(0);
    const box = observation.boundingBox;
    blocks.push({
      text: ObjC.unwrap(candidate.string),
      confidence: Number(candidate.confidence),
      x: Number(box.origin.x),
      y: Number(box.origin.y),
      width: Number(box.size.width),
      height: Number(box.size.height)
    });
  }
  return JSON.stringify(blocks);
}
"""


def recognize_macos_vision_blocks(image_array: np.ndarray) -> list[dict[str, Any]]:
    tmp_path = ""
    try:
        from PIL import Image

        height, width = image_array.shape[:2]
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        Image.fromarray(image_array).save(tmp_path, format="PNG")
        proc = subprocess.run(
            [
                "/usr/bin/osascript",
                "-l",
                "JavaScript",
                "-e",
                _MACOS_VISION_OCR_BLOCKS_JXA,
                tmp_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0:
            logger.warning("macOS Vision OCR 分块失败: %s", (proc.stderr or "").strip()[:500])
            return []
        raw_blocks = json.loads(proc.stdout or "[]")
        blocks: list[dict[str, Any]] = []
        for raw in raw_blocks if isinstance(raw_blocks, list) else []:
            text = str(raw.get("text") or "").strip()
            if not text:
                continue
            left = max(0.0, float(raw.get("x") or 0) * width)
            block_width = max(0.0, float(raw.get("width") or 0) * width)
            block_height = max(0.0, float(raw.get("height") or 0) * height)
            top = max(
                0.0,
                (1.0 - float(raw.get("y") or 0) - float(raw.get("height") or 0)) * height,
            )
            confidence = max(0.0, min(1.0, float(raw.get("confidence") or 0.0)))
            blocks.append(
                {
                    "text": text,
                    "left": left,
                    "top": top,
                    "width": block_width,
                    "height": block_height,
                    "confidence": confidence,
                    "center": (
                        left + block_width / 2.0,
                        top + block_height / 2.0,
                    ),
                    "y_center": top + block_height / 2.0,
                }
            )
        return blocks
    except (json.JSONDecodeError, subprocess.SubprocessError, *RECOVERABLE_ERRORS) as exc:
        logger.warning("macOS Vision OCR 分块异常: %s", exc)
        return []
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


def recognize_tesseract_blocks(image_array: np.ndarray) -> list[dict[str, Any]]:
    try:
        import pytesseract
        from PIL import Image

        image = Image.fromarray(image_array)
        try:
            data = pytesseract.image_to_data(
                image,
                lang="chi_sim+eng",
                output_type=pytesseract.Output.DICT,
            )
        except RECOVERABLE_ERRORS:
            data = pytesseract.image_to_data(
                image,
                output_type=pytesseract.Output.DICT,
            )
        blocks: list[dict[str, Any]] = []
        for index, raw_text in enumerate(data.get("text") or []):
            text = str(raw_text or "").strip()
            if not text:
                continue
            confidence = max(0.0, min(100.0, float(data["conf"][index]))) / 100.0
            left = float(data["left"][index])
            top = float(data["top"][index])
            width = float(data["width"][index])
            height = float(data["height"][index])
            blocks.append(
                {
                    "text": text,
                    "left": left,
                    "top": top,
                    "width": width,
                    "height": height,
                    "confidence": confidence,
                    "center": (left + width / 2.0, top + height / 2.0),
                    "y_center": top + height / 2.0,
                }
            )
        return blocks
    except RECOVERABLE_ERRORS as exc:
        logger.warning("Tesseract OCR 分块异常: %s", exc)
        return []
