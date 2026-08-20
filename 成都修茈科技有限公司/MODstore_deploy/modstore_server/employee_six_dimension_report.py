"""Shared grading and finalization for six-dimension employee reports."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

SIX_DIMENSION_KEYS = (
    "requirement_clarity",
    "pack_compliance",
    "code_robustness",
    "executability",
    "workflow_connectivity",
    "domain_delivery",
)
DIMENSION_LABELS_ZH = {
    "requirement_clarity": "需求理解",
    "pack_compliance": "包体合规",
    "code_robustness": "代码健壮",
    "executability": "可执行性",
    "workflow_connectivity": "流程贯通",
    "domain_delivery": "领域交付",
}
DIMENSION_DESCRIPTIONS_ZH = {
    "requirement_clarity": "需求是否被正确理解：brief 净化、结构化规格与 Word/资产管线识别是否一致。",
    "pack_compliance": "manifest 可读性、artifact 类型、员工声明字段与 validate 硬错误。",
    "code_robustness": "Python 编译、包体一致性、mod 沙箱轻量校验结果。",
    "executability": "handlers 契约、独立 zipapp 自检、目录登记与领域 runtime（如 Word convert）。",
    "workflow_connectivity": "员工包登记、工作流结构校验与真实员工调用（仅 pack_plus_workflow）。",
    "domain_delivery": "与所选管线（Word 全量提取 / 资产 direct_python / LLM）匹配的交付能力。",
}
DIMENSION_WEIGHTS = {
    "requirement_clarity": 1.0,
    "pack_compliance": 1.2,
    "code_robustness": 1.0,
    "executability": 1.5,
    "workflow_connectivity": 1.2,
    "domain_delivery": 1.3,
}
CRITICAL_DIMENSION_KEYS = frozenset({"executability", "pack_compliance", "domain_delivery"})
PASS_OVERALL = 70.0
PASS_EACH_DIM = 50.0
PASS_CRITICAL_DIM = 60.0
GRADE_TIERS: Tuple[Tuple[str, str, float], ...] = (
    ("S", "S级·卓越", 92.0),
    ("A", "A级·优秀", 85.0),
    ("B", "B级·良好", 78.0),
    ("P", "平级·达标", 70.0),
    ("C", "C级·合格", 60.0),
    ("D", "D级·待改进", 50.0),
    ("F", "F级·风险", 40.0),
    ("G", "G级·不可用", 0.0),
)
GRADE_SCALE_DOC = {
    "S": "92–100：卓越，可直接交付",
    "A": "85–91.9：优秀",
    "B": "78–84.9：良好",
    "P": "70–77.9：平级达标（达到流水线通过线）",
    "C": "60–69.9：合格但有明显短板",
    "D": "50–59.9：待改进",
    "F": "40–49.9：高风险",
    "G": "0–39.9 或关键维未达标：不可用",
}


def clamp_score(score: float) -> int:
    return max(0, min(100, int(round(score))))


def score_to_grade(score: float, *, force_g: bool = False) -> Dict[str, str]:
    if force_g:
        return {"code": "G", "label": "G级·不可用"}
    for code, label, minimum in GRADE_TIERS:
        if float(score) >= minimum:
            return {"code": code, "label": label}
    return {"code": "G", "label": "G级·不可用"}


def dim_entry(
    key: str,
    score: int,
    reasons: List[str],
    *,
    description: Optional[str] = None,
    force_g: bool = False,
) -> Dict[str, Any]:
    grade = score_to_grade(score, force_g=force_g)
    return {
        "score": score,
        "grade": grade["code"],
        "grade_label": grade["label"],
        "label": DIMENSION_LABELS_ZH.get(key, key),
        "description": description or DIMENSION_DESCRIPTIONS_ZH.get(key, ""),
        "reasons": reasons[:6],
    }


def finalize_dimension_report(
    dims: Dict[str, Dict[str, Any]],
    pipeline_label: str,
    *,
    scoring_source: str = "deterministic",
) -> Dict[str, Any]:
    weighted_sum = 0.0
    weight_total = 0.0
    for key in SIX_DIMENSION_KEYS:
        weight = float(DIMENSION_WEIGHTS.get(key, 1.0))
        weighted_sum += weight * float(dims[key]["score"])
        weight_total += weight
    overall = round(weighted_sum / weight_total, 1) if weight_total else 0.0
    failed_dims = [key for key in SIX_DIMENSION_KEYS if dims[key]["score"] < PASS_EACH_DIM]
    critical_failed_dims = [
        key for key in CRITICAL_DIMENSION_KEYS if dims[key]["score"] < PASS_CRITICAL_DIM
    ]
    passed = overall >= PASS_OVERALL and not failed_dims
    critical_failed = bool(critical_failed_dims) or not passed
    for key in critical_failed_dims:
        grade = score_to_grade(dims[key]["score"], force_g=True)
        dims[key]["grade"] = grade["code"]
        dims[key]["grade_label"] = grade["label"]
    overall_grade = score_to_grade(overall, force_g=critical_failed)
    if critical_failed and overall_grade["code"] not in ("F", "G"):
        overall_grade = score_to_grade(min(overall, 39.9), force_g=True)
    return {
        "dimensions": dims,
        "overall_score": overall,
        "overall_grade": overall_grade["code"],
        "overall_grade_label": overall_grade["label"],
        "dimension_grades": {key: dims[key].get("grade") for key in SIX_DIMENSION_KEYS},
        "passed": passed,
        "critical_failed": critical_failed,
        "failed_dimensions": failed_dims,
        "critical_dimensions": list(CRITICAL_DIMENSION_KEYS),
        "weights": dict(DIMENSION_WEIGHTS),
        "pipeline_label": pipeline_label,
        "grade_scale": dict(GRADE_SCALE_DOC),
        "pass_thresholds": {
            "overall": PASS_OVERALL,
            "each_dimension": PASS_EACH_DIM,
            "critical_dimension": PASS_CRITICAL_DIM,
        },
        "scoring_source": scoring_source,
    }
