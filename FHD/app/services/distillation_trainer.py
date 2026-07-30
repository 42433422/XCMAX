"""
蒸馏训练脚本 - 微调 BERT 模型用于意图识别并沉淀业务 know-how

使用收集的蒸馏数据微调 chinese-bert-wwm-ext 模型；也可以从用户反馈、
客服变更工单、bug 修复记录中构建持续学习候选集，经审核后进入训练集。

使用方法：
    python -m app.services.distillation_trainer --data distillation/training_data.jsonl --epochs 3
    python -m app.services.distillation_trainer --learn-from-defaults --review-only
    python -m app.services.distillation_trainer --data distillation/training_data.jsonl
        --learn-from-feedback app/user_memory/memory_store.json

模型输出：
    distillation/checkpoints/best.pt
    distillation/checkpoints/last.pt
    distillation/checkpoints/vocab.json

持续学习输出：
    distillation/continuous_learning/candidate_samples.jsonl
    distillation/continuous_learning/review_queue.jsonl
    distillation/continuous_learning/approved_samples.jsonl
    distillation/continuous_learning/industry_knowhow.jsonl
    distillation/continuous_learning/training_data.continuous.jsonl
    distillation/continuous_learning/manifest.json
"""

import argparse
import hashlib
import json
import logging
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import torch
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split
from torch.optim import AdamW as TorchAdamW
from torch.utils.data import DataLoader, Dataset

_TRANSFORMERS_IMPORT_ERROR: ImportError | None = None

try:
    from transformers import (
        BertForSequenceClassification,
        BertTokenizer,
        get_linear_schedule_with_warmup,
    )
except ImportError as exc:
    _TRANSFORMERS_IMPORT_ERROR = exc

    class _MissingTransformerComponent:
        @classmethod
        def from_pretrained(cls, *args, **kwargs):
            raise ImportError(
                "transformers is required for distillation model loading"
            ) from _TRANSFORMERS_IMPORT_ERROR

    BertForSequenceClassification = _MissingTransformerComponent
    BertTokenizer = _MissingTransformerComponent

    def get_linear_schedule_with_warmup(*args, **kwargs):
        raise ImportError(
            "transformers is required to build the distillation scheduler"
        ) from _TRANSFORMERS_IMPORT_ERROR


try:
    from transformers import AdamW
except ImportError:
    AdamW = TorchAdamW

from app.utils.distillation_paths import (
    get_distillation_checkpoints_dir,
    get_distillation_logs_dir,
    get_distillation_root_dir,
    get_distillation_training_data_path,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

try:
    from app.services.bert_intent_service import INTENT_LABELS as RUNTIME_INTENT_LABELS
except ImportError:
    RUNTIME_INTENT_LABELS = [
        "shipment_generate",
        "customers",
        "products",
        "shipments",
        "wechat_send",
        "print_label",
        "upload_file",
        "materials",
        "shipment_template",
        "template_extract",
        "business_docking",
        "template_preview",
        "shipment_records",
        "wechat",
        "printer_list",
        "settings",
        "tools_table",
        "other_tools",
        "ai_ecosystem",
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

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DISTILL_DIR = get_distillation_root_dir()
CHECKPOINT_DIR = get_distillation_checkpoints_dir()
LOG_DIR = get_distillation_logs_dir()
CONTINUOUS_LEARNING_DIR = os.path.join(DISTILL_DIR, "continuous_learning")
CONTINUOUS_TRAINING_DATA_NAME = "training_data.continuous.jsonl"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

INTENT_LABELS = list(RUNTIME_INTENT_LABELS)

LABEL_TO_ID = {label: idx for idx, label in enumerate(INTENT_LABELS)}
ID_TO_LABEL = {idx: label for label, idx in LABEL_TO_ID.items()}

LEARNING_STATUSES = {"candidate", "approved", "rejected"}
TRAINABLE_STATUSES = {"approved"}
RESOLVED_TICKET_STATUSES = {"resolved", "closed"}

INTENT_ALIASES = {
    "customer_list": "customers",
    "customer_query": "customers",
    "template_query": "shipment_template",
    "excel_analyzer": "excel_decompose",
    "send_wechat": "wechat_send",
    "wechat_contacts": "wechat",
    "unknown": "unk",
    "other": "unk",
    "default": "unk",
}

KEYWORD_INTENT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("negation", ("不要", "不用", "别", "取消", "不需要", "停止")),
    ("greet", ("你好", "您好", "hello", "hi", "早上好", "晚上好")),
    ("goodbye", ("再见", "拜拜", "bye", "先这样")),
    ("template_preview", ("模板预览", "预览模板", "看模板效果")),
    ("template_extract", ("提取模板", "导出模板", "模板提取", "词条提取")),
    (
        "business_docking",
        ("业务对接", "数据对接", "系统对接", "ERP 对接", "ERP对接"),
    ),
    ("shipment_records", ("出货记录", "发货记录", "送货记录", "历史发货单")),
    (
        "shipment_generate",
        ("生成发货单", "开发货单", "做发货单", "开单", "打单", "送货单"),
    ),
    ("wechat_send", ("发微信", "发送微信", "发消息", "发送消息", "转发给")),
    ("printer_list", ("打印机", "打印机列表", "选择打印机")),
    ("print_label", ("打印标签", "标签打印", "商标打印", "打标签", "标签偏移")),
    ("upload_file", ("上传", "导入", "上传文件", "导入文件", "解析文件")),
    ("materials", ("原材料", "材料", "库存", "材料库")),
    ("excel_decompose", ("分解 excel", "分解Excel", "解析 excel", "解析Excel", "表头")),
    ("customer_export", ("导出客户", "导出单位", "导出用户")),
    ("customer_edit", ("修改客户", "编辑客户", "更新客户", "改客户")),
    ("customer_supplement", ("补充客户", "添加联系人", "补充联系人", "客户资料")),
    ("customers", ("客户", "购买单位", "单位列表", "客户列表")),
    ("products", ("产品", "商品", "规格", "型号", "产品库")),
    ("settings", ("系统设置", "设置", "配置")),
    ("tools_table", ("工具表", "工具列表", "工具台账")),
    ("other_tools", ("其他工具", "更多工具")),
    ("ai_ecosystem", ("AI生态", "ai生态", "智能生态")),
    ("show_images", ("图片", "照片", "查看图片")),
    ("show_videos", ("视频", "录像", "查看视频")),
    (
        "help",
        (
            "帮助",
            "怎么用",
            "功能介绍",
            "支持什么",
            "报错",
            "故障",
            "bug",
            "问题",
        ),
    ),
)


def _now_iso() -> str:
    return datetime.now().isoformat()


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_intent_label(value: Any, *, default: str = "unk") -> str:
    label = str(value or "").strip()
    label = INTENT_ALIASES.get(label, label)
    if label in LABEL_TO_ID:
        return label
    return default if default in LABEL_TO_ID else str(default)


def infer_intent_label(text: str, *, default: str = "unk") -> str:
    normalized = _normalize_text(text)
    if not normalized:
        return normalize_intent_label(default)
    compact = normalized.replace(" ", "")
    lowered = normalized.lower()
    for label, keywords in KEYWORD_INTENT_RULES:
        if label not in LABEL_TO_ID:
            continue
        for keyword in keywords:
            if _keyword_matches(keyword, lowered=lowered, compact=compact):
                return label
    return normalize_intent_label(default)


def _keyword_matches(keyword: str, *, lowered: str, compact: str) -> bool:
    key = keyword.lower()
    compact_key = keyword.replace(" ", "")
    if key.isascii() and key.replace(" ", "").isalnum():
        return re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", lowered) is not None
    return key in lowered or compact_key in compact


def _coerce_float(value: Any, default: float = 1.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    return max(0.0, min(1.0, result))


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(loaded) if isinstance(loaded, dict) else {}
    return {}


def _stable_id(*parts: Any, prefix: str = "") -> str:
    raw = "\x1f".join(_normalize_text(part) for part in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}{digest}" if prefix else digest


def _row_text(*parts: Any, max_chars: int = 12000) -> str:
    text = "\n".join([_normalize_text(part) for part in parts if _normalize_text(part)])
    return text[:max_chars]


def _load_jsonish_rows(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        return []
    if source.is_dir():
        rows: list[dict[str, Any]] = []
        for child in sorted(source.glob("*.json")) + sorted(source.glob("*.jsonl")):
            rows.extend(_load_jsonish_rows(child))
        return rows

    if source.suffix == ".jsonl":
        rows = []
        with source.open(encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                loaded = json.loads(line)
                if isinstance(loaded, dict):
                    rows.append(loaded)
        return rows

    if source.suffix == ".json":
        loaded = json.loads(source.read_text(encoding="utf-8"))
        if isinstance(loaded, list):
            return [row for row in loaded if isinstance(row, dict)]
        if isinstance(loaded, dict):
            for key in ("requests", "tickets", "items", "events", "feedback"):
                value = loaded.get(key)
                if isinstance(value, list):
                    return [row for row in value if isinstance(row, dict)]
            return [loaded]
    return []


@dataclass
class LearningSample:
    """A source-traceable sample that may enter the classifier training set."""

    text: str
    label: str
    source_type: str
    source_id: str = ""
    confidence: float = 1.0
    slots: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    status: str = "candidate"
    created_at: str = field(default_factory=_now_iso)
    sample_id: str = ""

    def __post_init__(self) -> None:
        self.text = _normalize_text(self.text)
        self.label = normalize_intent_label(self.label)
        self.source_type = _normalize_text(self.source_type) or "unknown"
        self.source_id = _normalize_text(self.source_id)
        self.confidence = _coerce_float(self.confidence)
        self.slots = _coerce_dict(self.slots)
        self.metadata = _coerce_dict(self.metadata)
        self.evidence = _coerce_dict(self.evidence)
        if self.status not in LEARNING_STATUSES:
            self.status = "candidate"
        if not self.sample_id:
            self.sample_id = _stable_id(
                self.source_type,
                self.source_id,
                self.text,
                self.label,
                prefix="ls_",
            )

    @property
    def trainable(self) -> bool:
        return (
            self.status in TRAINABLE_STATUSES
            and bool(self.text)
            and self.label in LABEL_TO_ID
        )

    def to_training_row(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "label": self.label,
            "slots": self.slots,
            "source": self.source_type,
            "source_id": self.source_id,
            "confidence": self.confidence,
            "learning_sample_id": self.sample_id,
        }

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["trainable"] = self.trainable
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LearningSample":
        return cls(**{k: v for k, v in data.items() if k != "trainable"})


@dataclass
class KnowledgeUnit:
    """A non-classifier artifact for ERP domain know-how accumulation."""

    title: str
    summary: str
    source_type: str
    source_id: str = ""
    problem: str = ""
    resolution: str = ""
    domain_tags: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now_iso)
    unit_id: str = ""

    def __post_init__(self) -> None:
        self.title = _normalize_text(self.title)[:256]
        self.summary = _normalize_text(self.summary)[:4000]
        self.source_type = _normalize_text(self.source_type) or "unknown"
        self.source_id = _normalize_text(self.source_id)
        self.problem = _normalize_text(self.problem)[:4000]
        self.resolution = _normalize_text(self.resolution)[:4000]
        self.domain_tags = sorted({_normalize_text(tag) for tag in self.domain_tags if tag})
        self.evidence = _coerce_dict(self.evidence)
        if not self.unit_id:
            self.unit_id = _stable_id(
                self.source_type,
                self.source_id,
                self.title,
                self.summary,
                prefix="ku_",
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ContinuousLearningCorpus:
    """Builds a reviewable corpus from production signals before training."""

    def __init__(self, *, min_confidence: float = 0.75):
        self.min_confidence = _coerce_float(min_confidence, 0.75)
        self.samples: dict[str, LearningSample] = {}
        self.knowledge_units: dict[str, KnowledgeUnit] = {}
        self.skipped: list[dict[str, Any]] = []

    def add_sample(self, sample: LearningSample, *, reason: str = "") -> bool:
        if not sample.text:
            self.skipped.append(
                {
                    "reason": reason or "empty_text",
                    "source_type": sample.source_type,
                    "source_id": sample.source_id,
                }
            )
            return False
        if sample.status == "approved" and sample.confidence < self.min_confidence:
            sample.status = "candidate"
            sample.metadata["review_reason"] = "confidence_below_training_gate"
        existing = self.samples.get(sample.sample_id)
        if existing is None:
            self.samples[sample.sample_id] = sample
            return True
        if self._sample_rank(sample) > self._sample_rank(existing):
            self.samples[sample.sample_id] = sample
        return False

    def add_knowledge_unit(self, unit: KnowledgeUnit) -> bool:
        if not unit.title and not unit.summary:
            return False
        if unit.unit_id not in self.knowledge_units:
            self.knowledge_units[unit.unit_id] = unit
            return True
        return False

    def apply_review_decisions(self, decisions_path: str | Path | None) -> int:
        if not decisions_path:
            return 0
        changed = 0
        for row in _load_jsonish_rows(decisions_path):
            sample_id = str(
                row.get("sample_id") or row.get("learning_sample_id") or ""
            ).strip()
            if not sample_id or sample_id not in self.samples:
                continue
            sample = self.samples[sample_id]
            status = str(row.get("status") or "").strip()
            if status in LEARNING_STATUSES:
                sample.status = status
            if row.get("label") is not None:
                sample.label = normalize_intent_label(row.get("label"))
            if row.get("reviewer"):
                sample.metadata["reviewer"] = str(row.get("reviewer"))
            if row.get("review_note"):
                sample.metadata["review_note"] = str(row.get("review_note"))
            sample.metadata["reviewed_at"] = row.get("reviewed_at") or _now_iso()
            changed += 1
        return changed

    def trainable_samples(self, *, include_candidates: bool = False) -> list[LearningSample]:
        allowed = {"approved", "candidate"} if include_candidates else TRAINABLE_STATUSES
        return [
            sample
            for sample in sorted(self.samples.values(), key=lambda item: item.sample_id)
            if sample.status in allowed and sample.text and sample.label in LABEL_TO_ID
        ]

    def stats(self) -> dict[str, Any]:
        by_status = Counter(sample.status for sample in self.samples.values())
        by_label = Counter(sample.label for sample in self.samples.values())
        by_source = Counter(sample.source_type for sample in self.samples.values())
        return {
            "labels_count": len(INTENT_LABELS),
            "samples_total": len(self.samples),
            "trainable_total": len(self.trainable_samples()),
            "knowledge_units_total": len(self.knowledge_units),
            "skipped_total": len(self.skipped),
            "by_status": dict(sorted(by_status.items())),
            "by_label": dict(sorted(by_label.items())),
            "by_source": dict(sorted(by_source.items())),
        }

    def write_artifacts(
        self, output_dir: str | Path = CONTINUOUS_LEARNING_DIR
    ) -> dict[str, str]:
        target = Path(output_dir)
        target.mkdir(parents=True, exist_ok=True)
        paths = {
            "candidate_samples": str(target / "candidate_samples.jsonl"),
            "review_queue": str(target / "review_queue.jsonl"),
            "approved_samples": str(target / "approved_samples.jsonl"),
            "industry_knowhow": str(target / "industry_knowhow.jsonl"),
            "manifest": str(target / "manifest.json"),
        }
        _write_jsonl(paths["candidate_samples"], [s.to_dict() for s in self.samples.values()])
        _write_jsonl(
            paths["review_queue"],
            [s.to_dict() for s in self.samples.values() if s.status == "candidate"],
        )
        _write_jsonl(
            paths["approved_samples"],
            [s.to_dict() for s in self.samples.values() if s.status == "approved"],
        )
        _write_jsonl(
            paths["industry_knowhow"],
            [unit.to_dict() for unit in self.knowledge_units.values()],
        )
        manifest = {
            "generated_at": _now_iso(),
            "label_set": INTENT_LABELS,
            "label_set_sha256": _stable_id(*INTENT_LABELS),
            "min_confidence": self.min_confidence,
            "stats": self.stats(),
            "skipped": self.skipped[:200],
            "artifacts": paths,
        }
        Path(paths["manifest"]).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return paths

    @staticmethod
    def _sample_rank(sample: LearningSample) -> tuple[int, float]:
        status_rank = {"rejected": 0, "candidate": 1, "approved": 2}
        return status_rank.get(sample.status, 1), sample.confidence


def _write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def collect_user_feedback_samples(memory_path: str | Path | None = None) -> list[LearningSample]:
    """Collect reviewer-backed intent samples from user memory feedback history."""

    source_path = Path(memory_path or os.path.join(BASE_DIR, "user_memory", "memory_store.json"))
    if not source_path.is_file():
        return []
    raw = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return []

    samples: list[LearningSample] = []
    for user_id, memory in raw.items():
        if not isinstance(memory, dict):
            continue
        feedback_history = memory.get("feedback_history")
        if not isinstance(feedback_history, list):
            continue
        for idx, record in enumerate(feedback_history):
            if not isinstance(record, dict):
                continue
            text = _normalize_text(record.get("message"))
            if not text:
                continue
            feedback = str(record.get("user_feedback") or "").strip()
            recognized = normalize_intent_label(record.get("recognized_intent"))
            corrected_raw = record.get("corrected_intent")
            corrected = normalize_intent_label(corrected_raw) if corrected_raw else ""
            if feedback == "corrected" and corrected:
                label = corrected
                confidence = 0.98
                status = "approved"
            elif feedback == "confirmed":
                label = recognized
                confidence = 0.9
                status = "approved"
            elif feedback == "negated":
                label = corrected or infer_intent_label(text)
                confidence = 0.55
                status = "candidate"
            else:
                label = corrected or recognized or infer_intent_label(text)
                confidence = 0.6
                status = "candidate"

            samples.append(
                LearningSample(
                    text=text,
                    label=label,
                    source_type="customer_feedback",
                    source_id=f"{user_id}:{record.get('timestamp') or idx}",
                    confidence=confidence,
                    slots=_coerce_dict(record.get("slots")),
                    metadata={
                        "user_id": user_id,
                        "feedback": feedback,
                        "recognized_intent": recognized,
                        "corrected_intent": corrected,
                        "source_path": str(source_path),
                    },
                    evidence={"feedback_record": record},
                    status=status,
                    created_at=str(record.get("timestamp") or _now_iso()),
                )
            )
    return samples


def _default_ticket_roots() -> list[Path]:
    try:
        from app.services.user_cs_change_request import _store_roots
    except ImportError:
        return []
    return [Path(root) for root in _store_roots()]


def collect_change_request_learning(
    ticket_roots: Iterable[str | Path] | None = None,
) -> tuple[list[LearningSample], list[KnowledgeUnit]]:
    """Collect samples and know-how units from customer-service change tickets."""

    roots = [Path(root) for root in ticket_roots] if ticket_roots else _default_ticket_roots()
    samples: list[LearningSample] = []
    units: list[KnowledgeUnit] = []
    for root in roots:
        for row in _load_jsonish_rows(root):
            ticket_id = _normalize_text(row.get("ticket_no") or row.get("id"))
            title = _normalize_text(row.get("title"))
            desc = _normalize_text(row.get("description"))
            admin_note = _normalize_text(row.get("admin_note"))
            text = _row_text(title, desc, admin_note)
            if not text:
                continue
            explicit_label = (
                row.get("label") or row.get("intent") or row.get("corrected_intent")
            )
            label = (
                normalize_intent_label(explicit_label)
                if explicit_label
                else infer_intent_label(text)
            )
            status_raw = str(row.get("status") or "").strip()
            resolved = status_raw in RESOLVED_TICKET_STATUSES
            approved = resolved and explicit_label and label != "unk"
            samples.append(
                LearningSample(
                    text=text,
                    label=label,
                    source_type="production_ticket",
                    source_id=ticket_id or _stable_id(root, title, desc),
                    confidence=0.92 if approved else 0.65,
                    slots=_coerce_dict(row.get("slots")),
                    metadata={
                        "change_type": row.get("change_type"),
                        "status": status_raw,
                        "priority": row.get("priority"),
                        "market_user_id": row.get("market_user_id"),
                        "source_path": str(root),
                        "needs_review": not approved,
                    },
                    evidence={"ticket": row},
                    status="approved" if approved else "candidate",
                    created_at=str(
                        row.get("updated_at") or row.get("created_at") or _now_iso()
                    ),
                )
            )
            if row.get("change_type") == "bug_fix" or admin_note:
                units.append(
                    KnowledgeUnit(
                        title=title or "客服变更工单",
                        summary=_row_text(desc, admin_note, max_chars=4000),
                        problem=desc or title,
                        resolution=admin_note,
                        source_type="production_ticket",
                        source_id=ticket_id,
                        domain_tags=[
                            str(row.get("change_type") or ""),
                            label,
                            str(row.get("priority") or ""),
                        ],
                        evidence={"ticket": row},
                        created_at=str(
                            row.get("updated_at") or row.get("created_at") or _now_iso()
                        ),
                    )
                )
    return samples, units


def collect_bug_fix_learning(
    bugfix_path: str | Path | None = None,
) -> tuple[list[LearningSample], list[KnowledgeUnit]]:
    """Collect learning artifacts from structured bug-fix JSON/JSONL files."""

    if not bugfix_path:
        return [], []
    samples: list[LearningSample] = []
    units: list[KnowledgeUnit] = []
    for row in _load_jsonish_rows(bugfix_path):
        title = _normalize_text(row.get("title") or row.get("summary"))
        problem = _row_text(row.get("problem"), row.get("description"), row.get("symptom"))
        resolution = _row_text(row.get("resolution"), row.get("fix"), row.get("root_cause"))
        text = _row_text(title, problem, resolution)
        if not text:
            continue
        explicit_label = row.get("label") or row.get("intent")
        label = (
            normalize_intent_label(explicit_label)
            if explicit_label
            else infer_intent_label(text)
        )
        source_id = _normalize_text(
            row.get("source_id") or row.get("issue") or row.get("pr") or row.get("commit")
        )
        approved = bool(resolution and label != "unk")
        samples.append(
            LearningSample(
                text=text,
                label=label,
                source_type="bug_fix",
                source_id=source_id or _stable_id(title, problem, resolution),
                confidence=0.9 if approved else 0.6,
                metadata={
                    "component": row.get("component"),
                    "severity": row.get("severity"),
                    "source_path": str(bugfix_path),
                    "needs_review": not approved,
                },
                evidence={"bug_fix": row},
                status="approved" if approved else "candidate",
                created_at=str(row.get("fixed_at") or row.get("created_at") or _now_iso()),
            )
        )
        units.append(
            KnowledgeUnit(
                title=title or "bug fix",
                summary=_row_text(problem, resolution, max_chars=4000),
                problem=problem,
                resolution=resolution,
                source_type="bug_fix",
                source_id=source_id,
                domain_tags=[
                    label,
                    str(row.get("component") or ""),
                    str(row.get("severity") or ""),
                ],
                evidence={"bug_fix": row},
                created_at=str(row.get("fixed_at") or row.get("created_at") or _now_iso()),
            )
        )
    return samples, units


def collect_distillation_log_samples(
    engine: Any | None = None, *, limit: int = 1000
) -> list[LearningSample]:
    """Collect already persisted distillation_log rows as source-traced samples."""

    if engine is None:
        from app.db import engine as default_engine

        engine = default_engine
    from sqlalchemy import text

    try:
        with engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id, query, intent, slots, confidence, source, created_at
                    FROM distillation_log
                    ORDER BY created_at DESC, id DESC
                    LIMIT :limit
                    """
                ),
                {"limit": int(limit)},
            ).fetchall()
    except RECOVERABLE_ERRORS as exc:
        logger.warning("读取 distillation_log 失败: %s", exc)
        return []

    samples: list[LearningSample] = []
    for row in rows:
        row_map = getattr(row, "_mapping", row)
        confidence = _coerce_float(row_map["confidence"], 0.8)
        samples.append(
            LearningSample(
                text=row_map["query"],
                label=row_map["intent"],
                source_type="distillation_log",
                source_id=str(row_map["id"]),
                confidence=confidence,
                slots=_coerce_dict(row_map["slots"]),
                metadata={
                    "source": row_map["source"],
                    "created_at": str(row_map["created_at"]),
                },
                status="approved" if confidence >= 0.8 else "candidate",
            )
        )
    return samples


def build_continuous_learning_corpus(
    *,
    feedback_path: str | Path | None = None,
    ticket_roots: Iterable[str | Path] | None = None,
    bugfix_path: str | Path | None = None,
    include_defaults: bool = False,
    include_distillation_log: bool = False,
    review_decisions_path: str | Path | None = None,
    min_confidence: float = 0.75,
    distillation_engine: Any | None = None,
) -> ContinuousLearningCorpus:
    """Build a deduplicated, review-gated corpus from operational signals."""

    corpus = ContinuousLearningCorpus(min_confidence=min_confidence)
    if include_distillation_log:
        for sample in collect_distillation_log_samples(distillation_engine):
            corpus.add_sample(sample)
    if include_defaults or feedback_path:
        for sample in collect_user_feedback_samples(feedback_path):
            corpus.add_sample(sample)
    if include_defaults or ticket_roots:
        samples, units = collect_change_request_learning(ticket_roots)
        for sample in samples:
            corpus.add_sample(sample)
        for unit in units:
            corpus.add_knowledge_unit(unit)
    if bugfix_path:
        samples, units = collect_bug_fix_learning(bugfix_path)
        for sample in samples:
            corpus.add_sample(sample)
        for unit in units:
            corpus.add_knowledge_unit(unit)
    corpus.apply_review_decisions(review_decisions_path)
    return corpus


def _read_training_rows(data_path: str | Path | None) -> list[dict[str, Any]]:
    if not data_path:
        return []
    source = Path(data_path)
    if not source.is_file():
        return []
    rows: list[dict[str, Any]] = []
    if source.suffix == ".jsonl":
        with source.open(encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                data = json.loads(line)
                if not isinstance(data, dict):
                    continue
                label = normalize_intent_label(data.get("label"), default="")
                if label not in LABEL_TO_ID:
                    continue
                rows.append(
                    {
                        "text": str(data.get("text", "")),
                        "label": label,
                        "slots": _coerce_dict(data.get("slots")),
                        "source": data.get("source", "base_training_data"),
                    }
                )
    elif source.suffix == ".tsv":
        with source.open(encoding="utf-8") as f:
            next(f, None)
            for raw in f:
                parts = raw.rstrip("\n").split("\t")
                if len(parts) < 2:
                    continue
                label = normalize_intent_label(parts[1], default="")
                if label in LABEL_TO_ID:
                    rows.append(
                        {
                            "text": parts[0],
                            "label": label,
                            "slots": {},
                            "source": "base_training_data",
                        }
                    )
    return rows


def export_continuous_training_data(
    base_data_path: str | Path | None,
    output_path: str | Path,
    corpus: ContinuousLearningCorpus,
    *,
    include_candidates: bool = False,
) -> dict[str, Any]:
    """Merge base data with approved operational samples into one training JSONL."""

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in _read_training_rows(base_data_path):
        key = (_normalize_text(row.get("text")), str(row.get("label")))
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    learning_count = 0
    for sample in corpus.trainable_samples(include_candidates=include_candidates):
        key = (_normalize_text(sample.text), sample.label)
        if key in seen:
            continue
        seen.add(key)
        rows.append(sample.to_training_row())
        learning_count += 1
    _write_jsonl(output_path, rows)
    return {
        "output_path": str(output_path),
        "base_rows": len(rows) - learning_count,
        "learning_rows": learning_count,
        "total_rows": len(rows),
        "include_candidates": include_candidates,
    }


class DistillationDataset(Dataset):
    """蒸馏数据集"""

    def __init__(
        self, texts: list[str], labels: list[int], tokenizer: BertTokenizer, max_length: int = 64
    ):
        self.texts = texts
        self.labels = labels
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self) -> int:
        return len(self.texts)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        text = self.texts[idx]
        label = self.labels[idx]

        encoding = self.tokenizer(
            text,
            max_length=self.max_length,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        )

        return {
            "input_ids": encoding["input_ids"].squeeze(0),
            "attention_mask": encoding["attention_mask"].squeeze(0),
            "labels": torch.tensor(label, dtype=torch.long),
        }


class DistillationTrainer:
    """蒸馏训练器"""

    def __init__(
        self,
        model_name: str = "hfl/chinese-bert-wwm-ext",
        num_labels: int = len(INTENT_LABELS),
        max_length: int = 64,
        learning_rate: float = 2e-5,
        batch_size: int = 16,
        epochs: int = 3,
        warmup_ratio: float = 0.1,
        device: str | None = None,
    ):
        self.model_name = model_name
        self.num_labels = num_labels
        self.max_length = max_length
        self.learning_rate = learning_rate
        self.batch_size = batch_size
        self.epochs = epochs
        self.warmup_ratio = warmup_ratio

        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device

        logger.info("使用设备: %s", self.device)

        os.makedirs(CHECKPOINT_DIR, exist_ok=True)
        os.makedirs(LOG_DIR, exist_ok=True)

        self.tokenizer = None
        self.model = None
        self.train_loader = None
        self.val_loader = None

    def load_data(self, data_path: str) -> tuple[list[str], list[int]]:
        """加载训练数据"""
        texts = []
        labels = []

        if data_path.endswith(".jsonl"):
            with open(data_path, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    text = data.get("text", "")
                    raw_label = data.get("label", "unk")
                    label = normalize_intent_label(raw_label, default="")

                    if label in LABEL_TO_ID:
                        texts.append(text)
                        labels.append(LABEL_TO_ID[label])
        elif data_path.endswith(".tsv"):
            with open(data_path, encoding="utf-8") as f:
                next(f)
                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) >= 2:
                        label = normalize_intent_label(parts[1], default="")
                        if label in LABEL_TO_ID:
                            texts.append(parts[0])
                            labels.append(LABEL_TO_ID[label])

        logger.info("加载数据: %s 条", len(texts))
        return texts, labels

    def prepare_data(self, texts: list[str], labels: list[int], val_ratio: float = 0.2):
        """准备训练和验证数据"""
        label_counts = Counter(labels)
        can_stratify = (
            len(label_counts) >= 10
            and len(texts) > 100
            and min(label_counts.values(), default=0) >= 2
        )
        if can_stratify:
            train_texts, val_texts, train_labels, val_labels = train_test_split(
                texts, labels, test_size=val_ratio, random_state=42, stratify=labels
            )
        else:
            train_texts, val_texts, train_labels, val_labels = train_test_split(
                texts, labels, test_size=val_ratio, random_state=42
            )

        logger.info("训练集: %s 条, 验证集: %s 条", len(train_texts), len(val_texts))

        self.tokenizer = BertTokenizer.from_pretrained(self.model_name)

        train_dataset = DistillationDataset(
            train_texts, train_labels, self.tokenizer, self.max_length
        )
        val_dataset = DistillationDataset(val_texts, val_labels, self.tokenizer, self.max_length)

        self.train_loader = DataLoader(train_dataset, batch_size=self.batch_size, shuffle=True)
        self.val_loader = DataLoader(val_dataset, batch_size=self.batch_size)

        self.model = BertForSequenceClassification.from_pretrained(
            self.model_name,
            num_labels=self.num_labels,
            id2label=ID_TO_LABEL,
            label2id=LABEL_TO_ID,
        )
        self.model.to(self.device)

    def train_epoch(self, optimizer, scheduler) -> float:
        """训练一个 epoch"""
        self.model.train()
        total_loss = 0
        correct = 0
        total = 0

        for batch in self.train_loader:
            optimizer.zero_grad()

            input_ids = batch["input_ids"].to(self.device)
            attention_mask = batch["attention_mask"].to(self.device)
            labels = batch["labels"].to(self.device)

            outputs = self.model(input_ids=input_ids, attention_mask=attention_mask, labels=labels)
            loss = outputs.loss
            logits = outputs.logits

            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()

            total_loss += loss.item()
            preds = torch.argmax(logits, dim=1)
            correct += (preds == labels).sum().item()
            total += labels.size(0)

        avg_loss = total_loss / len(self.train_loader)
        accuracy = correct / total
        return avg_loss, accuracy

    @torch.no_grad()
    def evaluate(self) -> dict[str, float]:
        """评估模型"""
        self.model.eval()
        total_loss = 0
        all_preds = []
        all_labels = []

        for batch in self.val_loader:
            input_ids = batch["input_ids"].to(self.device)
            attention_mask = batch["attention_mask"].to(self.device)
            labels = batch["labels"].to(self.device)

            outputs = self.model(input_ids=input_ids, attention_mask=attention_mask, labels=labels)
            loss = outputs.loss
            logits = outputs.logits

            total_loss += loss.item()
            preds = torch.argmax(logits, dim=1)

            all_preds.extend(preds.cpu().numpy())
            all_labels.extend(labels.cpu().numpy())

        avg_loss = total_loss / len(self.val_loader)
        accuracy = accuracy_score(all_labels, all_preds)

        return {
            "val_loss": avg_loss,
            "val_accuracy": accuracy,
            "preds": all_preds,
            "labels": all_labels,
        }

    def save_checkpoint(self, path: str, epoch: int, best: bool = False):
        """保存检查点"""
        self.model.save_pretrained(path)
        self.tokenizer.save_pretrained(path)

        config = {
            "model_name": self.model_name,
            "num_labels": self.num_labels,
            "id2label": ID_TO_LABEL,
            "label2id": LABEL_TO_ID,
            "label_set_sha256": _stable_id(*INTENT_LABELS),
            "max_length": self.max_length,
            "epoch": epoch,
            "best": best,
            "saved_at": datetime.now().isoformat(),
        }

        with open(os.path.join(path, "train_config.json"), "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        with open(os.path.join(path, "intent_labels.json"), "w", encoding="utf-8") as f:
            json.dump(
                {"labels": INTENT_LABELS, "id2label": ID_TO_LABEL, "label2id": LABEL_TO_ID},
                f,
                ensure_ascii=False,
                indent=2,
            )

        vocab_path = os.path.join(CHECKPOINT_DIR, "vocab.json")
        with open(vocab_path, "w", encoding="utf-8") as f:
            json.dump({"id2label": ID_TO_LABEL, "label2id": LABEL_TO_ID}, f, ensure_ascii=False)

        logger.info("保存检查点到: %s", path)

    def train(self, data_path: str, output_dir: str = CHECKPOINT_DIR):
        """完整训练流程"""
        texts, labels = self.load_data(data_path)

        if len(texts) < 10:
            logger.error("训练数据不足，至少需要 10 条数据")
            return

        self.prepare_data(texts, labels)

        optimizer = AdamW(self.model.parameters(), lr=self.learning_rate, weight_decay=0.01)

        total_steps = len(self.train_loader) * self.epochs
        warmup_steps = int(total_steps * self.warmup_ratio)

        scheduler = get_linear_schedule_with_warmup(
            optimizer, num_warmup_steps=warmup_steps, num_training_steps=total_steps
        )

        best_accuracy = 0
        best_epoch = 0

        for epoch in range(1, self.epochs + 1):
            logger.info("\n=== Epoch %s/%s ===", epoch, self.epochs)

            train_loss, train_acc = self.train_epoch(optimizer, scheduler)
            logger.info(f"训练损失: {train_loss:.4f}, 训练准确率: {train_acc:.4f}")  # noqa: G004

            eval_result = self.evaluate()
            logger.info(
                f"验证损失: {eval_result['val_loss']:.4f}, 验证准确率: {eval_result['val_accuracy']:.4f}"  # noqa: G004
            )

            last_checkpoint = os.path.join(output_dir, "last.pt")
            self.save_checkpoint(last_checkpoint, epoch, best=False)

            if eval_result["val_accuracy"] > best_accuracy:
                best_accuracy = eval_result["val_accuracy"]
                best_epoch = epoch
                best_checkpoint = os.path.join(output_dir, "best.pt")
                self.save_checkpoint(best_checkpoint, epoch, best=True)

            unique_labels = sorted(set(eval_result["labels"]) | set(eval_result["preds"]))
            label_names = [ID_TO_LABEL[i] for i in unique_labels]
            report = classification_report(
                eval_result["labels"],
                eval_result["preds"],
                labels=unique_labels,
                target_names=label_names,
                zero_division=0,
            )
            logger.info("\n分类报告:\n%s", report)

        logger.info(f"\n训练完成! 最佳验证准确率: {best_accuracy:.4f} (Epoch {best_epoch})")  # noqa: G004

        log_path = os.path.join(
            LOG_DIR, f"training_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "best_accuracy": best_accuracy,
                    "best_epoch": best_epoch,
                    "total_epochs": self.epochs,
                    "data_path": data_path,
                    "model_name": self.model_name,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )


def main():
    parser = argparse.ArgumentParser(description="蒸馏训练工具")
    parser.add_argument("--data", type=str, default=None, help="训练数据路径")
    parser.add_argument(
        "--model", type=str, default="hfl/chinese-bert-wwm-ext", help="预训练模型名称"
    )
    parser.add_argument("--epochs", type=int, default=3, help="训练轮数")
    parser.add_argument("--batch_size", type=int, default=16, help="批大小")
    parser.add_argument("--lr", type=float, default=2e-5, help="学习率")
    parser.add_argument("--max_length", type=int, default=64, help="最大序列长度")
    parser.add_argument("--output", type=str, default=None, help="输出目录")
    parser.add_argument(
        "--learn-from-defaults",
        action="store_true",
        help="从默认用户反馈和客服变更工单目录构建持续学习语料",
    )
    parser.add_argument(
        "--learn-from-feedback",
        type=str,
        default=None,
        help="用户反馈 memory JSON",
    )
    parser.add_argument(
        "--learn-from-tickets",
        action="append",
        default=[],
        help="客服/生产工单 JSON 或目录，可重复传入",
    )
    parser.add_argument(
        "--learn-from-bugfixes",
        type=str,
        default=None,
        help="bug 修复 JSON/JSONL",
    )
    parser.add_argument(
        "--learn-from-distillation-log",
        action="store_true",
        help="把数据库 distillation_log 中未外部化的样本纳入候选语料",
    )
    parser.add_argument(
        "--review-decisions",
        type=str,
        default=None,
        help="审核决策 JSON/JSONL",
    )
    parser.add_argument(
        "--learning-output",
        type=str,
        default=None,
        help="持续学习语料和 manifest 输出目录",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.75,
        help="自动进入训练集的最低置信度",
    )
    parser.add_argument(
        "--include-candidates",
        action="store_true",
        help="将候选样本也写入连续训练数据（默认只写 approved）",
    )
    parser.add_argument(
        "--review-only",
        action="store_true",
        help="只生成候选集/审核队列/know-how manifest，不启动模型训练",
    )

    args = parser.parse_args()

    data_path = args.data
    if data_path is None:
        data_path = get_distillation_training_data_path()

    learning_requested = any(
        [
            args.learn_from_defaults,
            args.learn_from_feedback,
            args.learn_from_tickets,
            args.learn_from_bugfixes,
            args.learn_from_distillation_log,
            args.review_decisions,
        ]
    )
    if learning_requested:
        learning_output = args.learning_output or CONTINUOUS_LEARNING_DIR
        corpus = build_continuous_learning_corpus(
            feedback_path=args.learn_from_feedback,
            ticket_roots=args.learn_from_tickets or None,
            bugfix_path=args.learn_from_bugfixes,
            include_defaults=args.learn_from_defaults,
            include_distillation_log=args.learn_from_distillation_log,
            review_decisions_path=args.review_decisions,
            min_confidence=args.min_confidence,
        )
        artifacts = corpus.write_artifacts(learning_output)
        merged_data_path = os.path.join(learning_output, CONTINUOUS_TRAINING_DATA_NAME)
        base_data_path = data_path if os.path.exists(data_path) else None
        merge_stats = export_continuous_training_data(
            base_data_path,
            merged_data_path,
            corpus,
            include_candidates=args.include_candidates,
        )
        logger.info(
            "持续学习语料已生成: samples=%s, knowhow=%s, training_rows=%s",
            corpus.stats()["samples_total"],
            corpus.stats()["knowledge_units_total"],
            merge_stats["total_rows"],
        )
        logger.info("审核队列: %s", artifacts["review_queue"])
        if args.review_only:
            return {
                "artifacts": artifacts,
                "merge_stats": merge_stats,
                "corpus_stats": corpus.stats(),
            }
        data_path = merged_data_path

    if not os.path.exists(data_path):
        logger.error("训练数据不存在: %s", data_path)
        logger.info(
            "请先运行数据采集脚本，或使用 --learn-from-defaults/"
            "--learn-from-feedback 构建持续学习语料"
        )
        return

    output_dir = args.output or CHECKPOINT_DIR

    trainer = DistillationTrainer(
        model_name=args.model,
        max_length=args.max_length,
        learning_rate=args.lr,
        batch_size=args.batch_size,
        epochs=args.epochs,
    )

    trainer.train(data_path=data_path, output_dir=output_dir)


if __name__ == "__main__":
    main()


# NEURO-DDD: 为 Services 层类添加 instrumentation
from app.neuro_bus.neuro_service_instrumentation import instrument_service_layer_class

instrument_service_layer_class(DistillationTrainer, "app.services.distillation_trainer")
