"""
意图识别模型训练器：基于预训练Transformer模型进行微调

支持模型：
- bert-base-chinese
- hfl/chinese-bert-wwm
- hfl/chinese-roberta-wwm-ext

使用方法：
    python -m app.services.intent_trainer --data rasa/data/nlu.yml --model bert-base-chinese --epochs 5
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

# torch / transformers 是可选的重型 ML 依赖（见 requirements-ml.txt / pyproject [project.optional-dependencies].ml）。
# CI 与默认服务镜像不安装它们（deploy/requirements-server-api.txt 明确“去掉 torch 等大包”）。
# 历史上这里在模块顶层无条件 import，使整个 test_intent_trainer*.py 在无 ML 栈的环境（含 CI）
# 走 module-level skip——纯逻辑单元测试形同虚设。改为可选导入：标签/数据加载/切分/指标等纯逻辑
# 在无 torch/transformers 时仍可导入与测试；仅真正用到张量/模型的训练-导出路径在调用期才需要它们。
try:
    import torch
    from torch.utils.data import Dataset

    HAS_TORCH = True
except ImportError:  # pragma: no cover - 取决于运行环境是否安装了 torch
    HAS_TORCH = False
    torch = None  # type: ignore[assignment]
    Dataset = object  # type: ignore[assignment,misc]  # 占位基类：无 torch 时仍能定义 IntentDataset

try:
    from transformers import (
        AutoConfig,
        AutoModelForSequenceClassification,
        AutoTokenizer,
        BertTokenizer,
        DataCollatorWithPadding,
        EarlyStoppingCallback,
        Trainer,
        TrainingArguments,
    )

    HAS_TRANSFORMERS = True
except ImportError:  # pragma: no cover - 取决于运行环境是否安装了 transformers
    HAS_TRANSFORMERS = False
    # 占位符：让 `@patch("app.services.intent_trainer.AutoTokenizer")` 等 mock 目标可解析，
    # 纯逻辑导入不受影响；真正（未打桩地）调用训练/导出函数时会在访问这些 None 符号处报错——
    # 而唯一的运行时消费方 train_intent.py 自身在模块顶层 import torch，本就要求装好 ML 栈。
    AutoConfig = None  # type: ignore[assignment]
    AutoModelForSequenceClassification = None  # type: ignore[assignment]
    AutoTokenizer = None  # type: ignore[assignment]
    BertTokenizer = None  # type: ignore[assignment]
    DataCollatorWithPadding = None  # type: ignore[assignment]
    EarlyStoppingCallback = None  # type: ignore[assignment]
    Trainer = None  # type: ignore[assignment]
    TrainingArguments = None  # type: ignore[assignment]

try:
    import yaml

    HAS_YAML = True
except ImportError:
    HAS_YAML = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


INTENT_LABELS = [
    "shipment_generate",
    "customers",
    "products",
    "shipments",
    "wechat_send",
    "print_label",
    "upload_file",
    "materials",
    "shipment_template",
    "excel_decompose",
    "show_images",
    "show_videos",
    "greet",
    "goodbye",
    "help",
    "negation",
    "customer_export",
    "customer_edit",
    "customer_supplement",
    "unk",
]

LABEL_TO_ID = {label: idx for idx, label in enumerate(INTENT_LABELS)}
ID_TO_LABEL = {idx: label for idx, label in enumerate(INTENT_LABELS)}


@dataclass
class IntentExample:
    text: str
    label: str


class IntentDataset(Dataset):
    def __init__(
        self, examples: list[IntentExample], tokenizer: BertTokenizer, max_length: int = 64
    ):
        self.examples = examples
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, idx: int) -> dict:
        example = self.examples[idx]
        encoding = self.tokenizer(
            example.text,
            max_length=self.max_length,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        )
        item = {key: val.squeeze(0) for key, val in encoding.items()}
        if example.label in LABEL_TO_ID:
            item["labels"] = torch.tensor(LABEL_TO_ID[example.label])
        return item


def parse_nlu_yaml(yaml_path: str) -> list[IntentExample]:
    """解析 RASA NLU YAML 训练数据"""
    if not HAS_YAML:
        raise ImportError("PyYAML is required to parse NLU data. Install with: pip install pyyaml")

    examples = []
    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    nlu_data = data.get("nlu", [])
    for item in nlu_data:
        if "intent" in item and "examples" in item:
            intent_name = item["intent"]
            if intent_name == "negation_test":
                intent_name = "negation"
            raw_examples = item["examples"]
            lines = [line.strip() for line in raw_examples.split("\n") if line.strip()]
            for line in lines:
                if line.startswith("-"):
                    text = line[1:].strip()
                    if text:
                        examples.append(IntentExample(text=text, label=intent_name))

    logger.info("从 %s 解析了 %s 条训练样本", yaml_path, len(examples))
    return examples


def load_training_data(data_path: str) -> list[IntentExample]:
    """加载训练数据，支持多种格式"""
    path = Path(data_path)
    if path.suffix == ".yml" or path.suffix == ".yaml":
        return parse_nlu_yaml(str(path))
    elif path.suffix == ".json":
        with open(str(path), encoding="utf-8") as f:
            data = json.load(f)
        examples = []
        for item in data:
            if "text" in item and "label" in item:
                examples.append(IntentExample(text=item["text"], label=item["label"]))
        return examples
    else:
        raise ValueError(f"Unsupported data format: {path.suffix}")


def split_data(
    examples: list[IntentExample],
    train_ratio: float = 0.8,
    val_ratio: float = 0.1,
    test_ratio: float = 0.1,
    seed: int = 42,
) -> tuple[list[IntentExample], list[IntentExample], list[IntentExample]]:
    """划分训练集/验证集/测试集"""
    import random

    random.seed(seed)
    shuffled = examples.copy()
    random.shuffle(shuffled)

    n = len(shuffled)
    n_train = int(n * train_ratio)
    n_val = int(n * val_ratio)

    train_data = shuffled[:n_train]
    val_data = shuffled[n_train : n_train + n_val]
    test_data = shuffled[n_train + n_val :]

    logger.info(
        "数据划分: 训练集 %s, 验证集 %s, 测试集 %s", len(train_data), len(val_data), len(test_data)
    )
    return train_data, val_data, test_data


def compute_metrics(eval_pred):
    """计算评估指标"""
    from sklearn.metrics import accuracy_score, precision_recall_fscore_support

    predictions, labels = eval_pred
    predictions = predictions.argmax(axis=-1)
    accuracy = accuracy_score(labels, predictions)
    precision, recall, f1, _ = precision_recall_fscore_support(
        labels, predictions, average="weighted", zero_division=0
    )
    return {
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def train_intent_model(
    data_path: str,
    model_name: str = "bert-base-chinese",
    output_dir: str = "models/intent_bert",
    num_epochs: int = 10,
    batch_size: int = 16,
    learning_rate: float = 2e-5,
    max_length: int = 64,
    warmup_ratio: float = 0.1,
    weight_decay: float = 0.01,
    early_stopping_patience: int = 3,
):
    """
    训练意图识别模型

    Args:
        data_path: 训练数据路径
        model_name: 预训练模型名称
        output_dir: 输出目录
        num_epochs: 训练轮数
        batch_size: 批次大小
        learning_rate: 学习率
        max_length: 最大序列长度
        warmup_ratio: 预热比例
        weight_decay: 权重衰减
        early_stopping_patience: 早停耐心值
    """
    logger.info("开始训练意图识别模型...")
    logger.info("  数据: %s", data_path)
    logger.info("  模型: %s", model_name)
    logger.info("  轮数: %s", num_epochs)
    logger.info("  批次大小: %s", batch_size)

    examples = load_training_data(data_path)
    if len(examples) == 0:
        raise ValueError("训练数据为空")

    train_data, val_data, test_data = split_data(examples)

    tokenizer = AutoTokenizer.from_pretrained(model_name)

    train_dataset = IntentDataset(train_data, tokenizer, max_length)
    val_dataset = IntentDataset(val_data, tokenizer, max_length)
    test_dataset = IntentDataset(test_data, tokenizer, max_length)

    num_labels = len(INTENT_LABELS)

    config = AutoConfig.from_pretrained(
        model_name,
        num_labels=num_labels,
        id2label=ID_TO_LABEL,
        label2id=LABEL_TO_ID,
    )
    model = AutoModelForSequenceClassification.from_pretrained(
        model_name,
        config=config,
    )

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    training_args = TrainingArguments(
        output_dir=str(output_path),
        num_train_epochs=num_epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size * 2,
        learning_rate=learning_rate,
        warmup_ratio=warmup_ratio,
        weight_decay=weight_decay,
        logging_dir=str(output_path / "logs"),
        logging_steps=10,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="f1",
        greater_is_better=True,
        save_total_limit=2,
        report_to=["none"],
        fp16=bool(HAS_TORCH and torch.cuda.is_available()),
    )

    callbacks = []
    if early_stopping_patience > 0:
        callbacks.append(EarlyStoppingCallback(early_stopping_patience=early_stopping_patience))

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        compute_metrics=compute_metrics,
        data_collator=DataCollatorWithPadding(tokenizer),
        callbacks=callbacks,
    )

    trainer.train()

    logger.info("训练完成，在测试集上评估...")
    test_results = trainer.evaluate(test_dataset)
    logger.info("测试集结果: %s", test_results)

    final_model_path = output_path / "final"
    trainer.save_model(str(final_model_path))
    tokenizer.save_pretrained(str(final_model_path))

    with open(final_model_path / "intent_labels.json", "w", encoding="utf-8") as f:
        json.dump(
            {"labels": INTENT_LABELS, "id2label": ID_TO_LABEL, "label2id": LABEL_TO_ID},
            f,
            ensure_ascii=False,
            indent=2,
        )

    logger.info("模型已保存到: %s", final_model_path)
    return final_model_path


def export_to_onnx(model_path: str, output_path: str, max_length: int = 64):
    """导出模型为 ONNX 格式"""
    try:
        import onnxruntime  # noqa: F401

    except ImportError:
        logger.warning("ONNXRuntime not installed, skipping ONNX export")
        return

    tokenizer = AutoTokenizer.from_pretrained(model_path)
    model = AutoModelForSequenceClassification.from_pretrained(model_path)
    model.eval()

    dummy_input = tokenizer(
        "测试文本",
        max_length=max_length,
        padding="max_length",
        truncation=True,
        return_tensors="pt",
    )

    torch.onnx.export(
        model,
        (dummy_input["input_ids"], dummy_input["attention_mask"]),
        output_path,
        input_names=["input_ids", "attention_mask"],
        output_names=["logits"],
        dynamic_axes={
            "input_ids": {0: "batch_size"},
            "attention_mask": {0: "batch_size"},
            "logits": {0: "batch_size"},
        },
        opset_version=14,
    )
    logger.info("ONNX 模型已导出到: %s", output_path)


def main():
    parser = argparse.ArgumentParser(description="意图识别模型训练")
    parser.add_argument("--data", type=str, required=True, help="训练数据路径 (YAML/JSON)")
    parser.add_argument("--model", type=str, default="bert-base-chinese", help="预训练模型名称")
    parser.add_argument("--output", type=str, default="models/intent_bert", help="输出目录")
    parser.add_argument("--epochs", type=int, default=10, help="训练轮数")
    parser.add_argument("--batch_size", type=int, default=16, help="批次大小")
    parser.add_argument("--lr", type=float, default=2e-5, help="学习率")
    parser.add_argument("--max_length", type=int, default=64, help="最大序列长度")
    parser.add_argument("--export_onnx", action="store_true", help="导出 ONNX 模型")
    args = parser.parse_args()

    model_path = train_intent_model(
        data_path=args.data,
        model_name=args.model,
        output_dir=args.output,
        num_epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.lr,
        max_length=args.max_length,
    )

    if args.export_onnx:
        onnx_path = str(Path(args.output) / "model.onnx")
        export_to_onnx(str(model_path), onnx_path, args.max_length)


if __name__ == "__main__":
    main()
