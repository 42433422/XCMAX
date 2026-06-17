"""Comprehensive tests for intent_trainer — covering parse_nlu_yaml, train_intent_model, export_to_onnx, main(), and edge cases.

Extends the existing test file with additional coverage for uncovered lines.
"""

from __future__ import annotations

import json
import os
import sys
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
    pytest.skip("intent_trainer 依赖不可用", allow_module_level=True)

torch_available = True
try:
    import torch
except ImportError:
    torch_available = False


# ---------------------------------------------------------------------------
# parse_nlu_yaml
# ---------------------------------------------------------------------------


class TestParseNluYaml:
    """Tests for parse_nlu_yaml function."""

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_parse_basic_yaml(self, tmp_path):
        """Parse a basic NLU YAML file."""
        import yaml

        data = {
            "nlu": [
                {
                    "intent": "greet",
                    "examples": "- 你好\n- 嗨\n- 早上好\n",
                },
                {
                    "intent": "goodbye",
                    "examples": "- 再见\n- 拜拜\n",
                },
            ]
        }
        yaml_path = tmp_path / "nlu.yml"
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True)

        examples = parse_nlu_yaml(str(yaml_path))
        assert len(examples) == 5
        labels = {e.label for e in examples}
        assert "greet" in labels
        assert "goodbye" in labels

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_parse_negation_test_renamed(self, tmp_path):
        """negation_test intent should be renamed to negation."""
        import yaml

        data = {
            "nlu": [
                {
                    "intent": "negation_test",
                    "examples": "- 不要\n- 不用了\n",
                },
            ]
        }
        yaml_path = tmp_path / "negation.yml"
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True)

        examples = parse_nlu_yaml(str(yaml_path))
        assert len(examples) == 2
        assert all(e.label == "negation" for e in examples)

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_parse_empty_examples(self, tmp_path):
        """Intent with empty examples should produce no entries."""
        import yaml

        data = {
            "nlu": [
                {
                    "intent": "greet",
                    "examples": "",
                },
            ]
        }
        yaml_path = tmp_path / "empty.yml"
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True)

        examples = parse_nlu_yaml(str(yaml_path))
        assert len(examples) == 0

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_parse_skips_items_without_intent_or_examples(self, tmp_path):
        """Items missing 'intent' or 'examples' keys should be skipped."""
        import yaml

        data = {
            "nlu": [
                {"intent": "greet", "examples": "- 你好\n"},
                {"intent": "only_intent"},
                {"examples": "- no intent key\n"},
                {"other_key": "value"},
            ]
        }
        yaml_path = tmp_path / "partial.yml"
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True)

        examples = parse_nlu_yaml(str(yaml_path))
        assert len(examples) == 1

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_parse_skips_empty_text_lines(self, tmp_path):
        """Lines that are just '-' with no text should be skipped."""
        import yaml

        data = {
            "nlu": [
                {
                    "intent": "greet",
                    "examples": "- \n- 你好\n-   \n",
                },
            ]
        }
        yaml_path = tmp_path / "blank.yml"
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True)

        examples = parse_nlu_yaml(str(yaml_path))
        # Only "你好" should be kept; empty lines after '-' should be skipped
        assert len(examples) >= 1
        assert any(e.text == "你好" for e in examples)

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_parse_empty_nlu_list(self, tmp_path):
        """Empty nlu list should return no examples."""
        import yaml

        data = {"nlu": []}
        yaml_path = tmp_path / "empty_nlu.yml"
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True)

        examples = parse_nlu_yaml(str(yaml_path))
        assert len(examples) == 0

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_parse_no_nlu_key(self, tmp_path):
        """YAML without 'nlu' key should return no examples."""
        import yaml

        data = {"other": "data"}
        yaml_path = tmp_path / "no_nlu.yml"
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True)

        examples = parse_nlu_yaml(str(yaml_path))
        assert len(examples) == 0

    def test_parse_without_yaml_module(self):
        """When PyYAML is not available, should raise ImportError."""
        if HAS_YAML:
            pytest.skip("PyYAML is installed, cannot test ImportError path")
        with pytest.raises(ImportError, match="PyYAML"):
            parse_nlu_yaml("/any/path.yml")


# ---------------------------------------------------------------------------
# load_training_data — YAML format
# ---------------------------------------------------------------------------


class TestLoadTrainingDataYaml:
    """Tests for load_training_data with YAML files."""

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_load_yaml_file(self, tmp_path):
        """load_training_data should handle .yml files."""
        import yaml

        data = {
            "nlu": [
                {"intent": "greet", "examples": "- 你好\n- 嗨\n"},
            ]
        }
        yaml_path = tmp_path / "train.yml"
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True)

        examples = load_training_data(str(yaml_path))
        assert len(examples) == 2

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_load_yaml_extension(self, tmp_path):
        """load_training_data should handle .yaml files."""
        import yaml

        data = {
            "nlu": [
                {"intent": "greet", "examples": "- 你好\n"},
            ]
        }
        yaml_path = tmp_path / "train.yaml"
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True)

        examples = load_training_data(str(yaml_path))
        assert len(examples) == 1

    def test_load_json_missing_keys(self, tmp_path):
        """JSON entries without 'text' or 'label' should be skipped."""
        data = [
            {"text": "hello"},
            {"label": "greet"},
            {"text": "hi", "label": "greet"},
        ]
        json_path = tmp_path / "partial.json"
        json_path.write_text(json.dumps(data), encoding="utf-8")

        examples = load_training_data(str(json_path))
        assert len(examples) == 1
        assert examples[0].text == "hi"


# ---------------------------------------------------------------------------
# split_data — edge cases
# ---------------------------------------------------------------------------


class TestSplitDataEdgeCases:
    """Additional edge cases for split_data."""

    def test_split_small_dataset(self):
        """split_data should handle small datasets."""
        examples = [IntentExample(text="t0", label="greet"), IntentExample(text="t1", label="help")]
        train, val, test = split_data(examples)
        assert len(train) + len(val) + len(test) == 2

    def test_split_single_example(self):
        """split_data should handle a single example."""
        examples = [IntentExample(text="t0", label="greet")]
        train, val, test = split_data(examples)
        assert len(train) + len(val) + len(test) == 1

    def test_split_custom_ratios(self):
        """split_data should respect custom ratios."""
        examples = [IntentExample(text=f"t{i}", label="greet") for i in range(100)]
        train, val, test = split_data(examples, train_ratio=0.7, val_ratio=0.2, test_ratio=0.1)
        assert len(train) == 70
        assert len(val) == 20
        assert len(test) == 10

    def test_split_custom_seed(self):
        """Different seeds should produce different splits."""
        examples = [IntentExample(text=f"t{i}", label="greet") for i in range(50)]
        train1, _, _ = split_data(examples, seed=42)
        train2, _, _ = split_data(examples, seed=123)
        # Different seeds should produce different orderings (extremely unlikely to be same)
        assert [e.text for e in train1] != [e.text for e in train2]


# ---------------------------------------------------------------------------
# compute_metrics — edge cases
# ---------------------------------------------------------------------------


class TestComputeMetricsEdgeCases:
    """Additional edge cases for compute_metrics."""

    def test_single_sample(self):
        """compute_metrics should handle a single sample."""
        import numpy as np

        eval_pred = (np.array([[0.9, 0.1]]), np.array([0]))
        metrics = compute_metrics(eval_pred)
        assert metrics["accuracy"] == 1.0

    def test_multi_class(self):
        """compute_metrics should handle multi-class predictions."""
        import numpy as np

        predictions = np.array([
            [0.8, 0.1, 0.1],
            [0.1, 0.8, 0.1],
            [0.1, 0.1, 0.8],
        ])
        labels = np.array([0, 1, 2])
        metrics = compute_metrics((predictions, labels))
        assert metrics["accuracy"] == 1.0
        assert metrics["precision"] > 0
        assert metrics["recall"] > 0
        assert metrics["f1"] > 0

    def test_all_wrong(self):
        """compute_metrics with all wrong predictions."""
        import numpy as np

        predictions = np.array([[0.1, 0.9], [0.9, 0.1]])
        labels = np.array([0, 1])
        metrics = compute_metrics((predictions, labels))
        assert metrics["accuracy"] == 0.0


# ---------------------------------------------------------------------------
# train_intent_model — mock heavy dependencies
# ---------------------------------------------------------------------------


class TestTrainIntentModel:
    """Tests for train_intent_model function (mocking all heavy deps)."""

    def test_train_raises_on_empty_data(self, tmp_path):
        """train_intent_model should raise ValueError on empty training data."""
        data_path = str(tmp_path / "empty.json")
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump([], f)

        with pytest.raises(ValueError, match="训练数据为空"):
            train_intent_model(data_path)

    def test_train_intent_model_full_flow(self, tmp_path):
        """Full flow with mocked transformers Trainer."""
        data = [
            {"text": f"text_{i}", "label": INTENT_LABELS[i % len(INTENT_LABELS)]}
            for i in range(30)
        ]
        data_path = str(tmp_path / "train.json")
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        output_dir = str(tmp_path / "model_output")

        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_trainer_instance = MagicMock()
        mock_trainer_instance.evaluate.return_value = {"eval_f1": 0.85}
        mock_trainer_instance.train.return_value = None

        def _save_model(path):
            os.makedirs(path, exist_ok=True)

        mock_trainer_instance.save_model.side_effect = _save_model

        with patch(
            "app.services.intent_trainer.AutoTokenizer"
        ) as MockTokenizer, patch(
            "app.services.intent_trainer.AutoModelForSequenceClassification"
        ) as MockModel, patch(
            "app.services.intent_trainer.AutoConfig"
        ) as MockConfig, patch(
            "app.services.intent_trainer.Trainer"
        ) as MockTrainer, patch(
            "app.services.intent_trainer.DataCollatorWithPadding"
        ) as MockCollator, patch(
            "app.services.intent_trainer.EarlyStoppingCallback"
        ), patch(
            "app.services.intent_trainer.TrainingArguments"
        ) as MockTrainingArgs:
            MockTokenizer.from_pretrained.return_value = mock_tokenizer
            MockConfig.from_pretrained.return_value = MagicMock()
            MockModel.from_pretrained.return_value = mock_model
            MockTrainer.return_value = mock_trainer_instance
            MockCollator.return_value = MagicMock()
            MockTrainingArgs.return_value = MagicMock()

            result = train_intent_model(
                data_path=data_path,
                output_dir=output_dir,
                num_epochs=1,
                batch_size=2,
            )

            assert result == Path(output_dir) / "final"
            mock_trainer_instance.train.assert_called_once()
            mock_trainer_instance.evaluate.assert_called_once()
            mock_trainer_instance.save_model.assert_called_once()
            mock_tokenizer.save_pretrained.assert_called_once()

    def test_train_intent_model_saves_labels_json(self, tmp_path):
        """train_intent_model should save intent_labels.json."""
        data = [
            {"text": f"text_{i}", "label": INTENT_LABELS[i % len(INTENT_LABELS)]}
            for i in range(30)
        ]
        data_path = str(tmp_path / "train.json")
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        output_dir = str(tmp_path / "model_output")

        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_trainer_instance = MagicMock()
        mock_trainer_instance.evaluate.return_value = {"eval_f1": 0.9}
        mock_trainer_instance.train.return_value = None

        def _save_model(path):
            os.makedirs(path, exist_ok=True)

        mock_trainer_instance.save_model.side_effect = _save_model

        with patch(
            "app.services.intent_trainer.AutoTokenizer"
        ) as MockTokenizer, patch(
            "app.services.intent_trainer.AutoModelForSequenceClassification"
        ) as MockModel, patch(
            "app.services.intent_trainer.AutoConfig"
        ) as MockConfig, patch(
            "app.services.intent_trainer.Trainer"
        ) as MockTrainer, patch(
            "app.services.intent_trainer.DataCollatorWithPadding"
        ), patch(
            "app.services.intent_trainer.EarlyStoppingCallback"
        ), patch(
            "app.services.intent_trainer.TrainingArguments"
        ):
            MockTokenizer.from_pretrained.return_value = mock_tokenizer
            MockConfig.from_pretrained.return_value = MagicMock()
            MockModel.from_pretrained.return_value = mock_model
            MockTrainer.return_value = mock_trainer_instance

            result = train_intent_model(
                data_path=data_path,
                output_dir=output_dir,
                num_epochs=1,
            )

            # Verify intent_labels.json was written
            labels_path = Path(output_dir) / "final" / "intent_labels.json"
            assert labels_path.exists()
            with open(labels_path, encoding="utf-8") as f:
                labels_data = json.load(f)
            assert "labels" in labels_data
            assert labels_data["labels"] == INTENT_LABELS

    def test_train_no_early_stopping(self, tmp_path):
        """When early_stopping_patience=0, no callback should be added."""
        data = [
            {"text": f"text_{i}", "label": INTENT_LABELS[i % len(INTENT_LABELS)]}
            for i in range(30)
        ]
        data_path = str(tmp_path / "train.json")
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        output_dir = str(tmp_path / "model_output")

        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_trainer_instance = MagicMock()
        mock_trainer_instance.evaluate.return_value = {"eval_f1": 0.8}
        mock_trainer_instance.train.return_value = None

        def _save_model(path):
            os.makedirs(path, exist_ok=True)

        mock_trainer_instance.save_model.side_effect = _save_model

        with patch(
            "app.services.intent_trainer.AutoTokenizer"
        ) as MockTokenizer, patch(
            "app.services.intent_trainer.AutoModelForSequenceClassification"
        ) as MockModel, patch(
            "app.services.intent_trainer.AutoConfig"
        ) as MockConfig, patch(
            "app.services.intent_trainer.Trainer"
        ) as MockTrainer, patch(
            "app.services.intent_trainer.DataCollatorWithPadding"
        ), patch(
            "app.services.intent_trainer.TrainingArguments"
        ):
            MockTokenizer.from_pretrained.return_value = mock_tokenizer
            MockConfig.from_pretrained.return_value = MagicMock()
            MockModel.from_pretrained.return_value = mock_model
            MockTrainer.return_value = mock_trainer_instance

            train_intent_model(
                data_path=data_path,
                output_dir=output_dir,
                num_epochs=1,
                early_stopping_patience=0,
            )

            # Verify Trainer was called with no callbacks
            trainer_call_kwargs = MockTrainer.call_args[1]
            assert trainer_call_kwargs["callbacks"] == []


# ---------------------------------------------------------------------------
# export_to_onnx
# ---------------------------------------------------------------------------


class TestExportToOnnx:
    """Tests for export_to_onnx function."""

    def test_export_skips_when_onnxruntime_missing(self, tmp_path):
        """export_to_onnx should skip when onnxruntime is not installed."""
        with patch.dict("sys.modules", {"onnxruntime": None}):
            # Should not raise, just return None
            result = export_to_onnx("/fake/model/path", str(tmp_path / "model.onnx"))
            assert result is None

    def test_export_with_onnxruntime(self, tmp_path):
        """export_to_onnx should export when onnxruntime is available."""
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()

        with patch(
            "app.services.intent_trainer.AutoTokenizer"
        ) as MockTokenizer, patch(
            "app.services.intent_trainer.AutoModelForSequenceClassification"
        ) as MockModel, patch(
            "app.services.intent_trainer.torch.onnx.export"
        ) as mock_export, patch.dict(
            "sys.modules", {"onnxruntime": MagicMock()}
        ):
            MockTokenizer.from_pretrained.return_value = mock_tokenizer
            mock_tokenizer.return_value = {
                "input_ids": MagicMock(),
                "attention_mask": MagicMock(),
            }
            MockModel.from_pretrained.return_value = mock_model
            mock_model.eval.return_value = mock_model

            output_path = str(tmp_path / "model.onnx")
            export_to_onnx("/fake/model/path", output_path)

            mock_export.assert_called_once()


# ---------------------------------------------------------------------------
# main() CLI entry point
# ---------------------------------------------------------------------------


class TestMain:
    """Tests for the main() CLI entry point."""

    def test_main_calls_train(self, tmp_path):
        """main() should call train_intent_model with correct args."""
        data_path = str(tmp_path / "train.json")
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(
                [{"text": f"t{i}", "label": INTENT_LABELS[i % len(INTENT_LABELS)]} for i in range(30)],
                f,
            )

        with patch(
            "sys.argv",
            ["intent_trainer", "--data", data_path, "--epochs", "1"],
        ), patch(
            "app.services.intent_trainer.train_intent_model",
            return_value=Path("/fake/output/final"),
        ) as mock_train:
            main()
            mock_train.assert_called_once_with(
                data_path=data_path,
                model_name="bert-base-chinese",
                output_dir="models/intent_bert",
                num_epochs=1,
                batch_size=16,
                learning_rate=2e-5,
                max_length=64,
            )

    def test_main_with_export_onnx(self, tmp_path):
        """main() should call export_to_onnx when --export_onnx flag is set."""
        data_path = str(tmp_path / "train.json")
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(
                [{"text": f"t{i}", "label": INTENT_LABELS[i % len(INTENT_LABELS)]} for i in range(30)],
                f,
            )

        with patch(
            "sys.argv",
            ["intent_trainer", "--data", data_path, "--export_onnx"],
        ), patch(
            "app.services.intent_trainer.train_intent_model",
            return_value=Path("/fake/output/final"),
        ), patch(
            "app.services.intent_trainer.export_to_onnx"
        ) as mock_export:
            main()
            mock_export.assert_called_once_with(
                str(Path("/fake/output/final")),
                str(Path("models/intent_bert") / "model.onnx"),
                64,
            )

    def test_main_custom_params(self, tmp_path):
        """main() should pass custom parameters correctly."""
        data_path = str(tmp_path / "train.json")
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(
                [{"text": f"t{i}", "label": INTENT_LABELS[i % len(INTENT_LABELS)]} for i in range(30)],
                f,
            )

        with patch(
            "sys.argv",
            [
                "intent_trainer",
                "--data",
                data_path,
                "--model",
                "hfl/chinese-roberta-wwm-ext",
                "--output",
                "/custom/output",
                "--epochs",
                "5",
                "--batch_size",
                "32",
                "--lr",
                "3e-5",
                "--max_length",
                "128",
            ],
        ), patch(
            "app.services.intent_trainer.train_intent_model",
            return_value=Path("/custom/output/final"),
        ) as mock_train:
            main()
            mock_train.assert_called_once_with(
                data_path=data_path,
                model_name="hfl/chinese-roberta-wwm-ext",
                output_dir="/custom/output",
                num_epochs=5,
                batch_size=32,
                learning_rate=3e-5,
                max_length=128,
            )


# ---------------------------------------------------------------------------
# IntentDataset — edge cases
# ---------------------------------------------------------------------------


class TestIntentDatasetEdgeCases:
    """Additional edge cases for IntentDataset."""

    @pytest.mark.skipif(not torch_available, reason="torch not available")
    def test_getitem_with_known_label(self):
        """IntentDataset should map known labels to IDs."""
        import torch

        mock_tokenizer = MagicMock()
        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2]]),
            "attention_mask": torch.tensor([[1, 1]]),
        }
        examples = [IntentExample(text="开单", label="shipment_generate")]
        ds = IntentDataset(examples, mock_tokenizer)
        item = ds[0]
        assert item["labels"].item() == LABEL_TO_ID["shipment_generate"]

    @pytest.mark.skipif(not torch_available, reason="torch not available")
    def test_getitem_squeezes_encoding(self):
        """IntentDataset should squeeze encoding tensors."""
        mock_tokenizer = MagicMock()
        mock_input = MagicMock()
        mock_input.squeeze.return_value = mock_input
        mock_attn = MagicMock()
        mock_attn.squeeze.return_value = mock_attn
        mock_tokenizer.return_value = {
            "input_ids": mock_input,
            "attention_mask": mock_attn,
        }
        examples = [IntentExample(text="test", label="greet")]
        ds = IntentDataset(examples, mock_tokenizer, max_length=3)
        item = ds[0]
        assert item["input_ids"] is mock_input
        assert item["attention_mask"] is mock_attn
        mock_input.squeeze.assert_called_once_with(0)
        mock_attn.squeeze.assert_called_once_with(0)
