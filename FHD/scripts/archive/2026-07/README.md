# 临时脚本归档 2026-07

## 归档元信息

| 项 | 值 |
| --- | --- |
| 归档日期 | 2026-07-05 |
| 归档批次 | 2026-07 |
| 归档前文件数 | 57 |
| 原路径前缀 | `FHD/scripts/` |
| 归档路径 | `FHD/scripts/archive/2026-07/` |
| 归档操作 | `mv`（仅移动，未删除任何文件） |
| 触发任务 | scripts 顶层散落脚本治理 + guard-temp-scripts 配置缺口修复 |
| 归档人 | XCMAX 工程化治理（AI 子代理） |

## 归档原因

`FHD/scripts/` 顶层散落大量临时诊断/调试/验证脚本，命名前缀命中 `guard_temp_scripts.py` 的
`TEMP_PREFIXES`（`fix_` / `check_` / `final_` / `recover_` / `debug_` / `test_`），属于一次性
throwaway 产物，长期保留在顶层会：

1. 污染 `scripts/` 顶层命名空间，干扰模块清单审阅；
2. 误导开发者复制粘贴过期诊断逻辑到生产代码；
3. 与 `tools/` / `archive/` / `launchers/` 等正式子目录职责冲突；
4. 阻塞 `guard-temp-scripts` 配置升级（无法在 `TEMP_PREFIXES` 中追加 `debug_` / `test_`，
   否则 guard 会拦截这些已存在文件）。

归档后这些脚本仍可通过相对路径 `scripts/archive/2026-07/<name>.py` 引用，但不再出现在顶层。

## 文件清单（57 个）

### final_*.py（4 个）

| 文件 | 原路径 |
| --- | --- |
| `final_all_test.py` | `FHD/scripts/final_all_test.py` |
| `final_merge_result.py` | `FHD/scripts/final_merge_result.py` |
| `final_test.py` | `FHD/scripts/final_test.py` |
| `final_verification.py` | `FHD/scripts/final_verification.py` |

### fix_*.py（4 个）

| 文件 | 原路径 |
| --- | --- |
| `fix_materials_table.py` | `FHD/scripts/fix_materials_table.py` |
| `fix_purchase_unit.py` | `FHD/scripts/fix_purchase_unit.py` |
| `fix_sales_contract_template.py` | `FHD/scripts/fix_sales_contract_template.py` |
| `fix_sqlalchemy_config.py` | `FHD/scripts/fix_sqlalchemy_config.py` |

### debug_*.py（3 个）

| 文件 | 原路径 |
| --- | --- |
| `debug_customer_api.py` | `FHD/scripts/debug_customer_api.py` |
| `debug_pair.py` | `FHD/scripts/debug_pair.py` |
| `debug_sqlalchemy_config.py` | `FHD/scripts/debug_sqlalchemy_config.py` |

### check_*.py（18 个，不含 `check_openapi_consistency.py`）

> 注：`check_openapi_consistency.py` 为正式工具，已合并到 `FHD/scripts/tools/`，
> 不在本批次归档范围。

| 文件 | 原路径 |
| --- | --- |
| `check_3dbs.py` | `FHD/scripts/check_3dbs.py` |
| `check_all_services.py` | `FHD/scripts/check_all_services.py` |
| `check_api_8000.py` | `FHD/scripts/check_api_8000.py` |
| `check_backend_data_source.py` | `FHD/scripts/check_backend_data_source.py` |
| `check_customer_db.py` | `FHD/scripts/check_customer_db.py` |
| `check_customer_unified.py` | `FHD/scripts/check_customer_unified.py` |
| `check_customer_units_count.py` | `FHD/scripts/check_customer_units_count.py` |
| `check_db_full.py` | `FHD/scripts/check_db_full.py` |
| `check_db_query.py` | `FHD/scripts/check_db_query.py` |
| `check_db_structure.py` | `FHD/scripts/check_db_structure.py` |
| `check_db.py` | `FHD/scripts/check_db.py` |
| `check_frontend_statistics.py` | `FHD/scripts/check_frontend_statistics.py` |
| `check_import_status.py` | `FHD/scripts/check_import_status.py` |
| `check_no_xcagi_overrides.py` | `FHD/scripts/check_no_xcagi_overrides.py` |
| `check_purchase_units_table.py` | `FHD/scripts/check_purchase_units_table.py` |
| `check_purchase_units.py` | `FHD/scripts/check_purchase_units.py` |
| `check_templates.py` | `FHD/scripts/check_templates.py` |
| `check_units.py` | `FHD/scripts/check_units.py` |

### test_*.py（28 个）

| 文件 | 原路径 |
| --- | --- |
| `test_all_apis.py` | `FHD/scripts/test_all_apis.py` |
| `test_backend.py` | `FHD/scripts/test_backend.py` |
| `test_blank_grid_detection.py` | `FHD/scripts/test_blank_grid_detection.py` |
| `test_blank_grid.py` | `FHD/scripts/test_blank_grid.py` |
| `test_delete_function.py` | `FHD/scripts/test_delete_function.py` |
| `test_grid_layout.py` | `FHD/scripts/test_grid_layout.py` |
| `test_merged_cells_fixed.py` | `FHD/scripts/test_merged_cells_fixed.py` |
| `test_paddleocr_cv2.py` | `FHD/scripts/test_paddleocr_cv2.py` |
| `test_paddleocr_predict.py` | `FHD/scripts/test_paddleocr_predict.py` |
| `test_paddleocr_result.py` | `FHD/scripts/test_paddleocr_result.py` |
| `test_paddleocr_simple.py` | `FHD/scripts/test_paddleocr_simple.py` |
| `test_paddleocr_table.py` | `FHD/scripts/test_paddleocr_table.py` |
| `test_paddleocr.py` | `FHD/scripts/test_paddleocr.py` |
| `test_pdf.py` | `FHD/scripts/test_pdf.py` |
| `test_PE_white_base.py` | `FHD/scripts/test_PE_white_base.py` |
| `test_ppsructure.py` | `FHD/scripts/test_ppsructure.py` |
| `test_ppstructure.py` | `FHD/scripts/test_ppstructure.py` |
| `test_real_label_cv2.py` | `FHD/scripts/test_real_label_cv2.py` |
| `test_real_label_grid.py` | `FHD/scripts/test_real_label_grid.py` |
| `test_real_label.py` | `FHD/scripts/test_real_label.py` |
| `test_real_vertical_merge.py` | `FHD/scripts/test_real_vertical_merge.py` |
| `test_sqlalchemy_config.py` | `FHD/scripts/test_sqlalchemy_config.py` |
| `test_table_pipeline.py` | `FHD/scripts/test_table_pipeline.py` |
| `test_template_export.py` | `FHD/scripts/test_template_export.py` |
| `test_template_path.py` | `FHD/scripts/test_template_path.py` |
| `test_two_images_fixed.py` | `FHD/scripts/test_two_images_fixed.py` |
| `test_two_images.py` | `FHD/scripts/test_two_images.py` |
| `test_vertical_merge_detection.py` | `FHD/scripts/test_vertical_merge_detection.py` |

> **说明**：上述 `test_*.py` 均为本地调试用脚本，位于 `FHD/scripts/` 顶层，与正式后端单元测试
> （`FHD/tests/`）隔离。CI 守门员 `guard_temp_scripts.py` 已于本次同步升级，
> 将 `test_` / `debug_` 追加到 `TEMP_PREFIXES`，阻止后续再向 `scripts/` 顶层或仓库根提交
> 同前缀的一次性脚本。`FHD/tests/test_*.py` 不受此规则影响（合法单元测试）。

## 同时完成的相关变更

| 变更 | 位置 |
| --- | --- |
| `check_openapi_consistency.py` 由 `scripts/` 迁至 `scripts/tools/` | `FHD/scripts/tools/check_openapi_consistency.py` |
| 同步更新调用路径 | `Makefile`、`Makefile.win`、`tests/test_openapi_consistency.py`、`scripts/ci/bulk_openapi_metadata.py`、`docs/guides/OPENAPI_CONSISTENCY.md`、`docs/reports/LEGACY_CLEANUP_TRACKING.md`、`docs/mobile_tri_platform_ssot.md`、`docs/evidence/arch/README.md`、`app/utils/openapi_path.py`、`scripts/tools/check_openapi_consistency.py` 自身 docstring |
| `guard_temp_scripts.py` 的 `TEMP_PREFIXES` 追加 `debug_` / `test_` | `FHD/scripts/ci/guard_temp_scripts.py` |
| `docs/CI_SSOT.md` 同步前缀清单 | `docs/CI_SSOT.md` |

## 引用与恢复

- 归档不删除任何文件，如需恢复某脚本，使用 `git mv` 或 `mv` 即可。
- 归档目录 `archive/2026-07/` 已加入 `guard_temp_scripts.py::_is_allowed_temp_home` 白名单
  （`rel.startswith("archive/")` 命中），不会触发 guard 违规。
- 如需在 CI 中复用某个归档脚本，应先评估是否应迁回 `tools/` 并改名（去掉 throwaway 前缀），
  而不是直接从 `archive/` 调用。
