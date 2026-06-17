"""Tests for app.tasks.inference_tasks — CPU inference task queue.

Strategy: Use .run() to bypass celery's __call__ wrapper.
For bind=True tasks, .run() passes the task instance as self, so self.retry()
is callable. When self.retry(exc=exc) is called, celery re-raises the original
exception via raise_with_context.
For OCR: create a real tiny PNG so PIL/numpy work naturally; only mock predict_to_text_blocks.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestRunPaddleOcrTask:
    def test_run_paddle_ocr_task_success(self, tmp_path):
        """Test OCR task returns success with valid input."""
        from PIL import Image

        from app.tasks.inference_tasks import run_paddle_ocr_task

        # Create a tiny real test image so PIL/numpy work naturally
        img = Image.new("RGB", (2, 2), color="red")
        img_path = tmp_path / "test.png"
        img.save(img_path)

        mock_blocks = [{"text": "hello", "confidence": 0.99}]
        with patch(
            "app.services.paddle_ocr_runner.predict_to_text_blocks",
            return_value=mock_blocks,
        ):
            result = run_paddle_ocr_task.run(str(img_path))

        assert result["success"] is True
        assert result["blocks"] == mock_blocks

    def test_run_paddle_ocr_task_non_recoverable_error_propagates(self, tmp_path):
        """Test OCR task propagates non-recoverable errors (TypeError) directly."""
        from PIL import Image

        from app.tasks.inference_tasks import run_paddle_ocr_task

        img = Image.new("RGB", (2, 2), color="red")
        img_path = tmp_path / "test.png"
        img.save(img_path)

        # TypeError is NOT in RECOVERABLE_ERRORS, so it propagates uncaught
        with patch(
            "app.services.paddle_ocr_runner.predict_to_text_blocks",
            side_effect=TypeError("bad image dtype"),
        ):
            with pytest.raises(TypeError, match="bad image dtype"):
                run_paddle_ocr_task.run(str(img_path))

    def test_run_paddle_ocr_task_recoverable_error_attempts_retry(self, tmp_path):
        """Test OCR task catches recoverable errors and attempts self.retry().

        RuntimeError IS in RECOVERABLE_ERRORS, so the except clause catches it
        and calls self.retry(exc=exc). Celery's retry re-raises the original
        exception (with Retry context) — proving the retry path was reached.
        """
        from PIL import Image

        from app.tasks.inference_tasks import run_paddle_ocr_task

        img = Image.new("RGB", (2, 2), color="red")
        img_path = tmp_path / "test.png"
        img.save(img_path)

        with patch(
            "app.services.paddle_ocr_runner.predict_to_text_blocks",
            side_effect=RuntimeError("OCR engine down"),
        ):
            # The function catches RuntimeError (recoverable) → calls self.retry(exc=exc)
            # celery re-raises the original exc (RuntimeError) via raise_with_context
            with pytest.raises(RuntimeError, match="OCR engine down"):
                run_paddle_ocr_task.run(str(img_path))

    def test_run_paddle_ocr_task_invalid_path_raises(self):
        """Test OCR task raises on non-existent image path."""
        from app.tasks.inference_tasks import run_paddle_ocr_task

        # FileNotFoundError (subclass of OSError) is in RECOVERABLE_ERRORS
        # so it will be caught and self.retry(exc=exc) attempted →
        # celery re-raises the original FileNotFoundError
        with pytest.raises(FileNotFoundError):
            run_paddle_ocr_task.run("/nonexistent/path/to/image.png")


class TestRunIntentRecognitionTask:
    def test_run_intent_recognition_task_success(self):
        """Test intent recognition task returns result."""
        mock_result = {"intent": "shipment_generate", "confidence": 0.95}

        mock_recognizer = MagicMock()
        mock_recognizer.recognize.return_value = mock_result

        with patch(
            "app.domain.services.unified_intent_recognizer.get_unified_intent_recognizer",
            return_value=mock_recognizer,
        ):
            from app.tasks.inference_tasks import run_intent_recognition_task

            result = run_intent_recognition_task.run("发货给张三")

        assert result == mock_result
        mock_recognizer.recognize.assert_called_once_with("发货给张三")

    def test_run_intent_recognition_task_empty_text(self):
        """Test intent recognition with empty text."""
        mock_result = {"intent": "unknown", "confidence": 0.0}

        mock_recognizer = MagicMock()
        mock_recognizer.recognize.return_value = mock_result

        with patch(
            "app.domain.services.unified_intent_recognizer.get_unified_intent_recognizer",
            return_value=mock_recognizer,
        ):
            from app.tasks.inference_tasks import run_intent_recognition_task

            result = run_intent_recognition_task.run("")

        assert result == mock_result
