# Excel 质检员

四角色表格闭环（读取员 → 规则映射员 → 模板写入员 → **质检员**）的最后一道门禁，也是规则固化流的判据执行者。**独立对账**：不 import 映射员/写入员任何代码，从契约文件（plan/rules/write_report）与输出 xlsx 本身重算不变量——上游 bug 无法「自证清白」。

- 输入：回填结果 `.xlsx/.xlsm`（上传）+ `payload.plan`/`plan_path`（**必需**）+ 可选 `rules`/`rules_path`、`template_path`（原模板）、`write_report_path`
- 输出：`outputs/qc_report.json`——`verdict`（PASS/WARN/FAIL）+ `blame` 问责路由 + 六节明细

## 六节检查

| 节 | 检查 | fail 问责 |
|---|---|---|
| `conformance` | plan 每条 cell/formula 写入逐格比对（值/公式/number_format）；clear 范围内非计划格无残值；retain_sheets 生效；write_report 自述交叉验证 | `writer_or_plan` |
| `protection` | 提供原模板时 `protected_ranges` 逐格 diff | `writer` |
| `expected` | 三方对账：映射员自述（expected）↔ 从 plan 独立重算 ↔ 从输出文件重算（per_key 数值合计、计划格数）；records_dropped 呈现给人 | `mapper` |
| `formulas` | 全簿扫描 `#REF!` 与悬空 sheet 引用 | `template_or_plan` |
| `traceability` | 重算 rules.json sha256 ↔ `plan.meta.rules_ref`（产物可追溯规则版本） | `pipeline` |
| `structure` | `rules.blocks` 键 ↔ 输出键列实际值（模板重排/规则过期检测） | `rules_stale` |

**第七节 `semantic`（LLM 业务合理性审查）**：宿主提供 `ctx.call_llm` 且 `payload.use_llm` 未关时执行——审查确定性代码看不见的东西：数值是否符合业务常理（异常大/小、负数、超 24h 工时类）、丢弃记录是否可疑（错字/漏人）、无记录块提醒、警告轻重分级；并产出 `human_summary` 给业务人员看的中文摘要。LLM finding 计入 verdict（fail → FAIL，blame=`semantic_llm`）但**不可推翻确定性六节**；`payload.llm_strict=false` 把 LLM 的 fail 降级为 warn（防幻觉阻塞）；`payload.business_context` 可注入业务背景。

缺输入的节标记 `skipped` 并写明原因——**绝不假装通过**。verdict：任一 fail → FAIL；仅 warn → WARN；否则 PASS。员工返回 `ok=true` 表示质检执行成功，质检结论看 `verdict`。

## payload 示例

```json
{
  "file_path": "outputs/filled.xlsx",
  "plan_path": "outputs/plan.json",
  "rules_path": "rules.json",
  "template_path": "考勤模板.xlsx",
  "write_report_path": "outputs/write_report.json"
}
```

## 闭环走向建议

- `blame=writer_or_plan/writer` → 重跑模板写入员（或检查计划与保护区冲突）
- `blame=mapper` → 回炉规则映射员 compile（expected 失真）
- `blame=rules_stale` → 模板已改版，重新 infer 出规则提案给人确认
- `blame=pipeline` → rules.json 版本与计划不一致，检查固化流水
