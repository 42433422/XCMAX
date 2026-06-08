# 员工包脚手架：部门能力预设（`employee_ai_scaffold`）

[`employee_ai_scaffold.py`](../modstore_server/employee_ai_scaffold.py) 在 **`employee.capabilities` 为空** 时会依次尝试：

1. LLM JSON 可选字段 **`department_preset`**（见下表键名）
2. 关键词启发（SEO / 售后 / 文档等，见源码 `_default_capabilities`）
3. 通用默认：`task.analyze`、`llm.markdown`、`workflow.assist`

源码中的权威列表见 [`employee_scaffold_presets.py`](../modstore_server/employee_scaffold_presets.py) 内 **`DEPARTMENT_PRESETS`**。

## 预设键一览

| `department_preset` | 中文标签 | 默认能力（节选） |
|---------------------|----------|------------------|
| `design` | 设计与创意 | `ux.copy_review`, `brand.guide_check`, … |
| `engineering` | 研发工程 | `code.review`, `bug.triage`, … |
| `qa` | 测试与质量 | `test.plan_draft`, `regression.checklist`, … |
| `product` | 产品与需求 | `prd.outline`, `acceptance.criteria`, … |
| `operations` | 运营 | `campaign.checklist`, `content.calendar_hint`, … |
| `marketing` | 市场增长 | `copy.variations`, `landing.hints`, `seo.brief`, … |
| `sales` | 销售与客户拓展 | `pitch.outline`, `objection.handling`, … |
| `support` | 客户支持 | `ticket.classify`, `customer.reply`, … |
| `data` | 数据与分析 | `sql.explain_hint`, `metric.definition`, … |
| `security` | 安全与合规 | `threat.model_sketch`, `secret.handling_check`, … |
| `hr` | 人力资源 | `jd.outline`, `interview.rubric`, … |
| `legal_ops` | 法务与条款运营 | `clause.plain_language`, `risk.flag_hint`, … |
| `devops` | 运维与发布 | `deploy.runbook_hint`, `rollback.checklist`, … |
| `finance` | 财务与对账 | `invoice.field_check`, `reconciliation.hints`, … |
| `research` | 研究与竞品 | `competitor.matrix`, `source.trace_hint`, … |

每项预设另有 **`skill_hints`**（给人读的设计说明，不自动写入 manifest；可作为提示词补充）。

## LLM JSON 示例

在 **`capabilities` 留空** 时带上部门键：

```json
{
  "id": "growth-copy-helper",
  "name": "增长文案助手",
  "version": "1.0.0",
  "description": "生成与审核营销文案草案",
  "department_preset": "marketing",
  "employee": {
    "id": "growth-copy",
    "label": "增长文案",
    "capabilities": []
  }
}
```

若 **`employee.capabilities` 非空**，以模型给出的列表为准，**不会**再套用预设能力数组。

## 与 FHD 文档的关系

[FHD 员工形态说明](./fhd-employee-composition.md)描述宿主侧 A/B/C 三类概念；**本文仅描述 MODstore 脚手架的默认能力标签**，二者交叉引用，职责分离。
