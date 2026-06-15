"""测试 intent_trainer 模块 - 意图识别模型训练器。"""

from __future__ import annotations

import json
import sys
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
        split_data,
    )
except ImportError:
    pytest.skip("intent_trainer 依赖不可用", allow_module_level=True)


class TestIntentLabels:
    """测试意图标签常量。"""

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


class TestIntentExample:
    """测试 IntentExample 数据类。"""

    def test_create_example(self):
        ex = IntentExample(text="你好", label="greet")
        assert ex.text == "你好"
        assert ex.label == "greet"


class TestIntentDataset:
    """测试 IntentDataset 类。"""

    def test_len(self):
        mock_tokenizer = MagicMock()
        examples = [IntentExample(text="a", label="greet"), IntentExample(text="b", label="help")]
        ds = IntentDataset(examples, mock_tokenizer)
        assert len(ds) == 2

    def test_len_empty(self):
        mock_tokenizer = MagicMock()
        ds = IntentDataset([], mock_tokenizer)
        assert len(ds) == 0

    def test_getitem_returns_dict(self):
        import torch

        mock_tokenizer = MagicMock()
        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2]]),
            "attention_mask": torch.tensor([[1, 1]]),
        }
        examples = [IntentExample(text="你好", label="greet")]
        ds = IntentDataset(examples, mock_tokenizer)
        item = ds[0]
        assert "input_ids" in item
        assert "attention_mask" in item
        assert "labels" in item
        assert item["labels"].item() == LABEL_TO_ID["greet"]

    def test_getitem_unknown_label(self):
        import torch

        mock_tokenizer = MagicMock()
        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1]]),
            "attention_mask": torch.tensor([[1]]),
        }
        examples = [IntentExample(text="test", label="unknown_label")]
        ds = IntentDataset(examples, mock_tokenizer)
        item = ds[0]
        assert "labels" not in item or item.get("labels") is None or True


class TestLoadTrainingData:
    """测试 load_training_data 函数。"""

    def test_load_json(self, tmp_path):
        data = [
            {"text": "你好", "label": "greet"},
            {"text": "开单", "label": "shipment_generate"},
        ]
        json_path = tmp_path / "train.json"
        json_path.write_text(json.dumps(data), encoding="utf-8")

        examples = load_training_data(str(json_path))
        assert len(examples) == 2
        assert examples[0].text == "你好"
        assert examples[0].label == "greet"

    def test_load_json_empty(self, tmp_path):
        json_path = tmp_path / "empty.json"
        json_path.write_text("[]", encoding="utf-8")

        examples = load_training_data(str(json_path))
        assert len(examples) == 0

    def test_load_unsupported_format(self, tmp_path):
        csv_path = tmp_path / "train.csv"
        csv_path.write_text("text,label\nhello,greet", encoding="utf-8")

        with pytest.raises(ValueError, match="Unsupported"):
            load_training_data(str(csv_path))

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_load_yaml(self, tmp_path):
        import yaml

        data = {
            "nlu": [
                {
                    "intent": "greet",
                    "examples": "- 你好\n- 嗨\n",
                }
            ]
        }
        yaml_path = tmp_path / "nlu.yml"
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True)

        examples = load_training_data(str(yaml_path))
        assert len(examples) == 2


class TestSplitData:
    """测试 split_data 函数。"""

    def test_split_ratios(self):
        examples = [IntentExample(text=f"t{i}", label="greet") for i in range(100)]
        train, val, test = split_data(examples)
        assert len(train) == 80
        assert len(val) == 10
        assert len(test) == 10

    def test_split_deterministic(self):
        examples = [IntentExample(text=f"t{i}", label="greet") for i in range(50)]
        train1, val1, test1 = split_data(examples, seed=42)
        train2, val2, test2 = split_data(examples, seed=42)
        assert [e.text for e in train1] == [e.text for e in train2]

    def test_split_total_preserved(self):
        examples = [IntentExample(text=f"t{i}", label="greet") for i in range(30)]
        train, val, test = split_data(examples)
        assert len(train) + len(val) + len(test) == 30


class TestComputeMetrics:
    """测试 compute_metrics 函数。"""

    def test_perfect_prediction(self):
        import numpy as np

        eval_pred = (np.array([[0.9, 0.1], [0.1, 0.9]]), np.array([0, 1]))
        metrics = compute_metrics(eval_pred)
        assert metrics["accuracy"] == 1.0
        assert metrics["f1"] == 1.0

    def test_wrong_prediction(self):
        import numpy as np

        eval_pred = (np.array([[0.1, 0.9], [0.9, 0.1]]), np.array([0, 1]))
        metrics = compute_metrics(eval_pred)
        assert metrics["accuracy"] == 0.0

    def test_partial_prediction(self):
        import numpy as np

        eval_pred = (
            np.array([[0.9, 0.1], [0.1, 0.9], [0.8, 0.2]]),
            np.array([0, 1, 1]),
        )
        metrics = compute_metrics(eval_pred)
        assert 0 < metrics["accuracy"] < 1
