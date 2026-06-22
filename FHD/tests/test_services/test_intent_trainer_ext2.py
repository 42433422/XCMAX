"""Extended tests for app.services.intent_trainer — data loading, splitting, dataset, compute_metrics."""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

try:
    from app.services.intent_trainer import (
        HAS_YAML,
        ID_TO_LABEL,
        INTENT_LABELS,
        LABEL_TO_ID,
        IntentDataset,
        IntentExample,
        compute_metrics,
        load_training_data,
        parse_nlu_yaml,
        split_data,
    )
except ImportError:
    pytest.skip("intent_trainer dependencies unavailable", allow_module_level=True)


# ---------------------------------------------------------------------------
# IntentExample
# ---------------------------------------------------------------------------


class TestIntentExample:
    def test_create(self):
        ex = IntentExample(text="你好", label="greet")
        assert ex.text == "你好"
        assert ex.label == "greet"


# ---------------------------------------------------------------------------
# IntentDataset
# ---------------------------------------------------------------------------


class TestIntentDataset:
    def test_len(self):
        examples = [
            IntentExample(text="hi", label="greet"),
            IntentExample(text="bye", label="goodbye"),
        ]
        mock_tokenizer = MagicMock()
        mock_tokenizer.return_value = {
            "input_ids": MagicMock(squeeze=MagicMock(return_value=MagicMock())),
            "attention_mask": MagicMock(squeeze=MagicMock(return_value=MagicMock())),
        }
        ds = IntentDataset(examples, mock_tokenizer, max_length=32)
        assert len(ds) == 2

    def test_getitem_known_label(self):
        torch = pytest.importorskip("torch")

        examples = [IntentExample(text="发货", label="shipment_generate")]
        mock_tokenizer = MagicMock()
        mock_encoding = {
            "input_ids": torch.tensor([[1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1]]),
        }
        mock_tokenizer.return_value = mock_encoding
        ds = IntentDataset(examples, mock_tokenizer, max_length=32)
        item = ds[0]
        assert "labels" in item
        assert item["labels"].item() == LABEL_TO_ID["shipment_generate"]

    def test_getitem_unknown_label(self):
        torch = pytest.importorskip("torch")

        examples = [IntentExample(text="test", label="nonexistent_label")]
        mock_tokenizer = MagicMock()
        mock_encoding = {
            "input_ids": torch.tensor([[1, 2]]),
            "attention_mask": torch.tensor([[1, 1]]),
        }
        mock_tokenizer.return_value = mock_encoding
        ds = IntentDataset(examples, mock_tokenizer, max_length=32)
        item = ds[0]
        assert "labels" not in item


# ---------------------------------------------------------------------------
# parse_nlu_yaml
# ---------------------------------------------------------------------------


class TestParseNluYaml:
    def test_no_yaml_raises(self):
        if not HAS_YAML:
            with pytest.raises(ImportError, match="PyYAML"):
                parse_nlu_yaml("dummy.yml")

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_valid_yaml(self):
        import yaml

        data = {
            "nlu": [
                {
                    "intent": "greet",
                    "examples": "- 你好\n- 嗨\n- 早上好",
                },
                {
                    "intent": "goodbye",
                    "examples": "- 再见\n- 拜拜",
                },
            ]
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yml", delete=False, encoding="utf-8"
        ) as f:
            yaml.dump(data, f, allow_unicode=True)
            path = f.name
        try:
            examples = parse_nlu_yaml(path)
            assert len(examples) == 5
            assert examples[0].label == "greet"
            assert examples[0].text == "你好"
            assert examples[3].label == "goodbye"
        finally:
            os.unlink(path)

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_negation_test_renamed(self):
        import yaml

        data = {
            "nlu": [
                {
                    "intent": "negation_test",
                    "examples": "- 不需要\n- 不用了",
                },
            ]
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yml", delete=False, encoding="utf-8"
        ) as f:
            yaml.dump(data, f, allow_unicode=True)
            path = f.name
        try:
            examples = parse_nlu_yaml(path)
            assert all(e.label == "negation" for e in examples)
        finally:
            os.unlink(path)

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_empty_intent_skipped(self):
        import yaml

        data = {
            "nlu": [
                {
                    "intent": "greet",
                    "examples": "- hi\n- \n",
                },
            ]
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yml", delete=False, encoding="utf-8"
        ) as f:
            yaml.dump(data, f, allow_unicode=True)
            path = f.name
        try:
            examples = parse_nlu_yaml(path)
            # Empty lines after stripping "-" should be skipped
            assert len(examples) == 1
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# load_training_data
# ---------------------------------------------------------------------------


class TestLoadTrainingData:
    def test_json_format(self):
        data = [
            {"text": "发货", "label": "shipment_generate"},
            {"text": "你好", "label": "greet"},
        ]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(data, f, ensure_ascii=False)
            path = f.name
        try:
            examples = load_training_data(path)
            assert len(examples) == 2
            assert examples[0].text == "发货"
        finally:
            os.unlink(path)

    def test_json_missing_fields_skipped(self):
        data = [
            {"text": "发货"},  # missing label
            {"label": "greet"},  # missing text
            {"text": "你好", "label": "greet"},
        ]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(data, f, ensure_ascii=False)
            path = f.name
        try:
            examples = load_training_data(path)
            assert len(examples) == 1
        finally:
            os.unlink(path)

    def test_unsupported_format_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            load_training_data("data.csv")

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_yaml_format(self):
        import yaml

        data = {"nlu": [{"intent": "greet", "examples": "- hi"}]}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yml", delete=False, encoding="utf-8"
        ) as f:
            yaml.dump(data, f, allow_unicode=True)
            path = f.name
        try:
            examples = load_training_data(path)
            assert len(examples) == 1
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# split_data
# ---------------------------------------------------------------------------


class TestSplitData:
    def test_basic_split(self):
        examples = [IntentExample(text=f"text_{i}", label="greet") for i in range(100)]
        train, val, test = split_data(examples, train_ratio=0.8, val_ratio=0.1, test_ratio=0.1)
        assert len(train) == 80
        assert len(val) == 10
        assert len(test) == 10

    def test_total_preserved(self):
        examples = [IntentExample(text=f"t{i}", label="greet") for i in range(50)]
        train, val, test = split_data(examples)
        assert len(train) + len(val) + len(test) == 50

    def test_deterministic_with_seed(self):
        examples = [IntentExample(text=f"t{i}", label="greet") for i in range(20)]
        t1, v1, te1 = split_data(examples, seed=42)
        t2, v2, te2 = split_data(examples, seed=42)
        assert [e.text for e in t1] == [e.text for e in t2]

    def test_different_seed_different_split(self):
        examples = [IntentExample(text=f"t{i}", label="greet") for i in range(20)]
        t1, _, _ = split_data(examples, seed=42)
        t2, _, _ = split_data(examples, seed=99)
        # Very unlikely to be identical
        assert [e.text for e in t1] != [e.text for e in t2]

    def test_empty_input(self):
        train, val, test = split_data([])
        assert len(train) == 0
        assert len(val) == 0
        assert len(test) == 0


# ---------------------------------------------------------------------------
# compute_metrics
# ---------------------------------------------------------------------------


class TestComputeMetrics:
    def test_perfect_prediction(self):
        import numpy as np

        eval_pred = (np.array([[0.9, 0.1], [0.1, 0.9]]), np.array([0, 1]))
        metrics = compute_metrics(eval_pred)
        assert metrics["accuracy"] == 1.0
        assert metrics["f1"] == 1.0

    def test_imperfect_prediction(self):
        import numpy as np

        eval_pred = (np.array([[0.9, 0.1], [0.9, 0.1]]), np.array([0, 1]))
        metrics = compute_metrics(eval_pred)
        assert metrics["accuracy"] == 0.5
        assert 0.0 <= metrics["f1"] <= 1.0

    def test_all_wrong(self):
        import numpy as np

        eval_pred = (np.array([[0.1, 0.9], [0.9, 0.1]]), np.array([0, 1]))
        metrics = compute_metrics(eval_pred)
        assert metrics["accuracy"] == 0.0


# ---------------------------------------------------------------------------
# INTENT_LABELS / LABEL_TO_ID / ID_TO_LABEL
# ---------------------------------------------------------------------------


class TestIntentLabelsConstants:
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
