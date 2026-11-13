# 历史 / 示例 YAML（非默认）

仅当 `FHD_EXCEL_ETL_ALLOW_BUILTIN=1` 时由引擎加载。

默认走知识库 `universal` + 可学习 `templates`（`excel_etl_kb.json`）。
自定义版式请放到 `FHD_EXCEL_ETL_PROFILE_DIR`。

## 入库模版库（可选）

ETL 预览/执行接口支持 `save_as_template=1`：在业务解析成功后，把源办公文件再走
`analyze → create`，写入模版库 `templates` 表（见 `office_template_ingest_app_service`）。

也可用独立入口：`POST /api/templates/upload`（或 `POST /api/templates/analyze` + `auto_save=1`）。
