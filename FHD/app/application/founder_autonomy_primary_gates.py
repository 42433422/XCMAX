"""Founder, system, customer, and code autonomy score gates."""

from __future__ import annotations

from typing import Any, Mapping

from app.application.founder_autonomy_support import ScoreGate, _as_int


def build_primary_gate_sets(
    facts: Mapping[str, Any],
) -> tuple[list[ScoreGate], list[ScoreGate], list[ScoreGate], list[ScoreGate]]:
    surfaces = facts["surfaces"]
    workforce_ready = facts["workforce_ready"]
    assigned_employees = facts["assigned_employees"]
    planned = facts["planned"]
    proven_employees = facts["proven_employees"]
    shell_employees = facts["shell_employees"]
    goals_total = facts["goals_total"]
    runtime = facts["runtime"]
    council_ready = facts["council_ready"]
    strategic_council = facts["strategic_council"]
    pending_total = facts["pending_total"]
    governance_clear = facts["governance_clear"]
    cron_ok = facts["cron_ok"]
    runtime_fresh = facts["runtime_fresh"]
    latest_age = facts["latest_age"]
    runtime_provenance_ok = facts["runtime_provenance_ok"]
    runtime_provenance = facts["runtime_provenance"]
    contract_trusted = facts["contract_trusted"]
    contract_status = facts["contract_status"]
    workforce_assigned = facts["workforce_assigned"]
    wrote = facts["wrote"]
    reviewed = facts["reviewed"]
    qa_passed = facts["qa_passed"]
    gates_clear = facts["gates_clear"]
    latest_completed = facts["latest_completed"]
    has_open_run = facts["has_open_run"]
    latest_complete = facts["latest_complete"]
    value_ledger_ready = facts["value_ledger_ready"]
    production_value_verified = facts["production_value_verified"]
    paid_count = facts["paid_count"]
    paid_amount = facts["paid_amount"]
    customer_goals = facts["customer_goals"]
    delivered_count = facts["delivered_count"]
    outcome_verified = facts["outcome_verified"]
    paid_delivery_count = facts["paid_delivery_count"]
    paid_acceptance_count = facts["paid_acceptance_count"]
    merged = facts["merged"]
    real_deploy_dispatched = facts["real_deploy_dispatched"]
    accepted_deploys = facts["accepted_deploys"]
    deploy_verified = facts["deploy_verified"]

    founder_gates = [
        ScoreGate(
            "cockpit",
            "统一驾驶舱",
            15,
            bool(surfaces.get("founder_cockpit")),
            "管理端已注册创始人驾驶舱",
            "建立创始人统一驾驶舱",
            "source_capability",
        ),
        ScoreGate(
            "approval",
            "审批中心",
            10,
            bool(surfaces.get("approval_center")),
            "审批中心已对管理员开放",
            "将审批中心加入管理端并解除路由阻断",
            "source_capability",
        ),
        ScoreGate(
            "knowledge",
            "知识库",
            15,
            bool(surfaces.get("knowledge_base")),
            "Persy 知识库已对管理员开放",
            "将知识库加入管理端",
            "source_capability",
        ),
        ScoreGate(
            "employees",
            "AI 员工真实工作",
            15,
            bool(surfaces.get("ai_employees")) and workforce_ready,
            f"已排工 {assigned_employees}/{planned}，有回执 {proven_employees}/{planned}，空壳 {shell_employees}",
            "让至少 80% 编制产生真实运行回执，并清零空壳/无效 handler",
            "local_runtime",
        ),
        ScoreGate(
            "goals",
            "Goals",
            10,
            bool(surfaces.get("goals")) and goals_total > 0,
            f"目标条目 {int(goals_total)}",
            "接入可追踪 Goals 与完成率",
            "deployed_runtime",
        ),
        ScoreGate(
            "loops",
            "Loops",
            15,
            bool(surfaces.get("loops")) and bool(runtime.get("ok")),
            f"Loop runtime 在线，最近事件 {runtime.get('latest_event_at') or '未知'}",
            "接入实时 Loop 账本",
            "local_runtime",
        ),
        ScoreGate(
            "council",
            "Persy/Para/Retort 战略三席",
            10,
            council_ready,
            f"已验证协同回执 {int(_as_int(strategic_council.get('verified_receipt_count')))} 条",
            "让 Persy 事实、Para Goal/Loop 与 Retort 质疑形成同一可验证回执",
            "deployment_runtime",
        ),
        ScoreGate(
            "attention",
            "只看例外",
            10,
            pending_total <= 5 and governance_clear,
            f"待人工/会议决策 {pending_total}，治理门禁健康",
            "将待决策压到 5 项内并清除治理 hold",
            "deployed_runtime",
        ),
    ]

    system_gates = [
        ScoreGate(
            "cron",
            "定时调度",
            10,
            cron_ok,
            str(runtime.get("cron") or ""),
            "注册并启用 7x24 调度",
            "local_runtime",
        ),
        ScoreGate(
            "fresh",
            "持续心跳",
            10,
            runtime_fresh,
            f"最近事件距今 {latest_age:.1f} 小时" if latest_age is not None else "",
            "最近 6 小时内必须有运行事件",
            "local_runtime",
        ),
        ScoreGate(
            "provenance",
            "运行来源可信",
            15,
            runtime_provenance_ok,
            str(runtime_provenance.get("source") or "verified runtime provenance"),
            "用干净的精确提交和发布清单重建运行时；不得用心跳绕过来源门禁",
            "local_runtime",
        ),
        ScoreGate(
            "contract",
            "运行契约",
            10,
            contract_trusted,
            str(contract_status.get("detail") or "runtime contract trusted"),
            "修复管理端与 Loop runtime 契约",
            "local_runtime",
        ),
        ScoreGate(
            "staffing",
            "员工真实排工",
            15,
            workforce_assigned and shell_employees == 0,
            f"已排工 {assigned_employees}/{planned}，空壳 {shell_employees}",
            "为全员绑定职责、触发器、风险门禁与验收回执",
            "source_capability",
        ),
        ScoreGate(
            "execution",
            "无人值守执行",
            15,
            wrote and reviewed and qa_passed,
            "编写/独立评审/QA 均有成功事件",
            "跑通编写、独立评审与 QA",
            "local_runtime",
        ),
        ScoreGate(
            "gate_clear",
            "自治门禁",
            10,
            gates_clear,
            "当前 active_gates.ok=true",
            "清除 active gate 阻塞",
            "local_runtime",
        ),
        ScoreGate(
            "completed",
            "连续完成",
            15,
            latest_completed and not has_open_run,
            str(latest_complete.get("status") or ""),
            "完成当前运行且不留下悬挂 run",
            "local_runtime",
        ),
    ]

    customer_gates = [
        ScoreGate(
            "value_ledger",
            "价值账本",
            15,
            value_ledger_ready,
            "权威只追加客户价值账本可读",
            "接入可排除测试、内部与退款记录的权威价值账本",
            "local_runtime",
        ),
        ScoreGate(
            "paid",
            "真实付费",
            25,
            production_value_verified,
            f"第三方校验付费 {paid_count} 笔 / {paid_amount} 分",
            "取得带第三方交易证明的真实客户付费；测试单不计入",
            "production_value",
        ),
        ScoreGate(
            "goals",
            "客户目标",
            15,
            customer_goals > 0,
            f"客户目标 {customer_goals} 项",
            "将外部客户目标写入客户价值账本",
            "deployed_runtime",
        ),
        ScoreGate(
            "delivered",
            "目标交付",
            20,
            delivered_count > 0,
            f"不可变产物交付 {delivered_count} 项",
            "形成与客户目标关联且带制品 SHA-256 的交付回执",
            "deployed_runtime",
        ),
        ScoreGate(
            "capacity",
            "交付编制",
            10,
            workforce_assigned and shell_employees == 0,
            f"已排工 {assigned_employees}/{planned}",
            "补齐真实任务合同并清除空壳员工",
            "source_capability",
        ),
        ScoreGate(
            "outcome",
            "结果而非身份",
            15,
            outcome_verified,
            f"付费交付闭环 {paid_delivery_count} 项；客户验收 {paid_acceptance_count} 项",
            "把真实付费关联到不可变系统产出；继续取得客户验收回执",
            "production_value",
        ),
    ]

    code_gates = [
        ScoreGate(
            "write",
            "自己写",
            15,
            wrote,
            "code 员工步骤成功",
            "触发真实代码实现步骤",
            "local_runtime",
        ),
        ScoreGate(
            "review",
            "自己审",
            15,
            reviewed,
            "独立 review 员工步骤成功",
            "保留独立评审证据",
            "local_runtime",
        ),
        ScoreGate(
            "qa", "自己验", 15, qa_passed, "独立 QA 步骤成功", "保留独立 QA 证据", "local_runtime"
        ),
        ScoreGate(
            "merge",
            "自己合",
            20,
            merged,
            "账本存在 completed_merged",
            "让最新合格变更自动合并",
            "local_runtime",
        ),
        ScoreGate(
            "dispatch",
            "自己发版",
            15,
            real_deploy_dispatched,
            f"同链路部署派发 {len(accepted_deploys)} 次",
            "捕获带 run_id、合并 SHA 与 workflow ID 的 staging 派发回执",
            "deployment_runtime",
        ),
        ScoreGate(
            "verify",
            "部署验证",
            20,
            deploy_verified,
            "production 的 workflow、SHA 与制品摘要均已回读验证",
            "在同一 run/SHA 上通过 production workflow 与部署身份校验",
            "deployment_runtime",
        ),
    ]

    return founder_gates, system_gates, customer_gates, code_gates
