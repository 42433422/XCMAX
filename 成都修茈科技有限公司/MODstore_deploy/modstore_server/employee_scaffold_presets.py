"""Department-oriented capability presets for :mod:`employee_ai_scaffold`.

Used when ``employee.capabilities`` from the LLM is empty and/or when the LLM
sets ``department_preset`` to one of the keys below.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

# Keys are stable ASCII identifiers for prompts and APIs.
DEPARTMENT_PRESETS: Dict[str, Dict[str, Any]] = {
    "design": {
        "label_zh": "设计与创意",
        "capabilities": ["ux.copy_review", "brand.guide_check", "layout.feedback", "task.analyze"],
        "skill_hints": ["产出可执行的评审清单与修订建议；不确定处标注假设"],
    },
    "engineering": {
        "label_zh": "研发工程",
        "capabilities": ["code.review", "bug.triage", "api.contract_check", "task.analyze"],
        "skill_hints": ["变更影响范围、风险与回滚建议"],
    },
    "qa": {
        "label_zh": "测试与质量",
        "capabilities": [
            "test.plan_draft",
            "regression.checklist",
            "bug.repro_steps",
            "task.analyze",
        ],
        "skill_hints": ["前置条件、期望结果、边界与负面用例"],
    },
    "product": {
        "label_zh": "产品与需求",
        "capabilities": [
            "prd.outline",
            "acceptance.criteria",
            "backlog.prioritize_hint",
            "task.analyze",
        ],
        "skill_hints": ["目标用户、成功指标、范围与非目标"],
    },
    "operations": {
        "label_zh": "运营",
        "capabilities": [
            "campaign.checklist",
            "content.calendar_hint",
            "metrics.readout",
            "task.analyze",
        ],
        "skill_hints": ["渠道、节奏、可量化 KPI"],
    },
    "marketing": {
        "label_zh": "市场增长",
        "capabilities": ["copy.variations", "landing.hints", "seo.brief", "task.analyze"],
        "skill_hints": ["受众、卖点、合规用语注意"],
    },
    "sales": {
        "label_zh": "销售与客户拓展",
        "capabilities": ["pitch.outline", "objection.handling", "crm.note_summary", "task.analyze"],
        "skill_hints": ["下一步动作与跟进要点"],
    },
    "support": {
        "label_zh": "客户支持",
        "capabilities": ["ticket.classify", "customer.reply", "kb.article_outline", "task.analyze"],
        "skill_hints": ["共情、事实核对、升级条件"],
    },
    "data": {
        "label_zh": "数据与分析",
        "capabilities": [
            "sql.explain_hint",
            "metric.definition",
            "dashboard.brief",
            "task.analyze",
        ],
        "skill_hints": ["口径定义、维度与局限性"],
    },
    "security": {
        "label_zh": "安全与合规",
        "capabilities": [
            "threat.model_sketch",
            "secret.handling_check",
            "policy.gap_scan",
            "task.analyze",
        ],
        "skill_hints": ["不编造漏洞编号；建议验证步骤"],
    },
    "hr": {
        "label_zh": "人力资源",
        "capabilities": ["jd.outline", "interview.rubric", "onboarding.checklist", "task.analyze"],
        "skill_hints": ["平等雇佣与隐私边界"],
    },
    "legal_ops": {
        "label_zh": "法务与条款运营",
        "capabilities": [
            "clause.plain_language",
            "risk.flag_hint",
            "changelog.summary",
            "task.analyze",
        ],
        "skill_hints": ["非律师意见免责声明；引用需可追溯"],
    },
    "devops": {
        "label_zh": "运维与发布",
        "capabilities": [
            "deploy.runbook_hint",
            "rollback.checklist",
            "incident.timeline",
            "task.analyze",
        ],
        "skill_hints": ["变更窗口、依赖与健康检查"],
    },
    "finance": {
        "label_zh": "财务与对账",
        "capabilities": [
            "invoice.field_check",
            "reconciliation.hints",
            "budget.variance_note",
            "task.analyze",
        ],
        "skill_hints": ["币种、期间与数据来源"],
    },
    "research": {
        "label_zh": "研究与竞品",
        "capabilities": ["competitor.matrix", "source.trace_hint", "summary.brief", "task.analyze"],
        "skill_hints": ["标注信息时效性与来源"],
    },
}


def list_preset_keys() -> List[str]:
    return sorted(DEPARTMENT_PRESETS.keys())


def resolve_preset_capabilities(department_preset: str | None) -> Tuple[List[str], Dict[str, Any]]:
    """Return (capabilities, meta) for a preset key; meta empty if unknown."""
    key = str(department_preset or "").strip().lower()
    if not key or key not in DEPARTMENT_PRESETS:
        return [], {}
    row = DEPARTMENT_PRESETS[key]
    caps = row.get("capabilities") if isinstance(row.get("capabilities"), list) else []
    out = [str(x).strip()[:128] for x in caps if str(x).strip()]
    return out[:8], {"preset_key": key, "label_zh": row.get("label_zh", "")}
