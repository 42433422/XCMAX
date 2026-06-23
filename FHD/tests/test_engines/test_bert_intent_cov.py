from __future__ import annotations

"""Branch coverage for app/ai_engines/bert/intent_service.py."""

import sys
from unittest.mock import MagicMock, patch

import pytest

# ── torch / transformers are optional heavy deps; stub them if missing ──────
for _mod in ("torch", "transformers"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

# torch.cuda.is_available must return a real bool, not a MagicMock
import torch  # noqa: E402 — imported after stub

torch.cuda.is_available = lambda: False

from app.ai_engines.bert.intent_service import (  # noqa: E402
    ID_TO_LABEL,
    INTENT_LABELS,
    LABEL_TO_ID,
    BertIntentClassifier,
)


class TestModuleLevelConstants:
    def test_intent_labels_is_list(self):
        assert isinstance(INTENT_LABELS, list)
        assert "greet" in INTENT_LABELS
        assert "unk" in INTENT_LABELS

    def test_label_to_id_mapping(self):
        assert LABEL_TO_ID["greet"] == INTENT_LABELS.index("greet")

    def test_id_to_label_mapping(self):
        for idx, label in enumerate(INTENT_LABELS):
            assert ID_TO_LABEL[idx] == label


class TestBertIntentClassifierInit:
    def test_default_device_cpu(self):
        with patch("torch.cuda.is_available", return_value=False):
            clf = BertIntentClassifier()
        assert clf.device == "cpu"

    def test_explicit_device(self):
        clf = BertIntentClassifier(device="cpu")
        assert clf.device == "cpu"

    def test_cuda_device_when_available(self):
        with patch("torch.cuda.is_available", return_value=True):
            clf = BertIntentClassifier()
        assert clf.device == "cuda"

    def test_default_attributes(self):
        clf = BertIntentClassifier(
            model_path=None,
            model_name="bert-base-chinese",
            max_length=64,
            confidence_threshold=0.7,
            device="cpu",
        )
        assert clf.max_length == 64
        assert clf.confidence_threshold == 0.7
        assert clf._initialized is False
        assert clf.model is None
        assert clf.tokenizer is None


class TestBertIntentClassifierLoadModel:
    def test_load_model_already_initialized(self):
        clf = BertIntentClassifier(device="cpu")
        clf._initialized = True
        result = clf.load_model()
        assert result is True  # short-circuit

    def test_load_model_no_path_success(self):
        """Simulates loading a default model by mocking transformers."""
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()
        mock_config = MagicMock()

        clf = BertIntentClassifier(device="cpu", model_name="bert-base-chinese")

        with (
            patch(
                "app.ai_engines.bert.intent_service.AutoModelForSequenceClassification.from_pretrained",
                return_value=mock_model,
            ),
            patch(
                "app.ai_engines.bert.intent_service.BertTokenizer.from_pretrained",
                return_value=mock_tokenizer,
            ),
        ):
            result = clf.load_model()

        assert result is True
        assert clf._initialized is True

    def test_load_model_with_path_success(self, tmp_path):
        """Simulates loading from a local path."""
        model_path = str(tmp_path)
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()
        mock_config = MagicMock()

        clf = BertIntentClassifier(model_path=model_path, device="cpu")

        with (
            patch(
                "app.ai_engines.bert.intent_service.AutoConfig.from_pretrained",
                return_value=mock_config,
            ),
            patch(
                "app.ai_engines.bert.intent_service.AutoModelForSequenceClassification.from_pretrained",
                return_value=mock_model,
            ),
            patch(
                "app.ai_engines.bert.intent_service.AutoTokenizer.from_pretrained",
                return_value=mock_tokenizer,
            ),
            patch("os.path.exists", return_value=True),
        ):
            result = clf.load_model()

        assert result is True

    def test_load_model_failure(self):
        """Simulate load failure → returns False."""
        clf = BertIntentClassifier(device="cpu")

        with (
            patch(
                "app.ai_engines.bert.intent_service.AutoModelForSequenceClassification.from_pretrained",
                side_effect=OSError("model not found"),
            ),
            patch(
                "app.ai_engines.bert.intent_service.BertTokenizer.from_pretrained",
                side_effect=OSError("tokenizer not found"),
            ),
        ):
            result = clf.load_model()

        assert result is False
        assert clf._initialized is False

    def test_load_model_with_fp16(self, tmp_path):
        """use_fp16=True calls model.half()."""
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        clf = BertIntentClassifier(device="cpu", use_fp16=True)

        with (
            patch(
                "app.ai_engines.bert.intent_service.AutoModelForSequenceClassification.from_pretrained",
                return_value=mock_model,
            ),
            patch(
                "app.ai_engines.bert.intent_service.BertTokenizer.from_pretrained",
                return_value=mock_tokenizer,
            ),
        ):
            clf.load_model()

        mock_model.half.assert_called_once()


class TestBertIntentClassifierPredict:
    def _make_initialized_clf(self):
        clf = BertIntentClassifier(device="cpu", confidence_threshold=0.7)
        clf._initialized = True
        clf.model = MagicMock()
        clf.tokenizer = MagicMock()
        return clf

    def test_predict_empty_text(self):
        clf = self._make_initialized_clf()
        result = clf.predict("")
        assert result["intent"] == "unk"
        assert result["confidence"] == 0.0

    def test_predict_whitespace_text(self):
        clf = self._make_initialized_clf()
        result = clf.predict("   ")
        assert result["intent"] == "unk"

    def test_predict_success_above_threshold(self):
        """Simulate a successful prediction using fully mocked torch ops."""
        clf = self._make_initialized_clf()
        clf.confidence_threshold = 0.7

        # tokenizer returns dict of MagicMock tensors
        clf.tokenizer.return_value = {"input_ids": MagicMock()}

        greet_idx = INTENT_LABELS.index("greet")

        # Mock the torch functions at the module level used by intent_service
        mock_probs_tensor = MagicMock()
        mock_confidence_val = MagicMock()
        mock_confidence_val.item.return_value = 0.95  # above threshold

        mock_predicted_idx_val = MagicMock()
        mock_predicted_idx_val.item.return_value = greet_idx

        mock_probs_slice = MagicMock()

        import app.ai_engines.bert.intent_service as svc_mod

        def fake_softmax(logits, dim):
            return mock_probs_tensor

        def fake_max(tensor, dim):
            return (mock_confidence_val, mock_predicted_idx_val)

        mock_probs_tensor.__getitem__ = MagicMock(return_value=mock_probs_slice)

        # no_grad context
        import contextlib

        @contextlib.contextmanager
        def fake_no_grad():
            yield

        with (
            patch.object(svc_mod.torch, "softmax", side_effect=fake_softmax),
            patch.object(svc_mod.torch, "max", side_effect=fake_max),
            patch.object(svc_mod.torch, "no_grad", return_value=fake_no_grad()),
        ):
            result = clf.predict("你好")

        assert result["intent"] == "greet"
        assert result["confidence"] == 0.95

    def test_predict_below_threshold_returns_unk(self):
        """Confidence below threshold → intent = unk."""
        clf = BertIntentClassifier(device="cpu", confidence_threshold=0.99)
        clf._initialized = True
        clf.model = MagicMock()
        clf.tokenizer = MagicMock()
        clf.tokenizer.return_value = {"input_ids": MagicMock()}

        greet_idx = INTENT_LABELS.index("greet")

        mock_confidence_val = MagicMock()
        mock_confidence_val.item.return_value = 0.5  # below 0.99

        mock_predicted_idx_val = MagicMock()
        mock_predicted_idx_val.item.return_value = greet_idx

        mock_probs_tensor = MagicMock()

        import contextlib

        import app.ai_engines.bert.intent_service as svc_mod

        @contextlib.contextmanager
        def fake_no_grad():
            yield

        with (
            patch.object(svc_mod.torch, "softmax", return_value=mock_probs_tensor),
            patch.object(
                svc_mod.torch, "max", return_value=(mock_confidence_val, mock_predicted_idx_val)
            ),
            patch.object(svc_mod.torch, "no_grad", return_value=fake_no_grad()),
        ):
            result = clf.predict("something")

        assert result["intent"] == "unk"

    def test_predict_failure_returns_unk(self):
        clf = self._make_initialized_clf()
        clf.tokenizer.side_effect = RuntimeError("tokenizer error")

        result = clf.predict("hello")
        assert result["intent"] == "unk"

    def test_predict_triggers_load_when_not_initialized(self):
        clf = BertIntentClassifier(device="cpu")
        assert clf._initialized is False

        # predict on empty text short-circuits before load_model does anything real
        result = clf.predict("")
        assert result["intent"] == "unk"

    def test_predict_calls_load_model_when_uninitialized(self):
        clf = BertIntentClassifier(device="cpu")

        # load_model does NOT set tokenizer; inject a mock tokenizer so predict can proceed
        def fake_load():
            clf._initialized = True
            clf.tokenizer = MagicMock(side_effect=RuntimeError("no model"))
            clf.model = MagicMock()
            return False

        with patch.object(clf, "load_model", side_effect=fake_load) as mock_load:
            result = clf.predict("hello")

        mock_load.assert_called_once()
        # RuntimeError from tokenizer is in RECOVERABLE_ERRORS → caught → unk
        assert result["intent"] == "unk"


class TestBertIntentClassifierPredictBatch:
    def test_predict_batch_delegates(self):
        clf = BertIntentClassifier(device="cpu")
        clf._initialized = True

        with patch.object(clf, "predict", side_effect=[{"intent": "greet"}, {"intent": "unk"}]):
            results = clf.predict_batch(["你好", "xyzxyz"])

        assert len(results) == 2
        assert results[0]["intent"] == "greet"

    def test_predict_batch_empty(self):
        clf = BertIntentClassifier(device="cpu")
        clf._initialized = True
        results = clf.predict_batch([])
        assert results == []

    def test_predict_batch_triggers_load(self):
        clf = BertIntentClassifier(device="cpu")

        with patch.object(clf, "load_model", return_value=False):
            results = clf.predict_batch([""])
        # empty string → unk
        assert results[0]["intent"] == "unk"
