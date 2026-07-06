# Excel 模板写入员

通用「模板 + 写入计划 → 回填结果」的 direct_python 员工包。与「Excel 生成员」（JSON 从零建表）互补：本员工吃**已有模板**，按 `plan.json` 声明逐格回填，模板样式、合并单元格、既有公式原样保留。

- 输入：`plan.json`（上传文件或 `payload.plan` 内联）+ 模板 xlsx（`payload.template_path` / `payload.template_relpath` / 包内 `templates/` / `plan.template.path`）
- 输出：`outputs/filled.xlsx` + `write_report.json`（写入统计、violations、透传 `expected`，供质检员对账）

## plan.json 契约（plan_version = 1）

```json
{
  "plan_version": 1,
  "template": {"sheet_names": ["明细", "月度统计"]},
  "protected_ranges": ["明细!BR1:CC500", "明细!CE:CG"],
  "phases": [
    {"phase": "clear_ranges", "ranges": ["明细!E4:BM9"]},
    {"phase": "cell_writes", "writes": [
      {"sheet": "明细", "row": 4, "col": 13, "value": "√"},
      {"sheet": "明细", "ref": "N4", "value": "8", "value_type": "number", "number_format": "0.0"},
      {"sheet": "明细", "ref": "B2", "value": "2026-03-05", "value_type": "date"}
    ]},
    {"phase": "formula_writes", "writes": [
      {"sheet": "月度统计", "ref": "E4", "formula": "=SUMIF(明细!$BQ:$BQ,$B4,明细!BR:BR)"}
    ]},
    {"phase": "retain_sheets", "names": ["明细", "月度统计"]}
  ],
  "expected": {"rows_used": 1100, "employees": 42}
}
```

### 语义

- `template.sheet_names`：可选；模板缺任一声明 sheet 即失败（计划-模板匹配保险）。
- `protected_ranges`：可选；支持 `Sheet!A1:B2` 与整列 `Sheet!BR:CC`。任何写入/清除命中保护区默认**跳过并记 violation**（`write_report.json.violations`）；`payload.strict_protected=true` 时直接失败。
- `phases` 按数组顺序执行：
  - `clear_ranges`：清值不动样式/合并（回填前清旧数据）。
  - `cell_writes`：`ref`（如 `M4`）或 `row`+`col` 二选一；`value_type` 可选 `number/date/datetime/string`，解析失败降级为原样字符串并 warning；`number_format` 可选（如 `0.0`，用于修正模板 `[DBNum1]` 等显示怪癖）。
  - `formula_writes`：公式串（必须以 `=` 开头）原样写入，不求值。
  - `retain_sheets` / `remove_sheets`：裁剪输出 sheet（如只留「明细」「月度统计」）。
- 顶层直接给 `writes` 数组时，视为单一 `cell_writes` 阶段。
- `expected`：写入员不消费，原样透传（返回值与 `write_report.json`），供下游质检员对账。

## payload 可选项

- `plan`：内联计划对象（免上传文件）
- `template_path` / `template_relpath`：模板位置（绝对 / workspace 相对 / 包内相对）
- `output_relpath`：输出路径（默认 `outputs/filled.xlsx`；`.xlsm` 模板自动保留宏并改后缀）
- `strict_protected`：保护区违规改为直接失败
