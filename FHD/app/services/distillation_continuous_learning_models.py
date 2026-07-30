"""Continuous distillation learning corpus builders and exporters."""

from __future__ import annotations

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

from app.utils.distillation_paths import get_distillation_root_dir
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

logger = logging.getLogger(__name__)

INTENT_LABELS = list(RUNTIME_INTENT_LABELS)
LABEL_TO_ID = {label: idx for idx, label in enumerate(INTENT_LABELS)}

DISTILL_DIR = get_distillation_root_dir()

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
        return self.status in TRAINABLE_STATUSES and bool(self.text) and self.label in LABEL_TO_ID

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
            sample_id = str(row.get("sample_id") or row.get("learning_sample_id") or "").strip()
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

    def write_artifacts(self, output_dir: str | Path = CONTINUOUS_LEARNING_DIR) -> dict[str, str]:
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
