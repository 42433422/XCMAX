"""CPU inference tasks (OCR / intent) — Tier C inference queue."""

from __future__ import annotations

import logging

from app.extensions import celery_app
from app.utils.operational_errors import OPERATIONAL_ERRORS

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2, queue="inference")
def run_paddle_ocr_task(self, image_path: str):
    from pathlib import Path

    import numpy as np
    from PIL import Image

    from app.services.paddle_ocr_runner import predict_to_text_blocks

    try:
        img = np.array(Image.open(Path(image_path)))
        blocks = predict_to_text_blocks(img)
        return {"success": True, "blocks": blocks}
    except OPERATIONAL_ERRORS as exc:
        logger.exception("inference OCR failed")
        raise self.retry(exc=exc, countdown=5)


@celery_app.task(bind=True, max_retries=1, queue="inference")
def run_intent_recognition_task(self, text: str, **kwargs):
    from app.domain.services.unified_intent_recognizer import get_unified_intent_recognizer

    recognizer = get_unified_intent_recognizer()
    return recognizer.recognize(text)
