"""Tests for app.services.bert_intent_service — BERT intent classification service."""
from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from app.services.bert_intent_service import (
    ID_TO_LABEL,
    INTENT_LABELS,
    LABEL_TO_ID,
    BertIntentClassifier,
    BertIntentService,
    get_bert_intent_service,
    reset_bert_intent_service,
)


# ---------------------------------------------------------------------------
# Label constants
# ---------------------------------------------------------------------------


class TestIntentLabels:
    """Test intent label constants."""

    def test_labels_not_empty(self):
        assert len(INTENT_LABELS) > 0

    def test_label_to_id_bijective(self):
        for label, idx in LABEL_TO_ID.items():
            assert ID_TO_LABEL[idx] == label

    def test_known_intents_present(self):
        for intent in ("shipment_generate", "customers", "greet", "unk"):
            assert intent in LABEL_TO_ID

    def test_id_to_label_contiguous(self):
        keys = sorted(ID_TO_LABEL.keys())
        assert keys == list(range(len(INTENT_LABELS)))

    def test_unk_is_last(self):
        assert INTENT_LABELS[-1] == "unk"


# ---------------------------------------------------------------------------
# BertIntentClassifier — dummy model mode
# ---------------------------------------------------------------------------


class TestBertIntentClassifierDummy:
    """Test BertIntentClassifier with dummy model (no real ML stack)."""

    def test_init_with_local_files_only_no_model(self):
        """When local_files_only=True and no model_path, uses dummy model."""
        with patch(
            "app.services.bert_intent_service._import_ml_stack",
            side_effect=ImportError("no torch"),
        ):
            clf = BertIntentClassifier(local_files_only=True)
            assert clf.model is None
            assert clf.tokenizer is None
            assert clf.device == "cpu"

    def test_dummy_predict_returns_dict(self):
        with patch(
            "app.services.bert_intent_service._import_ml_stack",
            side_effect=ImportError("no torch"),
        ):
            clf = BertIntentClassifier(local_files_only=True)
            result = clf.predict("你好")
            assert "text" in result
            assert "intent" in result
            assert "confidence" in result
            assert result["model"] == "dummy"
            assert result["text"] == "你好"

    def test_dummy_predict_return_probs(self):
        with patch(
            "app.services.bert_intent_service._import_ml_stack",
            side_effect=ImportError("no torch"),
        ):
            clf = BertIntentClassifier(local_files_only=True)
            result = clf.predict("你好", return_probs=True)
            assert "all_probs" in result
            assert isinstance(result["all_probs"], dict)
            assert len(result["all_probs"]) > 0

    def test_dummy_predict_no_probs_by_default(self):
        with patch(
            "app.services.bert_intent_service._import_ml_stack",
            side_effect=ImportError("no torch"),
        ):
            clf = BertIntentClassifier(local_files_only=True)
            result = clf.predict("你好", return_probs=False)
            assert "all_probs" not in result

    def test_dummy_predict_batch(self):
        with patch(
            "app.services.bert_intent_service._import_ml_stack",
            side_effect=ImportError("no torch"),
        ):
            clf = BertIntentClassifier(local_files_only=True)
            results = clf.predict_batch(["你好", "开单"])
            assert len(results) == 2
            assert all(r["model"] == "dummy" for r in results)

    def test_dummy_predict_batch_return_probs(self):
        with patch(
            "app.services.bert_intent_service._import_ml_stack",
            side_effect=ImportError("no torch"),
        ):
            clf = BertIntentClassifier(local_files_only=True)
            results = clf.predict_batch(["你好"], return_probs=True)
            assert "all_probs" in results[0]

    def test_is_available_false_for_dummy(self):
        with patch(
            "app.services.bert_intent_service._import_ml_stack",
            side_effect=ImportError("no torch"),
        ):
            clf = BertIntentClassifier(local_files_only=True)
            assert clf.is_available() is False

    def test_dummy_predict_intent_in_labels(self):
        with patch(
            "app.services.bert_intent_service._import_ml_stack",
            side_effect=ImportError("no torch"),
        ):
            clf = BertIntentClassifier(local_files_only=True)
            result = clf.predict("测试")
            assert result["intent"] in INTENT_LABELS

    def test_dummy_predict_confidence_range(self):
        with patch(
            "app.services.bert_intent_service._import_ml_stack",
            side_effect=ImportError("no torch"),
        ):
            clf = BertIntentClassifier(local_files_only=True)
            result = clf.predict("测试")
            assert 0.0 <= result["confidence"] <= 1.0

    def test_init_with_explicit_device(self):
        with patch(
            "app.services.bert_intent_service._import_ml_stack",
            side_effect=ImportError("no torch"),
        ):
            clf = BertIntentClassifier(device="cpu", local_files_only=True)
            assert clf.device == "cpu"

    def test_init_default_confidence_threshold(self):
        with patch(
            "app.services.bert_intent_service._import_ml_stack",
            side_effect=ImportError("no torch"),
        ):
            clf = BertIntentClassifier(local_files_only=True)
            assert clf.confidence_threshold == 0.7

    def test_init_custom_confidence_threshold(self):
        with patch(
            "app.services.bert_intent_service._import_ml_stack",
            side_effect=ImportError("no torch"),
        ):
            clf = BertIntentClassifier(confidence_threshold=0.9, local_files_only=True)
            assert clf.confidence_threshold == 0.9


# ---------------------------------------------------------------------------
# BertIntentClassifier — model loading paths
# ---------------------------------------------------------------------------


class TestBertIntentClassifierModelLoading:
    """Test model loading logic with mocked ML stack."""

    def test_load_model_from_local_path(self, tmp_path):
        """Loading from a local directory with config.json."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        mock_auto_model_cls = MagicMock()
        mock_auto_tokenizer_cls = MagicMock()

        model_dir = str(tmp_path / "model")
        os.makedirs(model_dir, exist_ok=True)
        # HuggingFace config format: id2label keys are str ints, label2id keys are label names
        config_data = {
            "id2label": {"0": "greet", "1": "help"},
            "label2id": {"greet": "0", "help": "1"},
        }
        with open(os.path.join(model_dir, "config.json"), "w") as f:
            json.dump(config_data, f)

        with patch("app.services.bert_intent_service._import_ml_stack") as mock_import:
            mock_import.return_value = (mock_torch, mock_auto_model_cls, mock_auto_tokenizer_cls)
            clf = BertIntentClassifier(model_path=model_dir, device="cpu")
            mock_auto_tokenizer_cls.from_pretrained.assert_called()
            mock_auto_model_cls.from_pretrained.assert_called()

    def test_load_model_distillation_model_uses_standard_labels(self, tmp_path):
        """When config has LABEL_0 style labels, use standard intent labels."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        mock_auto_model_cls = MagicMock()
        mock_auto_tokenizer_cls = MagicMock()

        model_dir = str(tmp_path / "distill_model")
        os.makedirs(model_dir, exist_ok=True)
        config_data = {
            "id2label": {"0": "LABEL_0", "1": "LABEL_1"},
            "label2id": {"LABEL_0": 0, "LABEL_1": 1},
        }
        with open(os.path.join(model_dir, "config.json"), "w") as f:
            json.dump(config_data, f)

        with patch("app.services.bert_intent_service._import_ml_stack") as mock_import:
            mock_import.return_value = (mock_torch, mock_auto_model_cls, mock_auto_tokenizer_cls)
            clf = BertIntentClassifier(model_path=model_dir, device="cpu")
            # Should use standard ID_TO_LABEL, not LABEL_0
            assert clf.id2label == ID_TO_LABEL
            assert clf.label2id == LABEL_TO_ID

    def test_load_model_with_intent_labels_json(self, tmp_path):
        """When no config.json but intent_labels.json exists."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        mock_auto_model_cls = MagicMock()
        mock_auto_tokenizer_cls = MagicMock()

        model_dir = str(tmp_path / "model_no_config")
        os.makedirs(model_dir, exist_ok=True)
        labels_data = {
            "id2label": {"0": "greet", "1": "help"},
            "label2id": {"greet": "0", "help": "1"},
        }
        with open(os.path.join(model_dir, "intent_labels.json"), "w") as f:
            json.dump(labels_data, f)

        with patch("app.services.bert_intent_service._import_ml_stack") as mock_import:
            mock_import.return_value = (mock_torch, mock_auto_model_cls, mock_auto_tokenizer_cls)
            clf = BertIntentClassifier(model_path=model_dir, device="cpu")
            assert clf.id2label[0] == "greet"
            assert "greet" in clf.label2id

    def test_load_model_online_fallback(self):
        """When no local model, try loading from model hub."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        mock_auto_model_cls = MagicMock()
        mock_auto_tokenizer_cls = MagicMock()

        with patch("app.services.bert_intent_service._import_ml_stack") as mock_import:
            mock_import.return_value = (mock_torch, mock_auto_model_cls, mock_auto_tokenizer_cls)
            clf = BertIntentClassifier(model_name="bert-base-chinese", device="cpu")
            mock_auto_tokenizer_cls.from_pretrained.assert_called()

    def test_load_model_online_failure_falls_back_to_dummy(self):
        """When online model loading fails, fall back to dummy."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        mock_auto_model_cls = MagicMock()
        mock_auto_model_cls.from_pretrained.side_effect = OSError("no network")
        mock_auto_tokenizer_cls = MagicMock()

        with patch("app.services.bert_intent_service._import_ml_stack") as mock_import:
            mock_import.return_value = (mock_torch, mock_auto_model_cls, mock_auto_tokenizer_cls)
            clf = BertIntentClassifier(model_name="bert-base-chinese", device="cpu")
            assert clf.model is None
            assert clf.tokenizer is None

    def test_default_models_mapping(self):
        assert "bert-base-chinese" in BertIntentClassifier.DEFAULT_MODELS
        assert "chinese-bert-wwm" in BertIntentClassifier.DEFAULT_MODELS
        assert "chinese-roberta" in BertIntentClassifier.DEFAULT_MODELS

    def test_custom_model_name_not_in_defaults(self):
        """Custom model name should be used as-is."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        mock_auto_model_cls = MagicMock()
        mock_auto_tokenizer_cls = MagicMock()

        with patch("app.services.bert_intent_service._import_ml_stack") as mock_import:
            mock_import.return_value = (mock_torch, mock_auto_model_cls, mock_auto_tokenizer_cls)
            clf = BertIntentClassifier(model_name="custom-model-name", device="cpu")
            # Should call from_pretrained with "custom-model-name"
            call_args = mock_auto_tokenizer_cls.from_pretrained.call_args
            assert call_args[0][0] == "custom-model-name"


# ---------------------------------------------------------------------------
# BertIntentClassifier — predict with real model (mocked)
# ---------------------------------------------------------------------------


class TestBertIntentClassifierPredictWithModel:
    """Test predict/predict_batch when model is loaded (mocked)."""

    def _make_classifier_with_mock_model(self):
        """Create a classifier with a mocked model that returns deterministic results."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        mock_torch.no_grad.return_value.__enter__ = MagicMock(return_value=None)
        mock_torch.no_grad.return_value.__exit__ = MagicMock(return_value=None)

        mock_model = MagicMock()
        mock_output = MagicMock()
        mock_logits = MagicMock()
        mock_output.logits = mock_logits
        mock_model.return_value = mock_output

        # torch.softmax returns mock_probs
        mock_probs = MagicMock()
        mock_torch.softmax.return_value = mock_probs

        # torch.max(probs, dim=-1) returns (confidence_tensor, index_tensor)
        mock_confidence = MagicMock()
        mock_confidence.item.return_value = 0.95
        mock_idx = MagicMock()
        mock_idx.item.return_value = 0
        mock_torch.max.return_value = (mock_confidence, mock_idx)

        mock_tokenizer = MagicMock()
        mock_tokenizer.return_value = {"input_ids": MagicMock(), "attention_mask": MagicMock()}

        with patch("app.services.bert_intent_service._import_ml_stack") as mock_import:
            mock_import.return_value = (mock_torch, MagicMock(), MagicMock())
            clf = BertIntentClassifier(device="cpu", local_files_only=True)

        # Manually set model and tokenizer
        clf._torch = mock_torch
        clf.model = mock_model
        clf.tokenizer = mock_tokenizer
        return clf

    def test_predict_with_model(self):
        clf = self._make_classifier_with_mock_model()
        result = clf.predict("你好")
        assert result["model"] == "bert_intent_classifier"
        assert result["text"] == "你好"
        assert "intent" in result
        assert "confidence" in result

    def test_predict_batch_with_model(self):
        clf = self._make_classifier_with_mock_model()
        # Setup batch predict: torch.max returns (confidences, indices) where
        # confidences[i].item() and indices[i].item() are called
        mock_conf_0 = MagicMock()
        mock_conf_0.item.return_value = 0.9
        mock_conf_1 = MagicMock()
        mock_conf_1.item.return_value = 0.8
        mock_idx_0 = MagicMock()
        mock_idx_0.item.return_value = 0
        mock_idx_1 = MagicMock()
        mock_idx_1.item.return_value = 1

        mock_confidences = MagicMock()
        mock_confidences.__getitem__ = MagicMock(side_effect=[mock_conf_0, mock_conf_1])
        mock_indices = MagicMock()
        mock_indices.__getitem__ = MagicMock(side_effect=[mock_idx_0, mock_idx_1])

        clf._torch.max.return_value = (mock_confidences, mock_indices)

        results = clf.predict_batch(["你好", "开单"])
        assert len(results) == 2

    def test_is_available_true_with_model(self):
        clf = self._make_classifier_with_mock_model()
        assert clf.is_available() is True


# ---------------------------------------------------------------------------
# BertIntentService
# ---------------------------------------------------------------------------


class TestBertIntentService:
    """Test BertIntentService wrapper."""

    def test_init_creates_classifier(self):
        with patch(
            "app.services.bert_intent_service._import_ml_stack",
            side_effect=ImportError("no torch"),
        ):
            svc = BertIntentService(local_files_only=True)
            assert svc.classifier is not None
            assert svc.confidence_threshold == 0.7

    def test_recognize_with_dummy_model_and_fallback(self):
        with patch(
            "app.services.bert_intent_service._import_ml_stack",
            side_effect=ImportError("no torch"),
        ):
            svc = BertIntentService(use_fallback=True, local_files_only=True)
            result = svc.recognize("你好")
            assert "intent" in result
            assert "source" in result
            # Dummy model should trigger low confidence or bert source
            assert result["source"] in ("bert", "bert_low_confidence", "dummy")

    def test_recognize_no_fallback_unavailable(self):
        with patch(
            "app.services.bert_intent_service._import_ml_stack",
            side_effect=ImportError("no torch"),
        ):
            svc = BertIntentService(use_fallback=False, local_files_only=True)
            result = svc.recognize("你好")
            assert result["intent"] is None
            assert result["source"] == "unavailable"
            assert result["confidence"] == 0.0

    def test_recognize_with_context(self):
        with patch(
            "app.services.bert_intent_service._import_ml_stack",
            side_effect=ImportError("no torch"),
        ):
            svc = BertIntentService(use_fallback=True, local_files_only=True)
            result = svc.recognize("你好", context={"user_id": "123"})
            assert "intent" in result

    def test_recognize_batch_with_fallback(self):
        with patch(
            "app.services.bert_intent_service._import_ml_stack",
            side_effect=ImportError("no torch"),
        ):
            svc = BertIntentService(use_fallback=True, local_files_only=True)
            results = svc.recognize_batch(["你好", "开单"])
            assert len(results) == 2

    def test_recognize_batch_no_fallback_unavailable(self):
        with patch(
            "app.services.bert_intent_service._import_ml_stack",
            side_effect=ImportError("no torch"),
        ):
            svc = BertIntentService(use_fallback=False, local_files_only=True)
            results = svc.recognize_batch(["你好", "开单"])
            assert len(results) == 2
            assert all(r["intent"] is None for r in results)
            assert all(r["source"] == "unavailable" for r in results)

    def test_get_top_intents_unavailable(self):
        with patch(
            "app.services.bert_intent_service._import_ml_stack",
            side_effect=ImportError("no torch"),
        ):
            svc = BertIntentService(local_files_only=True)
            result = svc.get_top_intents("你好")
            assert result == []

    def test_get_top_intents_with_model(self):
        with patch(
            "app.services.bert_intent_service._import_ml_stack",
            side_effect=ImportError("no torch"),
        ):
            svc = BertIntentService(local_files_only=True)
            # Mock the classifier to return probs
            mock_result = {
                "intent": "greet",
                "confidence": 0.9,
                "all_probs": {"greet": 0.9, "help": 0.05, "unk": 0.05},
            }
            svc.classifier.predict = MagicMock(return_value=mock_result)
            svc.classifier.is_available = MagicMock(return_value=True)

            top_intents = svc.get_top_intents("你好", top_k=2)
            assert len(top_intents) == 2
            assert top_intents[0][0] == "greet"
            assert top_intents[0][1] == 0.9

    def test_low_confidence_triggers_fallback_recommendation(self):
        with patch(
            "app.services.bert_intent_service._import_ml_stack",
            side_effect=ImportError("no torch"),
        ):
            svc = BertIntentService(
                confidence_threshold=0.99, use_fallback=True, local_files_only=True
            )
            # Mock classifier to return low confidence
            mock_result = {
                "intent": "greet",
                "confidence": 0.5,
                "all_probs": {"greet": 0.5},
            }
            svc.classifier.predict = MagicMock(return_value=mock_result)
            svc.classifier.is_available = MagicMock(return_value=True)

            result = svc.recognize("你好")
            assert result["source"] == "bert_low_confidence"
            assert result["fallback_recommended"] is True

    def test_high_confidence_no_fallback(self):
        with patch(
            "app.services.bert_intent_service._import_ml_stack",
            side_effect=ImportError("no torch"),
        ):
            svc = BertIntentService(
                confidence_threshold=0.5, use_fallback=True, local_files_only=True
            )
            mock_result = {
                "intent": "greet",
                "confidence": 0.95,
                "all_probs": {"greet": 0.95},
            }
            svc.classifier.predict = MagicMock(return_value=mock_result)
            svc.classifier.is_available = MagicMock(return_value=True)

            result = svc.recognize("你好")
            assert result["source"] == "bert"
            assert "fallback_recommended" not in result


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------


class TestBertIntentServiceSingleton:
    """Test singleton get/reset functions."""

    def test_get_service_returns_instance(self):
        reset_bert_intent_service()
        with patch(
            "app.services.bert_intent_service._import_ml_stack",
            side_effect=ImportError("no torch"),
        ):
            svc = get_bert_intent_service(local_files_only=True)
            assert isinstance(svc, BertIntentService)
        reset_bert_intent_service()

    def test_singleton_returns_same_instance(self):
        reset_bert_intent_service()
        with patch(
            "app.services.bert_intent_service._import_ml_stack",
            side_effect=ImportError("no torch"),
        ):
            svc1 = get_bert_intent_service(local_files_only=True)
            svc2 = get_bert_intent_service(local_files_only=True)
            assert svc1 is svc2
        reset_bert_intent_service()

    def test_reset_clears_singleton(self):
        reset_bert_intent_service()
        with patch(
            "app.services.bert_intent_service._import_ml_stack",
            side_effect=ImportError("no torch"),
        ):
            svc1 = get_bert_intent_service(local_files_only=True)
            reset_bert_intent_service()
            svc2 = get_bert_intent_service(local_files_only=True)
            assert svc1 is not svc2
        reset_bert_intent_service()
