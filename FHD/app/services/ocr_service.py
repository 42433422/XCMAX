"""
OCR服务模块

提供图像文字识别、结构化数据提取等业务逻辑。
默认优先 PaddleOCR，与「识别模板」标签图走同一引擎；可通过环境变量切换或回退 EasyOCR/Tesseract。
"""

import logging
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np

from app.infrastructure.ocr_analysis import OCRAnalysisMixin
from app.services.ocr_text_blocks import (
    recognize_macos_vision_blocks,
    recognize_tesseract_blocks,
)
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
  request.recognitionLanguages = $(['zh-Hans', 'en-US']);
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


@dataclass
class OCRResult:
    """OCR识别结果"""

    text: str
    confidence: float
    bounding_box: tuple[int, int, int, int]
    block_type: str = "text"


class OCRService(OCRAnalysisMixin):
    """OCR服务类"""

    def __init__(self, use_gpu: bool = False):
        self.use_gpu = use_gpu
        self.reader = None
        self.tesseract_available = False
        self.macos_vision_available = False
        self._paddle_enabled = False
        self._init_engines()

    def _init_engines(self) -> None:
        """
        初始化识别后端。
        XCAGI_OCR_BACKEND: auto（默认）| paddle | easyocr | tesseract
        - auto: Paddle → EasyOCR → Tesseract
        - paddle: 仅 Paddle（失败则无任何引擎）
        """
        backend = os.environ.get("XCAGI_OCR_BACKEND", "auto").lower().strip() or "auto"

        if backend in ("auto", "paddle"):
            try:
                from app.services.paddle_ocr_runner import (
                    check_paddle_available,
                    get_paddle_ocr_instance,
                )

                if check_paddle_available():
                    get_paddle_ocr_instance()
                    self._paddle_enabled = True
                    logger.info("OCR 主引擎：PaddleOCR")
            except RECOVERABLE_ERRORS as e:
                logger.warning("PaddleOCR 初始化失败: %s", e)

        if backend == "paddle" and not self._paddle_enabled:
            logger.error(
                "XCAGI_OCR_BACKEND=paddle 但 PaddleOCR 不可用，请安装 paddlepaddle paddleocr"
            )

        if backend in ("auto", "easyocr") and not self._paddle_enabled:
            self._init_easyocr()

        if backend in ("auto", "macos_vision") and not self._paddle_enabled and self.reader is None:
            self._init_macos_vision()

        if backend in ("auto", "tesseract") and not self._paddle_enabled and self.reader is None:
            self._init_tesseract()

        if (
            not self._paddle_enabled
            and self.reader is None
            and not getattr(self, "macos_vision_available", False)
            and not self.tesseract_available
        ):
            self._init_tesseract()

    def _init_easyocr(self) -> None:
        try:
            import easyocr

            self.reader = easyocr.Reader(["ch_sim", "en"], gpu=self.use_gpu)
            logger.info("OCR 回退引擎：EasyOCR")
        except ImportError:
            logger.warning("EasyOCR 未安装")
            self.reader = None
        except RECOVERABLE_ERRORS as e:
            logger.error("EasyOCR 初始化失败: %s", e)
            self.reader = None

    def _init_tesseract(self) -> None:
        """初始化Tesseract"""
        try:
            import pytesseract

            pytesseract.get_tesseract_version()
            self.tesseract_available = True
            logger.info("OCR 回退引擎：Tesseract")
        except RECOVERABLE_ERRORS:
            self.tesseract_available = False

    def _init_macos_vision(self) -> None:
        """Enable the OCR engine built into macOS (no Python package or model download)."""
        self.macos_vision_available = bool(
            sys.platform == "darwin" and os.path.isfile("/usr/bin/osascript")
        )
        if self.macos_vision_available:
            logger.info("OCR 回退引擎：macOS Vision")

    def _recognize_macos_vision(self, image_array: np.ndarray) -> str:
        if not self.macos_vision_available:
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
            return self._clean_text(proc.stdout or "")
        except (subprocess.SubprocessError, *RECOVERABLE_ERRORS) as exc:
            logger.warning("macOS Vision OCR 异常: %s", exc)
            return ""
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

    def _recognize_macos_vision_blocks(self, image_array: np.ndarray) -> list[dict[str, Any]]:
        if not self.macos_vision_available:
            return []
        return recognize_macos_vision_blocks(image_array)

    def _recognize_tesseract_blocks(self, image_array: np.ndarray) -> list[dict[str, Any]]:
        if not self.tesseract_available:
            return []
        return recognize_tesseract_blocks(image_array)

    def recognize(self, image) -> str:
        """
        识别图像中的文字

        Args:
            image: PIL Image 或 numpy数组格式的图像

        Returns:
            识别出的文字
        """
        if (
            not self._paddle_enabled
            and self.reader is None
            and not getattr(self, "macos_vision_available", False)
            and not self.tesseract_available
        ):
            logger.error("OCR引擎未初始化")
            return ""

        try:
            if hasattr(image, "convert"):
                image_array = np.array(image.convert("RGB"))
            else:
                image_array = image
                if image_array.ndim == 2:
                    image_array = np.stack([image_array] * 3, axis=-1)

            if self._paddle_enabled:
                from app.services.paddle_ocr_runner import predict_to_text_blocks

                blocks = predict_to_text_blocks(image_array)
                text = self._clean_text("\n".join(b["text"] for b in blocks if b.get("text")))
                return text

            if self.reader is not None:
                results = self.reader.readtext(image_array, detail=0)
                text = "\n".join(results)
                return self._clean_text(text)

            if getattr(self, "macos_vision_available", False):
                return self._recognize_macos_vision(image_array)

            if self.tesseract_available:
                from PIL import Image

                pil_image = Image.fromarray(image_array)
                import pytesseract

                text = pytesseract.image_to_string(pil_image, lang="chi_sim+eng")
                return self._clean_text(text)

        except RECOVERABLE_ERRORS as e:
            logger.error("OCR识别失败: %s", e)

        return ""

    def recognize_text_blocks(self, image) -> list[dict[str, Any]]:
        """
        返回带坐标的文本块（标签模板网格配对等使用）。Paddle 优先，否则 EasyOCR。
        """
        if hasattr(image, "convert"):
            image_array = np.array(image.convert("RGB"))
        else:
            image_array = image
            if image_array.ndim == 2:
                image_array = np.stack([image_array] * 3, axis=-1)

        if self._paddle_enabled:
            from app.services.paddle_ocr_runner import predict_to_text_blocks

            return predict_to_text_blocks(image_array)

        if self.reader is not None:
            return self._easyocr_text_blocks(image_array)

        if getattr(self, "macos_vision_available", False):
            return self._recognize_macos_vision_blocks(image_array)

        if self.tesseract_available:
            return self._recognize_tesseract_blocks(image_array)

        return []

    def _easyocr_text_blocks(self, image_array: np.ndarray) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        try:
            for bbox, text, confidence in self.reader.readtext(image_array, detail=1):
                text = (text or "").strip()
                if not text:
                    continue
                xs = [float(p[0]) for p in bbox]
                ys = [float(p[1]) for p in bbox]
                left, top, right, bottom = int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))
                cx = sum(xs) / len(xs)
                cy = sum(ys) / len(ys)
                blocks.append(
                    {
                        "text": text,
                        "left": left,
                        "top": top,
                        "width": right - left,
                        "height": bottom - top,
                        "conf": float(confidence) * 100.0,
                        "center": (cx, cy),
                        "y_center": cy,
                    }
                )
        except RECOVERABLE_ERRORS as e:
            logger.error("EasyOCR 分块识别失败: %s", e)
        return blocks

    def recognize_file(self, file_path: str) -> dict[str, Any]:
        """
        识别文件中的文字

        Args:
            file_path: 文件路径

        Returns:
            识别结果字典
        """
        try:
            if not os.path.exists(file_path):
                return {"success": False, "message": f"文件不存在: {file_path}", "text": ""}

            from PIL import Image

            image = Image.open(file_path)

            text = self.recognize(image)

            return {"success": True, "message": "识别成功", "text": text, "file_path": file_path}

        except RECOVERABLE_ERRORS as e:
            logger.exception("识别文件失败: %s", e)
            return {"success": False, "message": f"识别失败: {str(e)}", "text": ""}

    def recognize_with_details(self, image: np.ndarray) -> list[OCRResult]:
        """识别图像中的文字，返回详细信息"""
        results: list[OCRResult] = []

        try:
            if self._paddle_enabled:
                if image.ndim == 2:
                    image = np.stack([image] * 3, axis=-1)
                for b in self.recognize_text_blocks(image):
                    text = b.get("text") or ""
                    conf = float(b.get("conf", 0)) / 100.0
                    box = (b.get("left", 0), b.get("top", 0), b.get("width", 0), b.get("height", 0))
                    results.append(
                        OCRResult(
                            text=text,
                            confidence=conf,
                            bounding_box=box,
                            block_type=self._classify_text(text),
                        )
                    )
                return results

            if self.reader is None:
                return results

            easyocr_results = self.reader.readtext(image, detail=1)

            for bbox, text, confidence in easyocr_results:
                ocr_result = OCRResult(
                    text=text,
                    confidence=confidence,
                    bounding_box=tuple(int(x) for x in np.asarray(bbox).flatten()[:4]),
                    block_type=self._classify_text(text),
                )
                results.append(ocr_result)

        except RECOVERABLE_ERRORS as e:
            logger.error("OCR识别失败: %s", e)

        return results

    def recognize_text(self, image_path: str) -> dict[str, Any]:
        """应用层：按路径识别（与 recognize_file 一致，补充 confidence）。"""
        out = self.recognize_file(image_path)
        if out.get("success") and "confidence" not in out:
            out["confidence"] = 0.0
        return out

    def recognize_text_from_bytes(self, image_bytes: bytes) -> dict[str, Any]:
        """应用层：从字节识别。"""
        try:
            from PIL import Image

            img = Image.open(BytesIO(image_bytes))
            if self._paddle_enabled:
                blocks = self.recognize_text_blocks(img)
                text = self._clean_text("\n".join(b["text"] for b in blocks if b.get("text")))
                confs = [float(b.get("conf", 0)) for b in blocks]
                avg = (sum(confs) / len(confs) / 100.0) if confs else 0.0
                return {"success": bool(text.strip()), "text": text, "confidence": avg}
            text = self.recognize(img)
            return {"success": bool(text.strip()), "text": text, "confidence": 0.0}
        except RECOVERABLE_ERRORS as e:
            logger.exception("从字节 OCR 失败: %s", e)
            return {"success": False, "message": str(e), "text": "", "confidence": 0.0}

    def recognize_trademark(self, image_path: str) -> dict[str, Any]:
        """商标图识别（当前与通用识别相同）。"""
        return self.recognize_text(image_path)

    def recognize_product(self, image_path: str) -> dict[str, Any]:
        """产品信息图识别（当前与通用识别相同）。"""
        return self.recognize_text(image_path)

    def get_active_ocr_backend(self) -> str:
        """当前主引擎名称（用于诊断）。"""
        if self._paddle_enabled:
            return "paddleocr"
        if self.reader is not None:
            return "easyocr"
        if getattr(self, "macos_vision_available", False):
            return "macos_vision"
        if self.tesseract_available:
            return "tesseract"
        return "none"


ocr_service: OCRService | None = None


def get_ocr_service() -> OCRService:
    global ocr_service
    if ocr_service is None:
        ocr_service = OCRService()
    return ocr_service


# NEURO-DDD: 为 Services 层类添加 instrumentation
from app.neuro_bus.neuro_service_instrumentation import instrument_service_layer_class

instrument_service_layer_class(OCRService, "app.services.ocr_service")
