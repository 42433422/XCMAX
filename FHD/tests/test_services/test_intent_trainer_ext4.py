"""Tests for app.services.intent_trainer — extended coverage (ext4).

Focus: parse_nlu_yaml with various YAML structures, load_training_data with
JSON list of dicts, IntentDataset.__getitem__ with valid label, train_intent_model
error path (empty data), export_to_onnx with onnxruntime available,
compute_metrics with edge cases, main() with --export_onnx flag.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

try:
    from app.services.intent_trainer import (
        HAS_TORCH,
        HAS_TRANSFORMERS,
        HAS_YAML,
        ID_TO_LABEL,
        INTENT_LABELS,
        LABEL_TO_ID,
        IntentDataset,
        IntentExample,
        compute_metrics,
        export_to_onnx,
        load_training_data,
        main,
        parse_nlu_yaml,
        split_data,
        train_intent_model,
    )
except ImportError:
    pytest.skip("intent_trainer dependencies unavailable", allow_module_level=True)

torch_available = True
try:
    import torch
except ImportError:
    torch_available = False


# ---------------------------------------------------------------------------
# parse_nlu_yaml — additional edge cases
# ---------------------------------------------------------------------------


class TestParseNluYamlMore:
    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_multiple_intents(self, tmp_path):
        yaml_file = tmp_path / "nlu.yml"
        yaml_file.write_text(
            """
nlu:
- intent: greet
  examples: |
    - 你好
    - 嗨
- intent: goodbye
  examples: |
    - 再见
    - 拜拜
""",
            encoding="utf-8",
        )
        result = parse_nlu_yaml(str(yaml_file))
        assert len(result) == 4
        labels = {r.label for r in result}
        assert labels == {"greet", "goodbye"}

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_intent_without_examples_key(self, tmp_path):
        yaml_file = tmp_path / "nlu.yml"
        yaml_file.write_text(
            """
nlu:
- intent: greet
- intent: goodbye
  examples: |
    - 再见
""",
            encoding="utf-8",
        )
        result = parse_nlu_yaml(str(yaml_file))
        assert len(result) == 1
        assert result[0].label == "goodbye"

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_examples_with_only_dashes(self, tmp_path):
        yaml_file = tmp_path / "nlu.yml"
        yaml_file.write_text(
            """
nlu:
- intent: greet
  examples: |
    - 你好
    -
    - 嗨
""",
            encoding="utf-8",
        )
        result = parse_nlu_yaml(str(yaml_file))
        # Empty text after "-" is skipped
        assert len(result) == 2

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_no_nlu_key(self, tmp_path):
        yaml_file = tmp_path / "nlu.yml"
        yaml_file.write_text(
            """
other_key: value
""",
            encoding="utf-8",
        )
        result = parse_nlu_yaml(str(yaml_file))
        assert len(result) == 0

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_empty_nlu_list(self, tmp_path):
        yaml_file = tmp_path / "nlu.yml"
        yaml_file.write_text(
            """
nlu: []
""",
            encoding="utf-8",
        )
        result = parse_nlu_yaml(str(yaml_file))
        assert len(result) == 0


# ---------------------------------------------------------------------------
# load_training_data — YAML extension variants
# ---------------------------------------------------------------------------


class TestLoadTrainingDataYamlExt:
    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_yaml_extension(self, tmp_path):
        yaml_file = tmp_path / "data.yaml"
        yaml_file.write_text(
            """
nlu:
- intent: greet
  examples: |
    - 你好
""",
            encoding="utf-8",
        )
        result = load_training_data(str(yaml_file))
        assert len(result) == 1
        assert result[0].label == "greet"

    def test_empty_json_list(self, tmp_path):
        json_file = tmp_path / "data.json"
        json_file.write_text("[]", encoding="utf-8")
        result = load_training_data(str(json_file))
        assert len(result) == 0

    def test_json_with_extra_fields(self, tmp_path):
        json_file = tmp_path / "data.json"
        data = [
            {"text": "你好", "label": "greet", "extra": "ignored"},
            {"text": "再见", "label": "goodbye", "metadata": {"x": 1}},
        ]
        json_file.write_text(json.dumps(data), encoding="utf-8")
        result = load_training_data(str(json_file))
        assert len(result) == 2
        assert result[0].text == "你好"


# ---------------------------------------------------------------------------
# IntentDataset.__getitem__ with valid label
# ---------------------------------------------------------------------------


class TestIntentDatasetGetitemValid:
    @pytest.mark.skipif(not torch_available, reason="torch not available")
    def test_getitem_with_valid_label(self):
        mock_tokenizer = MagicMock()
        mock_input = MagicMock()
        mock_input.squeeze.return_value = torch.zeros(64)
        mock_attn = MagicMock()
        mock_attn.squeeze.return_value = torch.ones(64)
        mock_tokenizer.return_value = {
            "input_ids": mock_input,
            "attention_mask": mock_attn,
        }

        ds = IntentDataset(
            [IntentExample(text="hello", label="greet")],
            mock_tokenizer,
            max_length=64,
        )
        item = ds[0]
        assert "input_ids" in item
        assert "attention_mask" in item
        assert "labels" in item
        assert item["labels"].item() == LABEL_TO_ID["greet"]

    @pytest.mark.skipif(not torch_available, reason="torch not available")
    def test_getitem_with_unk_label(self):
        mock_tokenizer = MagicMock()
        mock_input = MagicMock()
        mock_input.squeeze.return_value = torch.zeros(64)
        mock_attn = MagicMock()
        mock_attn.squeeze.return_value = torch.ones(64)
        mock_tokenizer.return_value = {
            "input_ids": mock_input,
            "attention_mask": mock_attn,
        }

        ds = IntentDataset(
            [IntentExample(text="hello", label="unk")],
            mock_tokenizer,
        )
        item = ds[0]
        assert item["labels"].item() == LABEL_TO_ID["unk"]


# ---------------------------------------------------------------------------
# train_intent_model — error paths
# ---------------------------------------------------------------------------


class TestTrainIntentModelErrors:
    def test_empty_training_data_raises(self, tmp_path):
        """Empty training data should raise ValueError."""
        with patch("app.services.intent_trainer.load_training_data", return_value=[]):
            with pytest.raises(ValueError, match="训练数据为空"):
                train_intent_model(data_path="fake.json", output_dir=str(tmp_path / "out"))

    @pytest.mark.skipif(
        not HAS_TRANSFORMERS, reason="transformers 未安装（重型 ML 依赖，CI 默认不装）"
    )
    @patch("app.services.intent_trainer.Trainer")
    @patch("app.services.intent_trainer.AutoModelForSequenceClassification.from_pretrained")
    @patch("app.services.intent_trainer.AutoConfig.from_pretrained")
    @patch("app.services.intent_trainer.AutoTokenizer.from_pretrained")
    @patch("app.services.intent_trainer.load_training_data")
    def test_train_with_early_stopping_disabled(
        self, mock_load, mock_tokenizer, mock_config, mock_model, mock_trainer, tmp_path
    ):
        """When early_stopping_patience=0, no EarlyStoppingCallback is added."""
        import os

        mock_load.return_value = [IntentExample(text=f"t{i}", label="greet") for i in range(20)]
        mock_tokenizer.return_value = MagicMock()
        mock_config.return_value = MagicMock()
        mock_model.return_value = MagicMock()
        mock_trainer_instance = MagicMock()
        mock_trainer_instance.evaluate.return_value = {"eval_loss": 0.5}
        mock_trainer_instance.save_model = MagicMock(
            side_effect=lambda path: os.makedirs(path, exist_ok=True)
        )
        mock_trainer.return_value = mock_trainer_instance

        train_intent_model(
            data_path="fake.json",
            output_dir=str(tmp_path / "output"),
            num_epochs=1,
            early_stopping_patience=0,
        )
        mock_trainer_instance.train.assert_called_once()


# ---------------------------------------------------------------------------
# export_to_onnx — with onnxruntime available
# ---------------------------------------------------------------------------


class TestExportToOnnxWithRuntime:
    @pytest.mark.skipif(
        not (HAS_TORCH and HAS_TRANSFORMERS),
        reason="torch+transformers 未安装（重型 ML 依赖，CI 默认不装）",
    )
    @patch("app.services.intent_trainer.AutoModelForSequenceClassification.from_pretrained")
    @patch("app.services.intent_trainer.AutoTokenizer.from_pretrained")
    @patch("app.services.intent_trainer.torch.onnx.export")
    def test_export_with_onnxruntime(self, mock_onnx_export, mock_tokenizer, mock_model, tmp_path):
        """When onnxruntime is importable, export proceeds."""
        # Make onnxruntime importable
        import sys

        fake_module = MagicMock()
        with patch.dict(sys.modules, {"onnxruntime": fake_module}):
            mock_tokenizer.return_value = MagicMock()
            mock_model.return_value = MagicMock()

            export_to_onnx(str(tmp_path), str(tmp_path / "model.onnx"))

            mock_onnx_export.assert_called_once()


# ---------------------------------------------------------------------------
# compute_metrics — edge cases
# ---------------------------------------------------------------------------


class TestComputeMetricsEdgeCases:
    def test_single_class(self):
        import numpy as np

        logits = np.array([[0.9, 0.1], [0.8, 0.2]])
        labels = np.array([0, 0])
        result = compute_metrics((logits, labels))
        assert result["accuracy"] == 1.0
        assert "precision" in result
        assert "recall" in result
        assert "f1" in result

    def test_all_wrong(self):
        import numpy as np

        logits = np.array([[0.1, 0.9], [0.9, 0.1]])
        labels = np.array([0, 1])
        result = compute_metrics((logits, labels))
        assert result["accuracy"] == 0.0


# ---------------------------------------------------------------------------
# main() CLI — with --export_onnx
# ---------------------------------------------------------------------------


class TestMainCLIWithOnnx:
    def test_main_with_export_onnx_flag(self, tmp_path):
        """main() with --export_onnx should call export_to_onnx after training."""
        with patch(
            "sys.argv",
            [
                "intent_trainer",
                "--data",
                "fake.json",
                "--epochs",
                "1",
                "--export_onnx",
            ],
        ):
            with (
                patch("app.services.intent_trainer.train_intent_model") as mock_train,
                patch("app.services.intent_trainer.export_to_onnx") as mock_export,
            ):
                mock_train.return_value = str(tmp_path / "final")

                main()

                mock_train.assert_called_once()
                mock_export.assert_called_once()

    def test_main_without_export_onnx_flag(self, tmp_path):
        """main() without --export_onnx should NOT call export_to_onnx."""
        with patch(
            "sys.argv",
            [
                "intent_trainer",
                "--data",
                "fake.json",
                "--epochs",
                "1",
            ],
        ):
            with (
                patch("app.services.intent_trainer.train_intent_model") as mock_train,
                patch("app.services.intent_trainer.export_to_onnx") as mock_export,
            ):
                mock_train.return_value = str(tmp_path / "final")

                main()

                mock_train.assert_called_once()
                mock_export.assert_not_called()


# ---------------------------------------------------------------------------
# split_data — additional edge cases
# ---------------------------------------------------------------------------


class TestSplitDataMore:
    def test_zero_examples(self):
        train, val, test = split_data([])
        assert len(train) == 0
        assert len(val) == 0
        assert len(test) == 0

    def test_three_examples(self):
        examples = [IntentExample(text=f"text{i}", label="greet") for i in range(3)]
        train, val, test = split_data(examples)
        total = len(train) + len(val) + len(test)
        assert total == 3

    def test_custom_seed_different_result(self):
        examples = [IntentExample(text=f"text{i}", label="greet") for i in range(50)]
        train1, _, _ = split_data(examples, seed=42)
        train2, _, _ = split_data(examples, seed=99)
        # Different seeds should (very likely) produce different orders
        assert [e.text for e in train1] != [e.text for e in train2]


# ---------------------------------------------------------------------------
# Constants validation — additional
# ---------------------------------------------------------------------------


class TestIntentTrainerConstantsExtra:
    def test_label_count_is_20(self):
        assert len(INTENT_LABELS) == 20

    def test_id_to_label_keys_are_ints(self):
        for i, label in enumerate(INTENT_LABELS):
            assert ID_TO_LABEL[i] == label

    def test_label_to_id_keys_are_strings(self):
        for label in INTENT_LABELS:
            assert label in LABEL_TO_ID

    def test_first_label_shipment_generate(self):
        assert INTENT_LABELS[0] == "shipment_generate"

    def test_has_yaml_is_bool(self):
        assert isinstance(HAS_YAML, bool)
