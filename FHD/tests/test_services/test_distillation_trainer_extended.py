"""Comprehensive tests for distillation_trainer — covering main(), train() branches, and edge cases.

Extends the existing test file with additional coverage for uncovered lines.
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

try:
    from app.services.distillation_trainer import (
        CHECKPOINT_DIR,
        ID_TO_LABEL,
        INTENT_LABELS,
        LABEL_TO_ID,
        LOG_DIR,
        DistillationDataset,
        DistillationTrainer,
        main,
    )
except ImportError:
    pytest.skip("distillation_trainer 依赖不可用", allow_module_level=True)

torch_available = True
try:
    import torch
except ImportError:
    torch_available = False


# ---------------------------------------------------------------------------
# main() CLI entry point
# ---------------------------------------------------------------------------


class TestMain:
    """Tests for the main() CLI entry point."""

    def test_main_data_not_exist(self, tmp_path):
        """main() should log error when data file doesn't exist."""
        with patch("sys.argv", ["distillation_trainer", "--data", "/nonexistent/data.jsonl"]):
            # main() returns None when data doesn't exist
            result = main()
            assert result is None

    def test_main_with_valid_data(self, tmp_path):
        """main() should run trainer when data exists."""
        data_path = str(tmp_path / "train.jsonl")
        with open(data_path, "w", encoding="utf-8") as f:
            for label_name in INTENT_LABELS[:5]:
                for i in range(5):
                    f.write(
                        json.dumps(
                            {"text": f"text_{label_name}_{i}", "label": label_name},
                            ensure_ascii=False,
                        )
                        + "\n"
                    )

        mock_trainer_instance = MagicMock()
        with (
            patch(
                "app.services.distillation_trainer.DistillationTrainer",
                return_value=mock_trainer_instance,
            ) as MockTrainer,
            patch(
                "sys.argv",
                ["distillation_trainer", "--data", data_path, "--epochs", "1"],
            ),
        ):
            main()
            MockTrainer.assert_called_once()
            mock_trainer_instance.train.assert_called_once()

    def test_main_default_data_path(self, tmp_path):
        """main() uses default data path when --data not provided."""
        with (
            patch(
                "app.services.distillation_trainer.get_distillation_training_data_path",
                return_value="/nonexistent/default.jsonl",
            ),
            patch("sys.argv", ["distillation_trainer"]),
        ):
            result = main()
            assert result is None

    def test_main_custom_output_dir(self, tmp_path):
        """main() passes custom output dir."""
        data_path = str(tmp_path / "train.jsonl")
        with open(data_path, "w", encoding="utf-8") as f:
            for i in range(15):
                f.write(
                    json.dumps(
                        {"text": f"t{i}", "label": INTENT_LABELS[i % len(INTENT_LABELS)]},
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        output_dir = str(tmp_path / "custom_output")
        mock_trainer_instance = MagicMock()
        with (
            patch(
                "app.services.distillation_trainer.DistillationTrainer",
                return_value=mock_trainer_instance,
            ),
            patch(
                "sys.argv",
                ["distillation_trainer", "--data", data_path, "--output", output_dir],
            ),
        ):
            main()
            mock_trainer_instance.train.assert_called_once_with(
                data_path=data_path, output_dir=output_dir
            )

    def test_main_custom_hyperparams(self, tmp_path):
        """main() passes custom hyperparameters to DistillationTrainer."""
        data_path = str(tmp_path / "train.jsonl")
        with open(data_path, "w", encoding="utf-8") as f:
            for i in range(15):
                f.write(
                    json.dumps(
                        {"text": f"t{i}", "label": INTENT_LABELS[i % len(INTENT_LABELS)]},
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        mock_trainer_instance = MagicMock()
        with (
            patch(
                "app.services.distillation_trainer.DistillationTrainer",
                return_value=mock_trainer_instance,
            ) as MockTrainer,
            patch(
                "sys.argv",
                [
                    "distillation_trainer",
                    "--data",
                    data_path,
                    "--model",
                    "bert-base-chinese",
                    "--epochs",
                    "5",
                    "--batch_size",
                    "32",
                    "--lr",
                    "3e-5",
                    "--max_length",
                    "128",
                ],
            ),
        ):
            main()
            MockTrainer.assert_called_once_with(
                model_name="bert-base-chinese",
                max_length=128,
                learning_rate=3e-5,
                batch_size=32,
                epochs=5,
            )


# ---------------------------------------------------------------------------
# DistillationTrainer.load_data — edge cases
# ---------------------------------------------------------------------------


class TestDistillationTrainerLoadDataEdgeCases:
    """Additional edge case tests for load_data."""

    def test_load_jsonl_with_empty_text(self, tmp_path):
        """JSONL entries with empty text should still be loaded."""
        trainer = DistillationTrainer(device="cpu")
        data_path = str(tmp_path / "empty_text.jsonl")
        with open(data_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"text": "", "label": "greet"}, ensure_ascii=False) + "\n")
            f.write(json.dumps({"label": "greet"}, ensure_ascii=False) + "\n")

        texts, labels = trainer.load_data(data_path)
        assert len(texts) == 2
        assert texts[0] == ""
        assert texts[1] == ""

    def test_load_jsonl_mixed_valid_invalid_labels(self, tmp_path):
        """Only entries with valid labels should be loaded."""
        trainer = DistillationTrainer(device="cpu")
        data_path = str(tmp_path / "mixed.jsonl")
        with open(data_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"text": "hello", "label": "greet"}, ensure_ascii=False) + "\n")
            f.write(
                json.dumps({"text": "bad", "label": "invalid_intent"}, ensure_ascii=False) + "\n"
            )
            f.write(json.dumps({"text": "bye", "label": "goodbye"}, ensure_ascii=False) + "\n")

        texts, labels = trainer.load_data(data_path)
        assert len(texts) == 2
        assert "hello" in texts
        assert "bye" in texts

    def test_load_tsv_with_extra_columns(self, tmp_path):
        """TSV with extra columns should still parse first two columns."""
        trainer = DistillationTrainer(device="cpu")
        data_path = str(tmp_path / "extra.tsv")
        with open(data_path, "w", encoding="utf-8") as f:
            f.write("text\tlabel\tscore\n")
            f.write("hello\tgreet\t0.9\n")

        texts, labels = trainer.load_data(data_path)
        assert len(texts) == 1
        assert texts[0] == "hello"

    def test_load_tsv_empty_lines(self, tmp_path):
        """TSV with empty lines should be handled gracefully."""
        trainer = DistillationTrainer(device="cpu")
        data_path = str(tmp_path / "empty_lines.tsv")
        with open(data_path, "w", encoding="utf-8") as f:
            f.write("text\tlabel\n")
            f.write("\n")
            f.write("hello\tgreet\n")

        texts, labels = trainer.load_data(data_path)
        assert len(texts) == 1

    def test_load_jsonl_all_unknown_labels(self, tmp_path):
        """All entries with unknown labels should result in empty data."""
        trainer = DistillationTrainer(device="cpu")
        data_path = str(tmp_path / "all_unknown.jsonl")
        with open(data_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"text": "a", "label": "unknown1"}, ensure_ascii=False) + "\n")
            f.write(json.dumps({"text": "b", "label": "unknown2"}, ensure_ascii=False) + "\n")

        texts, labels = trainer.load_data(data_path)
        assert len(texts) == 0


# ---------------------------------------------------------------------------
# DistillationTrainer.train — additional branches
# ---------------------------------------------------------------------------


class TestDistillationTrainerTrainBranches:
    """Additional branch coverage for the train() method."""

    def test_train_best_accuracy_updates(self, tmp_path):
        """train() should update best_accuracy when val_accuracy improves."""
        trainer = DistillationTrainer(device="cpu", epochs=2, batch_size=2)

        data_path = str(tmp_path / "train.jsonl")
        with open(data_path, "w", encoding="utf-8") as f:
            for label_name in INTENT_LABELS[:5]:
                for i in range(5):
                    f.write(
                        json.dumps(
                            {"text": f"text_{label_name}_{i}", "label": label_name},
                            ensure_ascii=False,
                        )
                        + "\n"
                    )

        log_dir = str(tmp_path / "logs")
        ckpt_dir = str(tmp_path / "ckpt")
        os.makedirs(log_dir, exist_ok=True)
        os.makedirs(ckpt_dir, exist_ok=True)

        trainer.load_data = MagicMock(return_value=(["a"] * 25, [i % 5 for i in range(25)]))
        trainer.prepare_data = MagicMock()
        # train() uses self.model.parameters() for AdamW; set up a mock model.
        trainer.model = MagicMock()
        trainer.model.parameters.return_value = iter([MagicMock()])
        trainer.train_loader = [MagicMock()]
        trainer.val_loader = [MagicMock()]

        # First epoch: lower accuracy, second: higher
        trainer.train_epoch = MagicMock(side_effect=[(0.5, 0.7), (0.3, 0.9)])
        trainer.evaluate = MagicMock(
            side_effect=[
                {"val_loss": 0.4, "val_accuracy": 0.7, "preds": [0, 1], "labels": [0, 1]},
                {"val_loss": 0.2, "val_accuracy": 0.9, "preds": [0, 1], "labels": [0, 1]},
            ]
        )
        trainer.save_checkpoint = MagicMock()

        with (
            patch("app.services.distillation_trainer.AdamW", return_value=MagicMock()),
            patch(
                "app.services.distillation_trainer.get_linear_schedule_with_warmup",
                return_value=MagicMock(),
            ),
            patch("app.services.distillation_trainer.classification_report", return_value="report"),
            patch("app.services.distillation_trainer.CHECKPOINT_DIR", ckpt_dir),
            patch("app.services.distillation_trainer.LOG_DIR", log_dir),
        ):
            trainer.train(data_path, output_dir=ckpt_dir)

        # save_checkpoint called for last + best for each epoch
        # Epoch 1: last + best (first best)
        # Epoch 2: last + best (new best)
        assert trainer.save_checkpoint.call_count == 4

    def test_train_no_improvement_saves_only_last(self, tmp_path):
        """When accuracy doesn't improve, only last checkpoint is saved per epoch."""
        trainer = DistillationTrainer(device="cpu", epochs=2, batch_size=2)

        data_path = str(tmp_path / "train.jsonl")
        with open(data_path, "w", encoding="utf-8") as f:
            for i in range(15):
                f.write(
                    json.dumps(
                        {"text": f"t{i}", "label": INTENT_LABELS[i % len(INTENT_LABELS)]},
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        log_dir = str(tmp_path / "logs")
        ckpt_dir = str(tmp_path / "ckpt")
        os.makedirs(log_dir, exist_ok=True)
        os.makedirs(ckpt_dir, exist_ok=True)

        trainer.load_data = MagicMock(return_value=(["a"] * 15, [0] * 15))
        trainer.prepare_data = MagicMock()
        # train() uses self.model.parameters() for AdamW; set up a mock model.
        trainer.model = MagicMock()
        trainer.model.parameters.return_value = iter([MagicMock()])
        trainer.train_loader = [MagicMock()]
        trainer.val_loader = [MagicMock()]
        trainer.train_epoch = MagicMock(return_value=(0.5, 0.8))
        # Accuracy stays at 0.5 — never improves from initial best_accuracy=0
        trainer.evaluate = MagicMock(
            side_effect=[
                {"val_loss": 0.4, "val_accuracy": 0.5, "preds": [0], "labels": [0]},
                {"val_loss": 0.4, "val_accuracy": 0.5, "preds": [0], "labels": [0]},
            ]
        )
        trainer.save_checkpoint = MagicMock()

        with (
            patch("app.services.distillation_trainer.AdamW", return_value=MagicMock()),
            patch(
                "app.services.distillation_trainer.get_linear_schedule_with_warmup",
                return_value=MagicMock(),
            ),
            patch("app.services.distillation_trainer.classification_report", return_value="report"),
            patch("app.services.distillation_trainer.CHECKPOINT_DIR", ckpt_dir),
            patch("app.services.distillation_trainer.LOG_DIR", log_dir),
        ):
            trainer.train(data_path, output_dir=ckpt_dir)

        # Each epoch: last checkpoint + best (since 0.5 > 0 initial)
        # Both epochs have same accuracy so second epoch doesn't beat first
        # Epoch 1: last + best (0.5 > 0)
        # Epoch 2: last only (0.5 not > 0.5)
        assert trainer.save_checkpoint.call_count == 3

    def test_train_exactly_10_samples(self, tmp_path):
        """train() should proceed with exactly 10 samples (minimum threshold)."""
        trainer = DistillationTrainer(device="cpu", epochs=1, batch_size=2)

        data_path = str(tmp_path / "exact10.jsonl")
        with open(data_path, "w", encoding="utf-8") as f:
            for i in range(10):
                f.write(
                    json.dumps(
                        {"text": f"t{i}", "label": INTENT_LABELS[i % len(INTENT_LABELS)]},
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        log_dir = str(tmp_path / "logs")
        ckpt_dir = str(tmp_path / "ckpt")
        os.makedirs(log_dir, exist_ok=True)
        os.makedirs(ckpt_dir, exist_ok=True)

        trainer.load_data = MagicMock(return_value=(["a"] * 10, [0] * 10))
        trainer.prepare_data = MagicMock()
        # train() uses self.model.parameters() for AdamW; set up a mock model.
        trainer.model = MagicMock()
        trainer.model.parameters.return_value = iter([MagicMock()])
        trainer.train_loader = [MagicMock()]
        trainer.val_loader = [MagicMock()]
        trainer.train_epoch = MagicMock(return_value=(0.5, 0.8))
        trainer.evaluate = MagicMock(
            return_value={"val_loss": 0.4, "val_accuracy": 0.8, "preds": [0], "labels": [0]}
        )
        trainer.save_checkpoint = MagicMock()

        with (
            patch("app.services.distillation_trainer.AdamW", return_value=MagicMock()),
            patch(
                "app.services.distillation_trainer.get_linear_schedule_with_warmup",
                return_value=MagicMock(),
            ),
            patch("app.services.distillation_trainer.classification_report", return_value="report"),
            patch("app.services.distillation_trainer.CHECKPOINT_DIR", ckpt_dir),
            patch("app.services.distillation_trainer.LOG_DIR", log_dir),
        ):
            trainer.train(data_path, output_dir=ckpt_dir)

        trainer.train_epoch.assert_called_once()


# ---------------------------------------------------------------------------
# DistillationTrainer.prepare_data — stratify branch
# ---------------------------------------------------------------------------


class TestDistillationTrainerPrepareDataStratify:
    """Test prepare_data stratify vs non-stratify branch."""

    def test_prepare_data_with_enough_labels_uses_stratify(self):
        """When >=10 unique labels and >100 samples, stratify should be used."""
        trainer = DistillationTrainer(device="cpu", batch_size=2)
        # 11 unique labels, 110 samples
        texts = [f"t{i}" for i in range(110)]
        labels = [i % 11 for i in range(110)]

        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        with (
            patch("app.services.distillation_trainer.BertTokenizer") as MockTokenizer,
            patch("app.services.distillation_trainer.BertForSequenceClassification") as MockModel,
            patch("app.services.distillation_trainer.DataLoader") as MockDataLoader,
            patch("app.services.distillation_trainer.train_test_split") as mock_split,
        ):
            MockTokenizer.from_pretrained.return_value = mock_tokenizer
            MockModel.from_pretrained.return_value = mock_model
            MockDataLoader.return_value = MagicMock()
            mock_split.return_value = (texts[:88], texts[88:], labels[:88], labels[88:])

            trainer.prepare_data(texts, labels, val_ratio=0.2)

            call_kwargs = mock_split.call_args[1]
            assert call_kwargs.get("stratify") is not None


# ---------------------------------------------------------------------------
# DistillationTrainer — device selection
# ---------------------------------------------------------------------------


class TestDistillationTrainerDeviceSelection:
    """Test device selection logic."""

    def test_auto_device_cpu_when_no_cuda(self):
        """When CUDA is not available, device should default to cpu."""
        with patch("app.services.distillation_trainer.torch") as mock_torch:
            mock_torch.cuda.is_available.return_value = False
            trainer = DistillationTrainer()
            assert trainer.device == "cpu"

    def test_explicit_device_overrides_auto(self):
        """Explicit device parameter should override auto-detection."""
        trainer = DistillationTrainer(device="cpu")
        assert trainer.device == "cpu"


# ---------------------------------------------------------------------------
# DistillationTrainer.save_checkpoint — edge cases
# ---------------------------------------------------------------------------


class TestDistillationTrainerSaveCheckpointEdgeCases:
    """Additional edge cases for save_checkpoint."""

    def test_save_checkpoint_config_has_saved_at(self, tmp_path):
        """train_config.json should contain a valid saved_at timestamp."""
        trainer = DistillationTrainer(device="cpu")
        trainer.tokenizer = MagicMock()
        trainer.model = MagicMock()

        checkpoint_path = str(tmp_path / "ckpt")
        ckpt_dir = str(tmp_path / "checkpoints")
        os.makedirs(checkpoint_path, exist_ok=True)
        os.makedirs(ckpt_dir, exist_ok=True)

        with patch("app.services.distillation_trainer.CHECKPOINT_DIR", ckpt_dir):
            trainer.save_checkpoint(checkpoint_path, epoch=1, best=True)

        config_path = os.path.join(checkpoint_path, "train_config.json")
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        assert "saved_at" in config
        # Should be a valid ISO format datetime
        assert "T" in config["saved_at"] or "-" in config["saved_at"]

    def test_save_checkpoint_best_false(self, tmp_path):
        """save_checkpoint with best=False should record best=False in config."""
        trainer = DistillationTrainer(device="cpu")
        trainer.tokenizer = MagicMock()
        trainer.model = MagicMock()

        checkpoint_path = str(tmp_path / "ckpt")
        ckpt_dir = str(tmp_path / "checkpoints")
        os.makedirs(checkpoint_path, exist_ok=True)
        os.makedirs(ckpt_dir, exist_ok=True)

        with patch("app.services.distillation_trainer.CHECKPOINT_DIR", ckpt_dir):
            trainer.save_checkpoint(checkpoint_path, epoch=5, best=False)

        config_path = os.path.join(checkpoint_path, "train_config.json")
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        assert config["best"] is False
        assert config["epoch"] == 5


# ---------------------------------------------------------------------------
# DistillationTrainer.evaluate — edge cases
# ---------------------------------------------------------------------------


class TestDistillationTrainerEvaluateEdgeCases:
    """Additional edge cases for evaluate."""

    @pytest.mark.skipif(not torch_available, reason="torch not available")
    def test_evaluate_multiple_batches(self):
        """evaluate should handle multiple batches correctly."""
        import torch

        trainer = DistillationTrainer(device="cpu")
        mock_model = MagicMock()

        batch1_output = MagicMock()
        batch1_output.loss = torch.tensor(0.3)
        batch1_output.logits = torch.tensor([[0.9, 0.1], [0.2, 0.8]])

        batch2_output = MagicMock()
        batch2_output.loss = torch.tensor(0.5)
        batch2_output.logits = torch.tensor([[0.7, 0.3]])

        mock_model.side_effect = [batch1_output, batch2_output]
        trainer.model = mock_model

        batch1 = {
            "input_ids": torch.tensor([[1, 2], [3, 4]]),
            "attention_mask": torch.tensor([[1, 1], [1, 1]]),
            "labels": torch.tensor([0, 1]),
        }
        batch2 = {
            "input_ids": torch.tensor([[5, 6]]),
            "attention_mask": torch.tensor([[1, 1]]),
            "labels": torch.tensor([0]),
        }

        class _FakeLoader:
            def __init__(self, batches):
                self._batches = batches

            def __iter__(self):
                return iter(self._batches)

            def __len__(self):
                return len(self._batches)

        trainer.val_loader = _FakeLoader([batch1, batch2])

        with patch("app.services.distillation_trainer.accuracy_score", return_value=1.0):
            result = trainer.evaluate()
        assert result["val_loss"] > 0
        assert 0 <= result["val_accuracy"] <= 1


# ---------------------------------------------------------------------------
# DistillationDataset — edge cases
# ---------------------------------------------------------------------------


class TestDistillationDatasetEdgeCases:
    """Additional edge cases for DistillationDataset."""

    def test_getitem_with_different_max_length(self):
        """Dataset should pass max_length to tokenizer."""
        mock_tokenizer = MagicMock()
        mock_input_ids = MagicMock()
        mock_attention_mask = MagicMock()
        mock_input_ids.squeeze.return_value = mock_input_ids
        mock_attention_mask.squeeze.return_value = mock_attention_mask
        mock_tokenizer.return_value = {
            "input_ids": mock_input_ids,
            "attention_mask": mock_attention_mask,
        }
        ds = DistillationDataset(["hello"], [0], mock_tokenizer, max_length=128)
        _ = ds[0]
        mock_tokenizer.assert_called_once_with(
            "hello",
            max_length=128,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        )

    @pytest.mark.skipif(not torch_available, reason="torch not available")
    def test_getitem_label_zero(self):
        """Label 0 should be handled correctly."""
        import torch

        mock_tokenizer = MagicMock()
        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1]]),
            "attention_mask": torch.tensor([[1]]),
        }
        ds = DistillationDataset(["test"], [0], mock_tokenizer)
        item = ds[0]
        assert item["labels"].item() == 0
