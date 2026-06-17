"""测试蒸馏训练器模块。

注意：distillation_trainer 依赖 torch / transformers 等重量级库，
在 CI 环境中可能不可用。因此测试通过 mock 或条件导入来覆盖核心逻辑。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest

# 尝试导入，如果 torch 不可用则跳过需要真实 torch 的测试
torch_available = True
try:
    import torch
except ImportError:
    torch_available = False

# 条件导入被测模块
try:
    from app.services.distillation_trainer import (
        ID_TO_LABEL,
        INTENT_LABELS,
        LABEL_TO_ID,
        DistillationDataset,
        DistillationTrainer,
    )
except ImportError:
    pytest.skip("distillation_trainer 依赖不可用", allow_module_level=True)


class TestIntentLabels:
    """测试意图标签常量。"""

    def test_intent_labels_not_empty(self):
        assert len(INTENT_LABELS) > 0

    def test_label_to_id_bijective(self):
        for label, idx in LABEL_TO_ID.items():
            assert ID_TO_LABEL[idx] == label

    def test_label_to_id_contains_known_intents(self):
        for intent in ("shipment_generate", "customers", "greet", "unk"):
            assert intent in LABEL_TO_ID

    def test_id_to_label_keys_are_contiguous(self):
        keys = sorted(ID_TO_LABEL.keys())
        assert keys == list(range(len(INTENT_LABELS)))


class TestDistillationDataset:
    """测试蒸馏数据集类。"""

    def test_len_returns_text_count(self):
        mock_tokenizer = MagicMock()
        mock_tokenizer.return_value = {
            "input_ids": MagicMock(squeeze=lambda dim: MagicMock()),
            "attention_mask": MagicMock(squeeze=lambda dim: MagicMock()),
        }
        texts = ["你好", "帮我开单"]
        labels = [0, 1]
        ds = DistillationDataset(texts, labels, mock_tokenizer)
        assert len(ds) == 2

    def test_len_empty(self):
        mock_tokenizer = MagicMock()
        ds = DistillationDataset([], [], mock_tokenizer)
        assert len(ds) == 0

    @pytest.mark.skipif(not torch_available, reason="torch not available")
    def test_getitem_returns_dict_with_expected_keys(self):
        import torch

        mock_tokenizer = MagicMock()
        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1]]),
        }
        texts = ["你好"]
        labels = [0]
        ds = DistillationDataset(texts, labels, mock_tokenizer, max_length=8)
        item = ds[0]
        assert "input_ids" in item
        assert "attention_mask" in item
        assert "labels" in item

    @pytest.mark.skipif(not torch_available, reason="torch not available")
    def test_getitem_label_is_long_tensor(self):
        import torch

        mock_tokenizer = MagicMock()
        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2]]),
            "attention_mask": torch.tensor([[1, 1]]),
        }
        ds = DistillationDataset(["test"], [5], mock_tokenizer)
        item = ds[0]
        assert item["labels"].dtype == torch.long
        assert item["labels"].item() == 5

    def test_getitem_calls_tokenizer_with_correct_args(self):
        mock_tokenizer = MagicMock()
        mock_input_ids = MagicMock()
        mock_attention_mask = MagicMock()
        mock_input_ids.squeeze.return_value = mock_input_ids
        mock_attention_mask.squeeze.return_value = mock_attention_mask
        mock_tokenizer.return_value = {
            "input_ids": mock_input_ids,
            "attention_mask": mock_attention_mask,
        }
        ds = DistillationDataset(["hello"], [0], mock_tokenizer, max_length=32)
        _ = ds[0]
        mock_tokenizer.assert_called_once_with(
            "hello", max_length=32, padding="max_length", truncation=True, return_tensors="pt"
        )


class TestDistillationTrainerInit:
    """测试 DistillationTrainer 初始化。"""

    def test_explicit_device_cpu(self):
        trainer = DistillationTrainer(device="cpu")
        assert trainer.device == "cpu"

    def test_default_hyperparameters(self):
        trainer = DistillationTrainer(device="cpu")
        assert trainer.num_labels == len(INTENT_LABELS)
        assert trainer.max_length == 64
        assert trainer.learning_rate == 2e-5
        assert trainer.batch_size == 16
        assert trainer.epochs == 3
        assert trainer.warmup_ratio == 0.1

    def test_custom_hyperparameters(self):
        trainer = DistillationTrainer(
            device="cpu",
            max_length=128,
            learning_rate=1e-4,
            batch_size=32,
            epochs=5,
            warmup_ratio=0.2,
        )
        assert trainer.max_length == 128
        assert trainer.learning_rate == 1e-4
        assert trainer.batch_size == 32
        assert trainer.epochs == 5
        assert trainer.warmup_ratio == 0.2

    def test_model_name_default(self):
        trainer = DistillationTrainer(device="cpu")
        assert trainer.model_name == "hfl/chinese-bert-wwm-ext"

    def test_initial_state_none(self):
        trainer = DistillationTrainer(device="cpu")
        assert trainer.tokenizer is None
        assert trainer.model is None
        assert trainer.train_loader is None
        assert trainer.val_loader is None


class TestDistillationTrainerLoadData:
    """测试数据加载功能。"""

    def test_load_jsonl_data(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        data_path = str(tmp_path / "test.jsonl")
        with open(data_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"text": "你好", "label": "greet"}, ensure_ascii=False) + "\n")
            f.write(
                json.dumps({"text": "开单", "label": "shipment_generate"}, ensure_ascii=False)
                + "\n"
            )

        texts, labels = trainer.load_data(data_path)
        assert len(texts) == 2
        assert "你好" in texts
        assert labels[0] == LABEL_TO_ID["greet"]
        assert labels[1] == LABEL_TO_ID["shipment_generate"]

    def test_load_jsonl_skips_unknown_labels(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        data_path = str(tmp_path / "test.jsonl")
        with open(data_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"text": "你好", "label": "greet"}, ensure_ascii=False) + "\n")
            f.write(
                json.dumps({"text": "unknown", "label": "nonexistent_label"}, ensure_ascii=False)
                + "\n"
            )

        texts, labels = trainer.load_data(data_path)
        assert len(texts) == 1

    def test_load_jsonl_default_label_is_unk(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        data_path = str(tmp_path / "test.jsonl")
        with open(data_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"text": "something"}, ensure_ascii=False) + "\n")

        texts, labels = trainer.load_data(data_path)
        assert len(texts) == 1
        assert labels[0] == LABEL_TO_ID["unk"]

    def test_load_tsv_data(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        data_path = str(tmp_path / "test.tsv")
        with open(data_path, "w", encoding="utf-8") as f:
            f.write("text\tlabel\n")
            f.write("你好\tgreet\n")
            f.write("开单\tshipment_generate\n")

        texts, labels = trainer.load_data(data_path)
        assert len(texts) == 2

    def test_load_tsv_skips_short_lines(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        data_path = str(tmp_path / "test.tsv")
        with open(data_path, "w", encoding="utf-8") as f:
            f.write("text\tlabel\n")
            f.write("only_one_column\n")
            f.write("你好\tgreet\n")

        texts, labels = trainer.load_data(data_path)
        assert len(texts) == 1

    def test_load_tsv_skips_unknown_labels(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        data_path = str(tmp_path / "test.tsv")
        with open(data_path, "w", encoding="utf-8") as f:
            f.write("text\tlabel\n")
            f.write("hello\tunknown_label\n")
            f.write("你好\tgreet\n")

        texts, labels = trainer.load_data(data_path)
        assert len(texts) == 1

    def test_load_empty_file(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        data_path = str(tmp_path / "empty.jsonl")
        with open(data_path, "w", encoding="utf-8") as f:
            pass

        texts, labels = trainer.load_data(data_path)
        assert len(texts) == 0
        assert len(labels) == 0

    def test_load_unsupported_format(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        data_path = str(tmp_path / "test.csv")
        with open(data_path, "w", encoding="utf-8") as f:
            f.write("text,label\nhello,greet\n")

        texts, labels = trainer.load_data(data_path)
        assert len(texts) == 0


class TestDistillationTrainerSaveCheckpoint:
    """测试检查点保存。"""

    def test_save_checkpoint_creates_config(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        trainer.tokenizer = MagicMock()
        trainer.model = MagicMock()

        checkpoint_path = str(tmp_path / "ckpt")
        os.makedirs(checkpoint_path, exist_ok=True)

        with patch(
            "app.services.distillation_trainer.CHECKPOINT_DIR", str(tmp_path / "checkpoints")
        ):
            os.makedirs(str(tmp_path / "checkpoints"), exist_ok=True)
            trainer.save_checkpoint(checkpoint_path, epoch=1, best=True)

        config_path = os.path.join(checkpoint_path, "train_config.json")
        assert os.path.exists(config_path)
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        assert config["epoch"] == 1
        assert config["best"] is True
        assert config["num_labels"] == len(INTENT_LABELS)
        assert "saved_at" in config

    def test_save_checkpoint_saves_model_and_tokenizer(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        trainer.tokenizer = MagicMock()
        trainer.model = MagicMock()

        checkpoint_path = str(tmp_path / "ckpt")
        os.makedirs(checkpoint_path, exist_ok=True)

        with patch(
            "app.services.distillation_trainer.CHECKPOINT_DIR", str(tmp_path / "checkpoints")
        ):
            os.makedirs(str(tmp_path / "checkpoints"), exist_ok=True)
            trainer.save_checkpoint(checkpoint_path, epoch=2, best=False)

        trainer.model.save_pretrained.assert_called_once_with(checkpoint_path)
        trainer.tokenizer.save_pretrained.assert_called_once_with(checkpoint_path)

    def test_save_checkpoint_creates_vocab(self, tmp_path):
        trainer = DistillationTrainer(device="cpu")
        trainer.tokenizer = MagicMock()
        trainer.model = MagicMock()

        checkpoint_path = str(tmp_path / "ckpt")
        ckpt_dir = str(tmp_path / "checkpoints")
        os.makedirs(checkpoint_path, exist_ok=True)
        os.makedirs(ckpt_dir, exist_ok=True)

        with patch("app.services.distillation_trainer.CHECKPOINT_DIR", ckpt_dir):
            trainer.save_checkpoint(checkpoint_path, epoch=1, best=False)

        vocab_path = os.path.join(ckpt_dir, "vocab.json")
        assert os.path.exists(vocab_path)
        with open(vocab_path, encoding="utf-8") as f:
            vocab = json.load(f)
        assert "id2label" in vocab
        assert "label2id" in vocab


class TestDistillationTrainerTrain:
    """测试完整训练流程的边界条件。"""

    def test_train_returns_early_with_insufficient_data(self, tmp_path):
        trainer = DistillationTrainer(device="cpu", epochs=1)
        data_path = str(tmp_path / "small.jsonl")
        with open(data_path, "w", encoding="utf-8") as f:
            for i in range(5):
                f.write(
                    json.dumps({"text": f"text{i}", "label": "greet"}, ensure_ascii=False) + "\n"
                )

        with patch("app.services.distillation_trainer.CHECKPOINT_DIR", str(tmp_path / "ckpt")):
            with patch("app.services.distillation_trainer.LOG_DIR", str(tmp_path / "logs")):
                result = trainer.train(data_path, output_dir=str(tmp_path / "ckpt"))
        assert result is None
