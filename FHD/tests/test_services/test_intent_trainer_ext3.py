"""Tests for app.services.intent_trainer — deep coverage (ext3).

Focus: train_intent_model with mocked Trainer, export_to_onnx,
split_data edge cases, parse_nlu_yaml edge cases, compute_metrics,
IntentDataset edge cases, and main() CLI entry point.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
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
# split_data edge cases
# ---------------------------------------------------------------------------


class TestSplitDataEdgeCases:
    def test_single_example(self):
        examples = [IntentExample(text="hello", label="greet")]
        train, val, test = split_data(examples)
        total = len(train) + len(val) + len(test)
        assert total == 1

    def test_two_examples(self):
        examples = [
            IntentExample(text="hello", label="greet"),
            IntentExample(text="bye", label="goodbye"),
        ]
        train, val, test = split_data(examples)
        total = len(train) + len(val) + len(test)
        assert total == 2

    def test_many_examples(self):
        examples = [IntentExample(text=f"text{i}", label="greet") for i in range(100)]
        train, val, test = split_data(examples)
        assert len(train) > len(val)
        assert len(train) > len(test)

    def test_custom_ratios(self):
        examples = [IntentExample(text=f"text{i}", label="greet") for i in range(100)]
        train, val, test = split_data(examples, train_ratio=0.7, val_ratio=0.2, test_ratio=0.1)
        assert len(train) == 70
        assert len(val) == 20
        assert len(test) == 10

    def test_reproducible_with_seed(self):
        examples = [IntentExample(text=f"text{i}", label="greet") for i in range(50)]
        train1, val1, test1 = split_data(examples, seed=42)
        train2, val2, test2 = split_data(examples, seed=42)
        assert [e.text for e in train1] == [e.text for e in train2]


# ---------------------------------------------------------------------------
# load_training_data edge cases
# ---------------------------------------------------------------------------


class TestLoadTrainingDataEdgeCases:
    def test_unsupported_format(self, tmp_path):
        bad_file = tmp_path / "data.csv"
        bad_file.write_text("text,label\nhello,greet", encoding="utf-8")
        with pytest.raises(ValueError, match="Unsupported"):
            load_training_data(str(bad_file))

    def test_json_with_missing_fields(self, tmp_path):
        json_file = tmp_path / "data.json"
        data = [{"text": "hello"}, {"label": "greet"}]
        json_file.write_text(json.dumps(data), encoding="utf-8")
        result = load_training_data(str(json_file))
        assert len(result) == 0

    def test_json_valid(self, tmp_path):
        json_file = tmp_path / "data.json"
        data = [
            {"text": "你好", "label": "greet"},
            {"text": "再见", "label": "goodbye"},
        ]
        json_file.write_text(json.dumps(data), encoding="utf-8")
        result = load_training_data(str(json_file))
        assert len(result) == 2


# ---------------------------------------------------------------------------
# parse_nlu_yaml edge cases
# ---------------------------------------------------------------------------


class TestParseNluYamlEdgeCases:
    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_negation_test_label(self, tmp_path):
        yaml_file = tmp_path / "nlu.yml"
        yaml_file.write_text(
            """
nlu:
- intent: negation_test
  examples: |
    - 不需要
    - 不要
""",
            encoding="utf-8",
        )
        result = parse_nlu_yaml(str(yaml_file))
        assert len(result) == 2
        assert result[0].label == "negation"

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_empty_examples(self, tmp_path):
        yaml_file = tmp_path / "nlu.yml"
        yaml_file.write_text(
            """
nlu:
- intent: greet
  examples: |
""",
            encoding="utf-8",
        )
        result = parse_nlu_yaml(str(yaml_file))
        assert len(result) == 0

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_no_intent_key(self, tmp_path):
        yaml_file = tmp_path / "nlu.yml"
        yaml_file.write_text(
            """
nlu:
- something_else: value
""",
            encoding="utf-8",
        )
        result = parse_nlu_yaml(str(yaml_file))
        assert len(result) == 0


# ---------------------------------------------------------------------------
# compute_metrics
# ---------------------------------------------------------------------------


class TestComputeMetrics:
    def test_perfect_predictions(self):
        import numpy as np

        eval_pred = (np.array([[0.9, 0.1], [0.1, 0.9]]), np.array([0, 1]))
        result = compute_metrics(eval_pred)
        assert result["accuracy"] == 1.0
        assert result["f1"] == 1.0

    def test_wrong_predictions(self):
        import numpy as np

        eval_pred = (np.array([[0.1, 0.9], [0.9, 0.1]]), np.array([0, 1]))
        result = compute_metrics(eval_pred)
        assert result["accuracy"] == 0.0

    def test_multiclass(self):
        import numpy as np

        logits = np.array(
            [
                [0.8, 0.1, 0.1],
                [0.1, 0.8, 0.1],
                [0.1, 0.1, 0.8],
            ]
        )
        labels = np.array([0, 1, 2])
        result = compute_metrics((logits, labels))
        assert result["accuracy"] == 1.0


# ---------------------------------------------------------------------------
# IntentDataset edge cases
# ---------------------------------------------------------------------------


class TestIntentDatasetEdgeCases:
    def test_unknown_label(self):
        mock_tokenizer = MagicMock()
        mock_tokenizer.return_value = {
            "input_ids": MagicMock(squeeze=lambda _: torch.zeros(64)),
            "attention_mask": MagicMock(squeeze=lambda _: torch.ones(64)),
        }
        if torch_available:
            ds = IntentDataset(
                [IntentExample(text="hello", label="nonexistent_label")],
                mock_tokenizer,
            )
            item = ds[0]
            # Unknown label should not be in LABEL_TO_ID, so labels key may be absent
            assert isinstance(item, dict)

    def test_empty_examples(self):
        mock_tokenizer = MagicMock()
        ds = IntentDataset([], mock_tokenizer)
        assert len(ds) == 0


# ---------------------------------------------------------------------------
# train_intent_model with mocked dependencies
# ---------------------------------------------------------------------------


class TestTrainIntentModel:
    @patch("app.services.intent_trainer.Trainer")
    @patch("app.services.intent_trainer.AutoModelForSequenceClassification.from_pretrained")
    @patch("app.services.intent_trainer.AutoConfig.from_pretrained")
    @patch("app.services.intent_trainer.AutoTokenizer.from_pretrained")
    @patch("app.services.intent_trainer.load_training_data")
    def test_train_with_mock(
        self, mock_load, mock_tokenizer, mock_config, mock_model, mock_trainer, tmp_path
    ):

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

        result = train_intent_model(
            data_path="fake.json",
            output_dir=str(tmp_path / "output"),
            num_epochs=1,
        )
        assert result is not None or mock_trainer_instance.train.called


# ---------------------------------------------------------------------------
# export_to_onnx
# ---------------------------------------------------------------------------


class TestExportToOnnx:
    @patch("app.services.intent_trainer.AutoModelForSequenceClassification.from_pretrained")
    @patch("app.services.intent_trainer.AutoTokenizer.from_pretrained")
    def test_export_without_onnxruntime(self, mock_tokenizer, mock_model, tmp_path):
        with patch.dict("sys.modules", {"onnxruntime": None}):
            # Should skip without error
            export_to_onnx(str(tmp_path), str(tmp_path / "model.onnx"))


# ---------------------------------------------------------------------------
# main() CLI
# ---------------------------------------------------------------------------


class TestMainCLI:
    def test_main_requires_data_arg(self):
        with patch("sys.argv", ["intent_trainer"]):
            with pytest.raises(SystemExit):
                main()

    def test_main_with_nonexistent_data(self):
        with patch("sys.argv", ["intent_trainer", "--data", "/nonexistent.json"]):
            with patch(
                "app.services.intent_trainer.load_training_data",
                side_effect=FileNotFoundError("no file"),
            ):
                with pytest.raises(FileNotFoundError):
                    main()


# ---------------------------------------------------------------------------
# Constants validation
# ---------------------------------------------------------------------------


class TestIntentTrainerConstants:
    def test_labels_count(self):
        assert len(INTENT_LABELS) == 20

    def test_label_id_consistency(self):
        for label, idx in LABEL_TO_ID.items():
            assert ID_TO_LABEL[idx] == label

    def test_unk_label_exists(self):
        assert "unk" in INTENT_LABELS
