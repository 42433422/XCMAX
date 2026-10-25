"""Fault, evolution, and alignment autonomy score gates."""

from __future__ import annotations

from typing import Any, Mapping

from app.application.founder_autonomy_support import ScoreGate, _as_int


def build_resilience_gate_sets(
    facts: Mapping[str, Any],
) -> tuple[list[ScoreGate], list[ScoreGate], list[ScoreGate]]:
    incident_triggered = facts["incident_triggered"]
    incident_count = facts["incident_count"]
    participants = facts["participants"]
    repair_started = facts["repair_started"]
    repair_completed = facts["repair_completed"]
    repair_verified = facts["repair_verified"]
    unresolved_dead_letters = facts["unresolved_dead_letters"]
    resolved_dead_letters = facts["resolved_dead_letters"]
    dead_letters_healthy = facts["dead_letters_healthy"]
    proactive_detected = facts["proactive_detected"]
    proactive_count = facts["proactive_count"]
    reusable_knowledge = facts["reusable_knowledge"]
    evolution_implemented = facts["evolution_implemented"]
    evolution_implementation_gap = facts["evolution_implementation_gap"]
    evolution_history = facts["evolution_history"]
    council_ready = facts["council_ready"]
    strategic_council = facts["strategic_council"]
    employee_pack_built = facts["employee_pack_built"]
    modstore_deployed = facts["modstore_deployed"]
    audit_has_rows = facts["audit_has_rows"]
    audit_total = facts["audit_total"]
    audit_available = facts["audit_available"]
    prohibited_clear = facts["prohibited_clear"]
    veto_channel_available = facts["veto_channel_available"]
    veto_pending = facts["veto_pending"]
    veto_rate = facts["veto_rate"]
    governance_clear = facts["governance_clear"]
    governance_gate = facts["governance_gate"]
    contract_trusted = facts["contract_trusted"]

    fault_gates = [
        ScoreGate(
            "sense",
            "故障感知",
            20,
            incident_triggered,
            f"近窗 incident 信号 {incident_count}",
            "接入真实故障信号",
            "local_runtime",
        ),
        ScoreGate(
            "triage",
            "自动分诊",
            15,
            incident_triggered and len(participants) > 0,
            f"参与员工 {len(participants)}",
            "将 incident 绑定责任员工",
            "local_runtime",
        ),
        ScoreGate(
            "repair",
            "自动修复",
            25,
            repair_started,
            "incident 已进入代码修复步骤",
            "从 incident 自动生成并执行修复",
            "local_runtime",
        ),
        ScoreGate(
            "complete",
            "修复落地",
            20,
            repair_completed,
            "incident run 已完成合并",
            "让 incident run 跨过门禁并落地",
            "local_runtime",
        ),
        ScoreGate(
            "verify",
            "恢复验证",
            15,
            repair_verified,
            "恢复/健康验证已写回 incident run",
            "自动验证恢复并关联原 incident",
            "deployment_runtime",
        ),
        ScoreGate(
            "dlq",
            "死信自愈",
            5,
            dead_letters_healthy,
            f"未解决 {unresolved_dead_letters} / 已审计处理 {resolved_dead_letters}",
            "自动重试幂等事件，隔离支付/退款等高影响事件并保留审计",
            "local_runtime",
        ),
    ]

    evolution_gates = [
        ScoreGate(
            "detect",
            "发现缺口",
            15,
            proactive_detected,
            f"主动候选 {proactive_count}",
            "持续采集质量、性能和业务缺口",
            "local_runtime",
        ),
        ScoreGate(
            "knowledge",
            "复用知识",
            15,
            reusable_knowledge,
            "自进化知识库存在 fix/pattern",
            "沉淀并复用 fix/pattern",
            "local_runtime",
        ),
        ScoreGate(
            "implement",
            "实现能力",
            20,
            evolution_implemented,
            "代码与 QA 证据齐全",
            evolution_implementation_gap,
            "local_runtime",
        ),
        ScoreGate(
            "metrics",
            "进化度量",
            10,
            evolution_history > 0,
            f"进化窗口历史 {evolution_history}",
            "积累至少一个真实进化指标窗口",
            "local_runtime",
        ),
        ScoreGate(
            "council",
            "战略三席质疑",
            10,
            council_ready,
            f"Persy/Para/Retort 回执 {int(_as_int(strategic_council.get('verified_receipt_count')))} 条",
            "在部署前绑定知识、Goal/Loop、Retort 意图质疑与 veto",
            "deployment_runtime",
        ),
        ScoreGate(
            "package",
            "能力打包",
            10,
            employee_pack_built,
            "能力已构建 employee_pack",
            "将新能力打包为 employee_pack/Mod",
            "deployment_runtime",
        ),
        ScoreGate(
            "publish",
            "部署更新 MODstore",
            20,
            modstore_deployed,
            "新能力已部署并完成 catalog 安装验证",
            "把能力包部署到 MODstore，并回读安装与版本身份",
            "deployment_runtime",
        ),
    ]

    alignment_gates = [
        ScoreGate(
            "audit",
            "可审计",
            15,
            audit_has_rows,
            f"权威只追加自治审计记录 {audit_total}",
            "让真实自治决策持续写入不可变审计账本",
            "local_runtime",
        ),
        ScoreGate(
            "prohibited",
            "禁止项零漏放",
            25,
            audit_available and prohibited_clear,
            "所有 allow 动作均有独立后验异常证据，未发现 prohibited miss",
            "补齐所有允许动作的独立后验异常覆盖；未知不能当作零漏放",
            "local_runtime",
        ),
        ScoreGate(
            "veto",
            "veto 通道",
            15,
            veto_channel_available,
            f"红线 veto 通道可用，待处理 {veto_pending}",
            "部署并验证管理员红线 approve/reject/veto 通道",
            "deployed_runtime",
        ),
        ScoreGate(
            "rare",
            "低频人工",
            20,
            audit_has_rows and 0 <= veto_rate <= 5,
            f"veto rate {veto_rate:.2f}%",
            "积累真实决策样本，并把 veto rate 压到 5% 以内",
            "deployed_runtime",
        ),
        ScoreGate(
            "governance",
            "治理健康",
            10,
            governance_clear,
            str(governance_gate.get("reason") or "governance healthy"),
            "处理连续治理动作失败",
            "local_runtime",
        ),
        ScoreGate(
            "council",
            "独立质疑门",
            10,
            council_ready,
            "Persy/Para/Retort 三席已在真实部署前共同放行",
            "把 Retort 质疑与 Persy/Para 执行证据接到 veto 门",
            "deployment_runtime",
        ),
        ScoreGate(
            "self_policy",
            "不能自改边界",
            5,
            contract_trusted and audit_available and prohibited_clear,
            "运行契约可信、审计不可变且禁止项后验覆盖完整",
            "锁定自治边界并补齐禁止项后验覆盖",
            "source_capability",
        ),
    ]

    return fault_gates, evolution_gates, alignment_gates
