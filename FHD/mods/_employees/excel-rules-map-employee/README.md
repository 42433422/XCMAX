# Excel 规则映射员

四角色表格闭环（读取员 → **规则映射员** → 模板写入员 → 质检员）的规则中枢：把「哪个 sheet、哪行是表头、哪些列映射、怎么转模板」沉淀成**可版本化的 rules.json**，并把固化规则编译成模板写入员可执行的 **plan.json**。零领域知识——「写什么值」由上游领域算子/人以 records 提供，本员工只决定「哪里写、怎么写」。

## 双动作

### 1. `infer`（默认）：模板 workbook.json → rules.json 提案

输入：读取员读**模板**产出的 `workbook.json`（依赖其 `merged_ranges` / `cells[].formula`）。

推断内容（全部通用启发式，无考勤等领域语义）：

| 字段 | 算法 |
|---|---|
| `template_map.block` | 竖向合并单元格周期性：高度众数 + 起点等差链，跨列投票（如 A/B/C 列 6 行合并 × 151 块） |
| `template_map.header_rows` | 首块行 - 1 |
| `template_map.key_col` | 块首行文本「覆盖率 × 唯一率」最高列（如 C 列姓名） |
| `template_map.blocks` | 每块 `{index, top, key}`（compile 的键 → 行映射） |
| `template_map.calendar` | 表头区 1..N 横向等差数字序列 → 锚列/每日槽数/天数/布局 |
| `template_map.formula_zones` | 块首行公式覆盖率 ≥60% 的连续列区间（如 BR..CG） |
| `formula_templates` | 同列跨块公式拟合：骨架全等 + 数字 token 常数/等差（`ROWS($1:1)→($1:7)` 步进 6 → `base+step×block_index`） |
| `template_map.month_cells` | 表头区 1900..2100 整数 + 同行右侧 1..12 |
| `template_map.clear_zone` | 日历锚列 .. 公式区前一列（低置信，标注待确认） |

输出 `outputs/rules.json` 是**提案**：`evidence.confidences` + `evidence.open_questions` 列出待人确认项（如 bands 多带布局、clear_zone 边界）。骨架不一致/非等差的公式列不拟合、保持保护。

**LLM 精修**（宿主提供 `ctx.call_llm` 且 `payload.use_llm` 未关时）：LLM 基于表头/块文本样本回答 open_questions——提议 bands 多带布局、兜底键列、修 clear_zone 边界。**每条提议必须通过确定性验证**（越界/公式区重叠/覆盖率检查）才采纳；采纳与拒绝全部留痕于 `evidence.llm`，去人工化的同时保持规则可审查。

### 2. `compile`：rules.json + records → plan.json

输入：固化后的 `rules.json`（上传文件、`payload.rules`、或组合 `{"rules":…, "records":…}`）；records 走 `payload.records` / `payload.records_path`。

records 两种形态（可混用）：

```json
{"key": "张三", "day": 5, "band": "morning", "entries": [{"symbol": "√", "value": 2.0}]}
{"key": "张三", "cells": [{"col": "BQ", "row_offset": 0, "value": "张三"}]}
```

- 日历型：槽列 = `anchor + (day-1)×slots_per_day`；行 = 块首行 + `bands[band].row_offset` + entry 序号；`layout=symbol_value` 写符号格+数值格两格
- 直写型：块内任意格（列字母/列号 + row_offset）
- 校验：day/band/entry/row_offset 越界、键不在块清单 → 带原因进 `expected.records_dropped`
- 公式：`formula_templates` 按 `block_index` 实例化到每块首行
- 保护区：`formula_zones` 中**未被模板覆盖**的列 → `plan.protected_ranges`（第二道防线）
- `payload.month_label`（YYYY-MM）→ `month_cells` 写年/月

输出 `outputs/plan.json`：模板写入员 `plan_version=1` 契约 + `expected`（对账基准）+ `meta.rules_ref`（规则内容 sha256，产物可追溯规则版本）。

## 固化建议

`rules.json` 提案经人确认（补 `bands`、修 `clear_zone`、填 `policy`）后入库固化，配套金样（输入样本 + 期望输出）做回归门禁；模板改版时重新 infer 比对 diff。
