# Excel 读取员

由上传资产生成的 direct_python 员工包。

上传 `.xlsx/.xlsm`，全量读取为 `outputs/workbook.json` 中介，供生成员/模板写入员等下游员工消费。

## workbook.json 每 sheet 字段

- `columns` / `rows` / `row_records`：按自动识别（或 `payload.header_row` 指定）的表头展平的数据行
- `headers` / `cells`：单元格级明细（`row/col/letter/value/display/formula/data_type`）
- `merged_ranges`：合并单元格范围列表（如 `"A1:D1"`），模板结构（人员块、竖向合并表头）识别依赖它
- `cells[].number_format`：数字格式，仅在非 `General` 时输出（如 `[DBNum1]` / `0.0`），供模板回填保真

## payload 可选项

- `header_row`：表头行（1-based），`0`/缺省为自动识别
- `header_scan_rows` / `max_row_cap` / `max_col_cap`：扫描与截断上限（`0` 不限）
