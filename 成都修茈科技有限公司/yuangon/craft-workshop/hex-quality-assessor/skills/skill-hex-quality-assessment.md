# 六维质检（MODstore 员工包）

对**被测员工包**输出六维 JSON 评分（0–100），键名固定：

- `requirement_clarity` — 需求理解
- `pack_compliance` — 包体合规
- `code_robustness` — 代码健壮
- `executability` — 可执行性
- `workflow_connectivity` — 流程贯通
- `domain_delivery` — 领域交付

## 输入（task JSON）

- `target_employee_id`：被测员工 id
- `pipeline_label`：管线标签（如 `asset_direct_python`）
- `baseline_report`：规则引擎六维基线（可选参考）
- `manifest_excerpt`：manifest 摘要
- `validate_errors` / `mod_checks_summary`：校验结果
- `bench_summary`：上架基准测试摘要（若有）

## 输出

**仅 JSON**，结构见 system prompt。每项须给出可审计的 `reasons`。
