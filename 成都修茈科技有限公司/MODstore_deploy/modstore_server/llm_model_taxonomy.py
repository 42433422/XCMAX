"""模型 ID → 展示分类（启发式，可随厂商命名迭代）。"""

from __future__ import annotations

from typing import Dict, List, Literal, Tuple, cast

from modstore_server import model_registry

Category = Literal["llm", "vlm", "image", "video", "other"]

CATEGORY_ORDER: Tuple[Category, ...] = ("llm", "vlm", "image", "video", "other")


def category_labels_zh() -> Dict[str, str]:
    return {
        "llm": "语言大模型 (LLM)",
        "vlm": "视觉 / 多模态 (VLM)",
        "image": "图像生成",
        "video": "视频生成",
        "other": "其他",
    }


def supports_trial_chat(category: str) -> bool:
    return category in ("llm", "vlm")


def classify_model(provider: str, model_id: str) -> Category:
    """模型 id → 展示分类。分类规则（关键词表/厂商专属规则）来自模型统一 SSOT
    的 classification 块，委托共享 model_registry.classify —— 与 FHD
    app/infrastructure/llm/model_registry.classify 同算法、同规则（已逐字对拍）。
    新增/调整分类关键词：改 FHD/config/models.yaml#classification + `ssot sync models --apply`。"""
    return cast(Category, model_registry.classify(provider, model_id))


def _category_sort_key(cat: str) -> int:
    try:
        return CATEGORY_ORDER.index(cat)  # type: ignore[arg-type]
    except ValueError:
        return len(CATEGORY_ORDER)


def build_models_detailed(provider: str, model_ids: List[str]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for mid in model_ids:
        mid = (mid or "").strip()
        if not mid:
            continue
        rows.append({"id": mid, "category": classify_model(provider, mid)})
    rows.sort(key=lambda r: (_category_sort_key(r["category"]), r["id"]))
    return rows


def media_counts_from_detailed(models_detailed: List[Dict[str, str]]) -> Dict[str, int]:
    """按 taxonomy 分类统计，供钱包磁贴展示生图/生视频能力。"""
    counts: Dict[str, int] = {c: 0 for c in CATEGORY_ORDER}
    for md in models_detailed or []:
        cat = str(md.get("category") or "other")
        if cat not in counts:
            cat = "other"
        counts[cat] += 1
    return counts
