# ELT 单一命名升级说明

本版本不再把历史 ETL 名称当作运行时别名。直接删库或跳过升级会丢失数据或无法启动；请按下述步骤迁移后再启动新版本。

## 升级步骤

1. 备份当前数据库，不要删除已有库。
2. 在应用目录执行 `alembic upgrade head`。这会沿用已落库的历史 revision，并把残留的 `etl.*` 权限码改成 `elt.*`（若 `elt.*` 权限已存在，则把旧授权合并过去，不丢角色授权）。同一升级还会把业务可变状态中的旧标识改成现行值：模板来源 `shipment_excel_etl`、发货导入 `kind=shipment_delivery_etl`、指纹 `source_kind=general_etl`、出货记录 `raw_text` 中的 `source=shipment_excel_etl`、运行回滚元数据键 `_etl`，以及草稿里的动作 `execute_delivery_etl`。若 `_etl` 与 `_elt` 同时存在且值冲突，升级会失败并回滚该次写入，不会丢行。
3. 把环境变量改成现行名称，例如 `FHD_SHIPMENT_ETL_LLM` 改为 `FHD_SHIPMENT_ELT_LLM`，`FHD_EXCEL_ETL_*` 改为 `FHD_EXCEL_ELT_*`。完整对照见 `app/application/elt_env.py` 中的 `LEGACY_TO_CURRENT`。旧变量只要还在环境里，启动就会失败并列出应改成的新名称。
4. 业务代码和 Mods 改为直接导入 `app.*.elt_*` 与 `ShipmentEltProfile` 等现行符号。`app.*.etl_*` 导入路径已删除，不再通过 `sys.modules` 转发。
5. 权限检查与接口请使用 `elt.read`、`elt.execute`、`elt.template.manage` 等 `elt.*` 码；传入 `etl.*` 会被视为缺少权限，而不是自动改写。

公开 HTTP API 仍是 `/api/elt`。能力页历史地址 `erp-etl.html` 属于已发布资料路径，本变更不把它暗改成仍可用的同页别名；若后续更换对外页面，需单独公布新地址。

## 不会改动的部分

- 已落库 Alembic revision 标识和已经应用的历史迁移文件名、迁移语义（例如 `2026_09_05_etl_operation_lease`）。
- 与本项目数据对接无关的通用 “ETL” 术语或第三方协议名称。
- 用户业务数据：调和与切换迁移只改名或合并权限与业务标识，不删除仍有数据的运行行。
- 历史回执与审计快照：`elt_runs.receipt_json` / `summary_json`，以及运行行上的 `source_json`、`provenance_json`、`llm_suggestion_json` 视为已发出或模型/来源快照，不改写其中的旧标识。已归档的验收证据（例如 `docs/evidence/e2e/`）也不改。
- 行业术语或与本项目运行标识无关的字符串，例如 `general_elt_legacy_note`，不会被当成旧值替换。

空库安装执行 `alembic upgrade head` 后，运行行表名为 `elt_run_rows`，不应再出现可用的 `etl_*` 业务表、运行时 `etl.*` 权限码，或仍由运行时代码写入的 `shipment_excel_etl` / `shipment_delivery_etl` / `general_etl` / `_etl` / `execute_delivery_etl` 标识。
