# Odoo 18 吸收分析（Retort 引擎）— 结论速览

> 生成时间：2026-08-06（UTC）
> 用途：面向非技术读者的简明结论。技术细节见同目录 `absorption_evidence.json`（吸收证据）与 `absorption_tasks.json`（待吸收任务清单）。

## 一句话结论

我们用 Retort 引擎对 **Odoo 18**（全球最流行的开源 ERP）与 **FHD 智能对话**做了一次"吸收深度"分析。结论是：**FHD 的智能对话已经是可靠的"轻量进销存"，但缺 Odoo 那层"真正的 ERP 业务深度"——销售到收款闭环、复式记账、报表中心、多单位/多地址、库存补货预警**，值得吸收，好让对话"说话就能跑通 ERP 全流程"。

## FHD 现状（轻量进销存）

- 已经能管：客户（customers）、产品（products）、原材料（materials）、库存（inventory）、采购（purchase）、财务流水（finance）、出货记录（shipment_records）。
- 缺口：没有**销售订单闭环**、没有**报表工具**、财务只是**流水没有记账**、没有**多单位/多地址/补货预警**。

## Odoo 18 提供了什么（值得吸收）

| 能力 | 通俗解释 | 吸收优先级 |
|------|---------|-----------|
| 销售到收款闭环 | 报价→确认→发货→开票→收款，一个订单全流程推进 | P0 |
| 财务复式记账 | 每笔业务生成"借/贷"对照的记账凭证（如采购→借库存、贷应付） | P0 |
| 报表中心 | 销售/库存/采购/看板，自然语言"出报表"并导出 | P0 |
| Agent 工具注册表扩容 | 让对话能调用销售/报表/记账/补货工具 | P0 |
| 多单位换算 | 同一产品多单位（件/箱/斤），"500 斤"要换算/澄清 | P1 |
| 客户多地址 | 发票地址与送货地址分离 | P1 |
| 库存补货预警 | 库存低于下限自动预警并反问是否补货 | P1 |
| 反问澄清业务化 | 单位/口径/冲销/批量歧义时先问清楚再执行 | P1 |
| 对话路由接入 | 普通/专业对话能路由到新 ERP 工具 | P1 |

## 本次产出

- 9 项待吸收任务（见 `absorption_tasks.json`），每一项都写明了 **Odoo 做法 → FHD 现状 → 吸收到哪个文件 → 验收标准**。
- 吸收落点：新增 `app/db/models/sales.py`、`app/db/models/accounting.py`，扩展 `config/risk_actions.registry.json` 与 `app/services/tools_execution/registry.py`，扩展 `app/application/workflow/clarification_node.py` 与 `normal_chat_dispatch.py`。
- 实际落地由 `.trae/specs/absorb-odoo18-erp-agent/tasks.md` 的 Task 2-8 执行。

## 重要说明

- 本次是**纯研究/分析**：只生成了上面这几份分析产物，**没有修改任何 FHD 业务代码**、没有自动合并、没有跑 git 分支合并。
- Retort 的"维度分数"（五维打分）需要联网的 PaiBi LLM 深度评审，本机未配置，故分数留空（已在分析中标注为 degraded）；吸收结论基于代码证据 + 内置知识给出，不影响任务清单的可用性。
- Odoo 18 的 License 边界门禁（license_gate）已通过，可合法吸收其业务设计与数据模型思路（非直接复制其代码）。