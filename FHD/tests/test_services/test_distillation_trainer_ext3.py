"""Tests for app.services.distillation_trainer — deep coverage (ext3).

Focus: DistillationTrainer.load_data with TSV format, prepare_data with few labels,
save_checkpoint, train with insufficient data, DistillationDataset.__getitem__,
and main() CLI entry point.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
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
    pytest.skip("distillation_trainer dependencies unavailable", allow_module_level=True)

torch_available = True
try:
    import torch
except ImportError:
    torch_available = False


# ---------------------------------------------------------------------------
# DistillationDataset.__getitem__ with real tokenizer mock
# ---------------------------------------------------------------------------


class TestDistillationDatasetGetitem:
    @pytest.mark.skipif(not torch_available, reason="torch not available")
    def test_getitem_returns_dict(self):
        mock_tokenizer = MagicMock()
        mock_input = MagicMock()
        mock_input.squeeze.return_value = mock_input
        mock_attn = MagicMock()
        mock_attn.squeeze.return_value = mock_attn
        mock_tokenizer.return_value = {
            "input_ids": mock_input,
            "attention_mask": mock_attn,
        }
        ds = DistillationDataset(["hello"], [0], mock_tokenizer, max_length=64)
        item = ds[0]
        assert "input_ids" in item
        assert "attention_mask" in item
        assert "labels" in item
        assert item["labels"].item() == 0

    @pytest.mark.skipif(not torch_available, reason="torch not available")
    def test_getitem_different_labels(self):
        mock_tokenizer = MagicMock()
        mock_input = MagicMock()
        mock_input.squeeze.return_value = mock_input
        mock_attn = MagicMock()
        mock_attn.squeeze.return_value = mock_attn
        mock_tokenizer.return_value = {
            "input_ids": mock_input,
            "attention_mask": mock_attn,
        }
        ds = DistillationDataset(["a", "b", "c"], [0, 5, 19], mock_tokenizer, max_length=64)
        assert ds[0]["labels"].item() == 0
        assert ds[1]["labels"].item() == 5
        assert ds[2]["labels"].item() == 19


# ---------------------------------------------------------------------------
# DistillationTrainer.load_data — TSV format
# ---------------------------------------------------------------------------


class TestDistillationTrainerLoadDataTSV:
    def test_load_tsv_valid(self, tmp_path):
        tsv_file = tmp_path / "data.tsv"
        tsv_file.write_text("text\tlabel\n你好\tgreet\n再见\tgoodbye\n", encoding="utf-8")

        trainer = DistillationTrainer.__new__(DistillationTrainer)
        texts, labels = trainer.load_data(str(tsv_file))
        assert len(texts) == 2
        assert "你好" in texts
        assert labels[0] == LABEL_TO_ID["greet"]

    def test_load_tsv_unknown_label_skipped(self, tmp_path):
        tsv_file = tmp_path / "data.tsv"
        tsv_file.write_text("text\tlabel\nhello\tunknown_label\n你好\tgreet\n", encoding="utf-8")

        trainer = DistillationTrainer.__new__(DistillationTrainer)
        texts, labels = trainer.load_data(str(tsv_file))
        # Unknown labels are skipped as complete samples so texts and labels stay aligned.
        assert len(texts) == 1
        assert len(labels) == 1
        assert labels[0] == LABEL_TO_ID["greet"]

    def test_load_tsv_single_column_skipped(self, tmp_path):
        tsv_file = tmp_path / "data.tsv"
        tsv_file.write_text("text\nhello\n", encoding="utf-8")

        trainer = DistillationTrainer.__new__(DistillationTrainer)
        texts, labels = trainer.load_data(str(tsv_file))
        assert len(texts) == 0

    def test_load_jsonl_with_unknown_label(self, tmp_path):
        jsonl_file = tmp_path / "data.jsonl"
        lines = [
            json.dumps({"text": "hi", "label": "greet"}),
            json.dumps({"text": "hello", "label": "nonexistent_label"}),
        ]
        jsonl_file.write_text("\n".join(lines), encoding="utf-8")

        trainer = DistillationTrainer.__new__(DistillationTrainer)
        texts, labels = trainer.load_data(str(jsonl_file))
        assert len(texts) == 1
        assert texts[0] == "hi"

    def test_load_jsonl_empty_text(self, tmp_path):
        jsonl_file = tmp_path / "data.jsonl"
        lines = [
            json.dumps({"text": "", "label": "greet"}),
            json.dumps({"text": "hello", "label": "greet"}),
        ]
        jsonl_file.write_text("\n".join(lines), encoding="utf-8")

        trainer = DistillationTrainer.__new__(DistillationTrainer)
        texts, labels = trainer.load_data(str(jsonl_file))
        # Empty text still gets loaded (label is valid)
        assert len(texts) >= 1


# ---------------------------------------------------------------------------
# DistillationTrainer — device selection
# ---------------------------------------------------------------------------


class TestDistillationTrainerDevice:
    def test_explicit_device_cpu(self):
        trainer = DistillationTrainer(device="cpu")
        assert trainer.device == "cpu"

    @pytest.mark.skipif(not torch_available, reason="torch not available")
    def test_default_device_selection(self):
        trainer = DistillationTrainer()
        assert trainer.device in ("cpu", "cuda")


# ---------------------------------------------------------------------------
# DistillationTrainer.train — insufficient data
# ---------------------------------------------------------------------------


class TestDistillationTrainerTrainInsufficientData:
    def test_train_with_less_than_10_samples(self, tmp_path):
        jsonl_file = tmp_path / "small.jsonl"
        lines = [json.dumps({"text": f"text{i}", "label": "greet"}) for i in range(5)]
        jsonl_file.write_text("\n".join(lines), encoding="utf-8")

        trainer = DistillationTrainer(device="cpu")
        # Should return early without error
        trainer.train(str(jsonl_file), output_dir=str(tmp_path / "output"))


# ---------------------------------------------------------------------------
# DistillationTrainer.save_checkpoint
# ---------------------------------------------------------------------------


class TestDistillationTrainerSaveCheckpoint:
    @pytest.mark.skipif(not torch_available, reason="torch not available")
    def test_save_checkpoint_creates_files(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        # Manually set tokenizer and model to mocks
        trainer.tokenizer = MagicMock()
        trainer.model = MagicMock()

        output_dir = tmp_path / "ckpt"
        output_dir.mkdir()
        trainer.save_checkpoint(str(output_dir), epoch=1, best=False)

        trainer.model.save_pretrained.assert_called_once_with(str(output_dir))
        trainer.tokenizer.save_pretrained.assert_called_once_with(str(output_dir))

        # Check train_config.json was written
        config_path = output_dir / "train_config.json"
        assert config_path.exists()
        config = json.loads(config_path.read_text(encoding="utf-8"))
        assert config["epoch"] == 1
        assert config["best"] is False

    @pytest.mark.skipif(not torch_available, reason="torch not available")
    def test_save_checkpoint_best_flag(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        trainer.tokenizer = MagicMock()
        trainer.model = MagicMock()

        output_dir = tmp_path / "ckpt_best"
        output_dir.mkdir()
        trainer.save_checkpoint(str(output_dir), epoch=3, best=True)

        config_path = output_dir / "train_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        assert config["best"] is True
        assert config["epoch"] == 3


# ---------------------------------------------------------------------------
# DistillationTrainer constants
# ---------------------------------------------------------------------------


class TestDistillationTrainerConstants:
    def test_intent_labels_count(self):
        assert len(INTENT_LABELS) == 20

    def test_label_to_id_consistency(self):
        for label, idx in LABEL_TO_ID.items():
            assert ID_TO_LABEL[idx] == label

    def test_distill_dir_exists(self):
        assert isinstance(DISTILL_DIR, str)

    def test_checkpoint_dir_exists(self):
        assert isinstance(CHECKPOINT_DIR, str)

    def test_log_dir_exists(self):
        assert isinstance(LOG_DIR, str)


# ---------------------------------------------------------------------------
# main() CLI entry point
# ---------------------------------------------------------------------------


class TestMainCLI:
    def test_main_with_nonexistent_data(self):
        with patch("sys.argv", ["distillation_trainer", "--data", "/nonexistent/path.jsonl"]):
            # Should not raise, just log error and return
            main()

    def test_main_with_default_data_path(self, tmp_path):
        with patch("sys.argv", ["distillation_trainer"]):
            with patch(
                "app.services.distillation_trainer.get_distillation_training_data_path",
                return_value=str(tmp_path / "nonexistent.jsonl"),
            ):
                # Should not raise
                main()
