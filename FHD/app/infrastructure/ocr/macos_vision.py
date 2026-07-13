"""macOS Vision OCR adapter kept in the infrastructure layer."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import numpy as np

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

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


def is_macos_vision_available() -> bool:
    """Return whether the native Vision bridge can be invoked."""
    available = bool(sys.platform == "darwin" and os.path.isfile("/usr/bin/osascript"))
    if available:
        logger.info("OCR 回退引擎：macOS Vision")
    return available


def recognize_macos_vision(
    image_array: np.ndarray,
    *,
    cleaner: Callable[[str], str],
) -> str:
    """Run Vision through JXA and always remove the temporary image."""
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
        return cleaner(proc.stdout or "")
    except (subprocess.SubprocessError, *RECOVERABLE_ERRORS) as exc:
        logger.warning("macOS Vision OCR 异常: %s", exc)
        return ""
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


__all__ = ["is_macos_vision_available", "recognize_macos_vision"]
