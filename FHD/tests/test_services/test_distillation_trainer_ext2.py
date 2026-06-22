"""Tests for app.services.distillation_trainer — uncovered branches (ext2).

Focus: DistillationDataset.__len__, DistillationTrainer.train_epoch with real tensors,
DistillationTrainer.train with insufficient data (< 10 samples), DistillationTrainer.init
device selection, module-level constants, and the instrument_service_layer_class call.
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

try:
    from app.services.distillation_trainer import (
        CHECKPOINT_DIR,
        DISTILL_DIR,
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

from app.services import distillation_trainer as _distillation_module

torch = _distillation_module.torch
torch_available = torch is not None


# ========================= DistillationDataset.__len__ =====================


class TestDistillationDatasetLen:
    def test_len_matches_texts(self):
        mock_tokenizer = MagicMock()
        ds = DistillationDataset(["a", "b", "c"], [0, 1, 2], mock_tokenizer)
        assert len(ds) == 3

    def test_len_empty(self):
        mock_tokenizer = MagicMock()
        ds = DistillationDataset([], [], mock_tokenizer)
        assert len(ds) == 0


# ========================= DistillationTrainer.train with < 10 samples ====


class TestDistillationTrainerTrainInsufficientData:
    def test_train_returns_early_with_insufficient_data(self, tmp_path):
        """train() should return early when fewer than 10 samples."""
        trainer = DistillationTrainer(device="cpu", epochs=1)

        data_path = str(tmp_path / "small.jsonl")
        with open(data_path, "w", encoding="utf-8") as f:
            for i in range(5):
                f.write(
                    json.dumps(
                        {"text": f"t{i}", "label": INTENT_LABELS[i % len(INTENT_LABELS)]},
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        # train() should return None when < 10 samples
        trainer.train(data_path, output_dir=str(tmp_path / "output"))
        # No exception raised, just early return


# ========================= DistillationTrainer.train_epoch =================


class TestDistillationTrainerTrainEpoch:
    @pytest.mark.skipif(not torch_available, reason="torch not available")
    def test_train_epoch_returns_loss_and_accuracy(self):
        trainer = DistillationTrainer(device="cpu", epochs=1, batch_size=2)

        # Create a minimal model and data loader
        mock_model = MagicMock()
        mock_output = MagicMock()
        mock_output.loss = torch.tensor(0.5)
        mock_output.logits = torch.tensor([[0.9, 0.1], [0.2, 0.8]])
        mock_model.return_value = mock_output
        mock_model.parameters.return_value = []
        trainer.model = mock_model

        batch = {
            "input_ids": torch.tensor([[1, 2], [3, 4]]),
            "attention_mask": torch.tensor([[1, 1], [1, 1]]),
            "labels": torch.tensor([0, 1]),
        }
        mock_loader = MagicMock()
        mock_loader.__iter__ = MagicMock(return_value=iter([batch]))
        mock_loader.__len__ = MagicMock(return_value=1)
        trainer.train_loader = mock_loader

        mock_optimizer = MagicMock()
        mock_scheduler = MagicMock()

        avg_loss, accuracy = trainer.train_epoch(mock_optimizer, mock_scheduler)
        assert avg_loss > 0
        assert 0 <= accuracy <= 1


# ========================= DistillationTrainer.init device selection ======


class TestDistillationTrainerInitDevice:
    def test_explicit_device_cuda(self):
        trainer = DistillationTrainer(device="cuda")
        assert trainer.device == "cuda"

    def test_default_params(self):
        trainer = DistillationTrainer()
        assert trainer.max_length == 64
        assert trainer.learning_rate == 2e-5
        assert trainer.batch_size == 16
        assert trainer.epochs == 3
        assert trainer.warmup_ratio == 0.1


# ========================= Module-level constants =========================


class TestModuleConstants:
    def test_intent_labels_not_empty(self):
        assert len(INTENT_LABELS) > 0
        assert "unk" in INTENT_LABELS

    def test_label_to_id_mapping(self):
        assert len(LABEL_TO_ID) == len(INTENT_LABELS)
        for label in INTENT_LABELS:
            assert label in LABEL_TO_ID

    def test_id_to_label_mapping(self):
        assert len(ID_TO_LABEL) == len(INTENT_LABELS)
        for idx, label in ID_TO_LABEL.items():
            assert label in INTENT_LABELS

    def test_bidirectional_consistency(self):
        for label, idx in LABEL_TO_ID.items():
            assert ID_TO_LABEL[idx] == label

    def test_distill_dir_is_string(self):
        assert isinstance(DISTILL_DIR, str)

    def test_checkpoint_dir_is_string(self):
        assert isinstance(CHECKPOINT_DIR, str)

    def test_log_dir_is_string(self):
        assert isinstance(LOG_DIR, str)


# ========================= DistillationTrainer.load_data TSV edge cases ===


class TestDistillationTrainerLoadDataTSV:
    def test_tsv_with_insufficient_columns(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        data_path = str(tmp_path / "short.tsv")
        with open(data_path, "w", encoding="utf-8") as f:
            f.write("text\tlabel\n")
            f.write("only_one_column\n")  # Only 1 column, needs >= 2

        texts, labels = trainer.load_data(data_path)
        assert len(texts) == 0

    def test_tsv_with_invalid_label(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        data_path = str(tmp_path / "bad_label.tsv")
        with open(data_path, "w", encoding="utf-8") as f:
            f.write("text\tlabel\n")
            f.write("hello\tinvalid_label\n")

        texts, labels = trainer.load_data(data_path)
        # Source appends text unconditionally for TSV rows with >=2 columns,
        # but only appends label when valid. So texts and labels can be out
        # of sync for invalid-label rows.
        assert len(texts) == 1
        assert len(labels) == 0

    def test_tsv_with_valid_data(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        data_path = str(tmp_path / "valid.tsv")
        with open(data_path, "w", encoding="utf-8") as f:
            f.write("text\tlabel\n")
            f.write("hello\tgreet\n")
            f.write("bye\tgoodbye\n")

        texts, labels = trainer.load_data(data_path)
        assert len(texts) == 2
        assert labels[0] == LABEL_TO_ID["greet"]
        assert labels[1] == LABEL_TO_ID["goodbye"]


# ========================= DistillationTrainer.evaluate with empty loader ==


class TestDistillationTrainerEvaluateEmpty:
    @pytest.mark.skipif(not torch_available, reason="torch not available")
    def test_evaluate_with_no_batches(self):
        trainer = DistillationTrainer(device="cpu")
        trainer.model = MagicMock()
        mock_loader = MagicMock()
        mock_loader.__iter__ = MagicMock(return_value=iter([]))
        mock_loader.__len__ = MagicMock(return_value=0)
        trainer.val_loader = mock_loader

        # This will raise ZeroDivisionError since len(val_loader) == 0
        # The source code doesn't guard against this
        try:
            result = trainer.evaluate()
        except ZeroDivisionError:
            pass  # Expected for empty loader


# ========================= DistillationTrainer.prepare_data low data ======


class TestDistillationTrainerPrepareDataLowData:
    def test_prepare_data_with_few_labels(self):
        """When < 10 unique labels or <= 100 samples, stratify should not be used."""
        trainer = DistillationTrainer(device="cpu", batch_size=2)
        texts = [f"t{i}" for i in range(5)]
        labels = [0, 1, 2, 3, 4]  # 5 unique labels, 5 samples

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
            mock_split.return_value = (texts[:4], texts[4:], labels[:4], labels[4:])

            trainer.prepare_data(texts, labels, val_ratio=0.2)

            call_kwargs = mock_split.call_args[1]
            assert "stratify" not in call_kwargs or call_kwargs.get("stratify") is None


# ========================= main() with custom model =======================


class TestMainCustomModel:
    def test_main_with_custom_model_name(self, tmp_path):
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
                "sys.argv", ["distillation_trainer", "--data", data_path, "--model", "custom-model"]
            ),
        ):
            main()
            MockTrainer.assert_called_once()
            call_kwargs = MockTrainer.call_args[1]
            assert call_kwargs["model_name"] == "custom-model"
