# 仓库全覆盖归属表（Single Source of Truth）

> 版本：1.1.0 · 更新：2026-05-08  
> 目标：`E:\成都修茈科技有限公司` 下的**每一个文件/目录**都必须有一名 AI 员工或一条「显式忽略」规则覆盖，没有真空地带。

本表与 [`yuangon/**/employee.yaml`](.) 的 `scope_globs` / `forbidden_globs` 保持一致；
任何新增目录/文件**先**登记到本表，再扩 yaml，再跑 `push-update-context-officer.skill-yuangon-resync`
让 `task-router-officer` 重建路由表。

## 一、仓库根（`E:\成都修茈科技有限公司\`）

| 路径 | 所有者 | 备注 |
|------|--------|------|
| `app.py`、`requirements.txt`、`public/**`、`uploads/**`、`excel-to-ai.html` | `flask-entry-keeper` | 根 Flask 入口 |
| `src/**`、`main.js`、`index.html`、`about.html`、`cases.html`、`case-*.html`、`services.html`、`solutions.html`、`news.html`、`contact.html`、`honors.html`、`styles.css`、`assets/**`、`activities.json`、`news.json` | `site-content-editor` | 静态营销站内容（含 Vite 子目录 `src/`） |
| `package.json`、`package-lock.json`、`vite.config.ts`、`tsconfig*.json`、`eslint.config.js`、`.prettierrc`、`.prettierignore`、`env.d.ts` | `site-content-editor` | 根前端工具链（与 MODstore_deploy/market/ 工具链是两套，不要混用） |
| `sitemap.xml`、`robots.txt`、`baidu_urls.txt`、`BingSiteAuth.xml`、`baidu_verify_*.html` | `seo-sitemap-curator` | SEO 资产 |
| `nginx-*.conf`、`xiu-ci.com_nginx.zip`、`_nginx_extract/**` | `nginx-config-engineer` | Nginx 配置 |
| `_local_secrets/**`、`.cursor_admin_token.txt`、`alipay_package/**` | `security-secrets-guard` | 密钥与凭据 |
| `setup-alipay.sh`、`stop_ports.py`、`deploy/**`、`scripts/**`、`docker/**`、`dist/**` | `deploy-release-officer` | 发布与部署 |
| `.github/**`、`.gitignore`、`.gitleaks.toml`、`*.code-workspace`（如 `成都修茈科技有限公司.code-workspace`） | `push-update-context-officer` | 仓库元数据 + CI / 密钥扫描配置 |
| `playwright.config.ts`、`.pre-commit-config.yaml` | `test-qa-runner` | 测试编排 |
| `.cursor_*_log.txt`、`coverage/**`、`playwright-report/**`、`test-results/**` | `log-monitor-incident`（读）+ `retention-officer`（清理） | 日志/产物 |
| `__tmp_xcemp/**`、`__tmp_emp_*.json`、`.cursor_inspect_purge.py`、`MODstore_deploy.zip`、`xiu-ci.com_nginx.zip`（仅清理）、`3月31日 (5)(*).mp4`、`test_image.jpg`、`new/**`、`site/**`、`taiyangniao-pro/**` | `retention-officer` | 历史/临时归档 |
| `node_modules/**`、`__pycache__/**`、`.pytest_cache/**`、`.git/**`、`.venv/**` | **显式忽略**（构建/IDE 产物，不入员工 scope） | retention-officer 可周期清理 `node_modules` 之外的项 |
| `.cursor/**`、`.trae/**` | `doc-knowledge-curator` | IDE 项目级提示词与规则 |
| `*.md`（仓库根所有 Markdown，含 `LLM*.md`、`OPC_*.md`、`腾讯云Pages部署指引.md`、`修改建议-需求报告.md`、`README.md`、`ESkill.md`） | `doc-knowledge-curator` | 文档总管 |
| `*.docx`（如 `AI员工集体建设需求报告.docx`） | `doc-knowledge-curator` | 战略文档 |
| `project-doc-generator.xcemp`、`py-doc-generator.xcemp` | `doc-knowledge-curator` | 文档生成器员工包（自用工具） |
| `marketing-site/**` | `marketing-site-builder` | Nunjucks 营销站构建（与根静态站分工） |
| `mods/**`、`eskill-prototype/**` | `mods-and-eskill-curator` | Mod 包与 ESkill 原型 |
| `mianshi/**` | `intake-dispatcher`（监听） + `employee-interview-assistant`（处理） + `employee-pack-quality-interviewer`（质询） | 候补员工面试中转 |
| `vibe-coding/**` | `vibe-coding-maintainer` | 平台核心库（test_vibe_*_data 子目录归 retention-officer 清理） |
| `MODstore_deploy/**` | 见下表 §二 | MODstore 平台 |
| `yuangon/**` | 各员工自治 + `employee-interview-assistant`/`employee-pack-quality-interviewer` 跨员工写元数据 | 编制源 |

## 二、`MODstore_deploy/` 子树

| 路径 | 所有者 | 备注 |
|------|--------|------|
| `market/src/views/workbench/**`、`market/src/components/workbench/**`、`market/src/components/admin/**`、`market/src/views/Admin*View.vue`、`market/src/views/admin/**`、`WorkbenchHomeView.vue` | `workbench-ux-stylist` | 工作台 + 管理后台 UI |
| `market/src/**`（其余）、`market/src/api.ts`、`market/src/infrastructure/**`、`market/src/components/**`（非 admin/workbench）、`market/src/stores/**`、`market/src/router/**`、`market/package.json`、`market/vite.config.*`、`market/tsconfig*.json` | `market-frontend-dev` | 市场前端 |
| `market/src/**/*.test.ts`、`market/src/**/*.spec.ts`、`market/src/test/**` | `test-qa-runner` | 前端测试 |
| `market/dist/**`、`market_vue_baseline/**`、`market_vue_baseline*.tar.gz`、`market-dist-*.zip`、`hero-video.mp4` | `retention-officer` | 构建产物 + 历史快照 |
| `modstore_server/workbench_api.py`、`market_api.py`、`market_catalog_api.py`、`script_workflow_api.py`、`realtime_ws.py`、`llm_api.py`、`llm_chat_proxy.py`、`llm_catalog.py`、`llm_model_taxonomy.py`、`workflow_nl_graph.py`、`api/**`、`eventing/**`、`app.py` | `modstore-backend-api` | 后端 API |
| `modstore_server/employee_*.py`、`mod_employee_*.py`、`mod_scaffold_runner.py`、`services/employee.py`、`integrations/vibe_eskill_adapter.py`、`market_files/*.xcemp` | `employee-pack-curator` | 员工包生命周期 |
| `modstore_server/payment_*.py`、`payment_orders/**`、`llm_billing.py`、`subscription_renewer.py`、`llm_key_resolver.py`、`java_payment_service/**` | `payment-billing-reconciler` | 支付/账单 |
| `modstore_server/models.py`、`db.py`、`database*.py`、`migrations/**`、`alembic/**`、`alembic.ini`、`scripts/db_*.py` | `dbops-engineer` | ORM + 迁移 |
| `modstore_server/eventing/intake/**`、`api/intake_api.py`、`webhook_events/intake/**` | `intake-dispatcher` | 接入层 |
| `modstore_server/eventing/router/**`、`api/router_api.py`、`scripts/build_routing_table.py`、`docs/routing-table.md` | `task-router-officer` | 派发层 |
| `modstore_server/api/change_request_api.py`、`eventing/audit/**`、`scripts/audit_*.py`、`docs/runbooks/change-request-audit.md` | `change-request-auditor` | 评审层 |
| `modstore_server/script_agent/**`、`services/**`、`tools/**`、`application/**`、`domain/**`、`infrastructure/**`、`integrations/**`（除上面已点名的） | `modstore-backend-api` | 后端通用代码（默认归 backend-api） |
| `modstore_server/workbench_script_runs/**`、`webhook_events/**`、`market_files/.tmp_chunks/**` | `retention-officer` | 临时/沙箱产物 |
| `modstore_server/library/**`、`catalog_data/**`、`vector_data/**`、`data/**` | **用户数据 / 显式禁区**（所有员工 forbidden） | 任何代码改动都必须经 admin 显式授权 |
| `modstore_server/__pycache__/**`、`modstore.egg-info/**`、`.coverage` | **显式忽略** | retention-officer 可清 |
| `tests/**`、`tests/conftest.py`、`tests/test_coverage_gates.py` | `test-qa-runner` | 后端测试 |
| `docs/**` | `doc-knowledge-curator`（默认） | 子项另有专属人员（详见 §三） |
| `chaos/**`、`monitoring/**`、`orchestration/**`、`perf/**` | `log-monitor-incident` | SRE/可观测域 |
| `keys/**`、`keys_staging/**`、`.env`、`.env.example`、`.env.local`、`.env.production*`、`runtime_allowlist.json` | `security-secrets-guard` | 凭据/允许清单 |
| `Dockerfile`、`docker-compose.yml`、`.dockerignore`、`deploy.sh`、`deploy.bat`、`restart.bat`、`start*.{py,bat,ps1}`、`systemd/**` | `deploy-release-officer` | 发布脚手架 |
| `git-push.bat`、`git-push.sh`、`.gitignore`、`.github/**` | `push-update-context-officer` | 推送/CI |
| `pyproject.toml`、`COMPOSE.md`、`CONTRIBUTING.md`、`templates/**`、`examples/**` | `doc-knowledge-curator` | 项目文档 |
| `modman/**` | `mods-and-eskill-curator` | Mod manager 工具 |
| `var/**` | **显式禁区**（运行时） | 仅 retention-officer 在 `workbench_script_runs/`/`webhook_events/` 等子目录下清理 |
| `.mypy_cache/**`、`.ruff_cache/**`、`.pytest_cache/**`、`.venv/**`、`.trae/**` | **显式忽略** | IDE/缓存 |

## 三、`MODstore_deploy/docs/` 子树

| 路径 | 所有者 |
|------|--------|
| `docs/observability.md`、`OPS_MONITORING.md`、`runbooks/incident-response.md`、`sre-operating-model.md`、`runbooks/disaster-recovery.md`、`runbooks/chaos-game-day.md` | `log-monitor-incident` |
| `docs/employee_publish_wizard.md`、`fhd-employee-composition.md`、`docs/modstore/员工制作增强设计方案.md`、`docs/adr/0003-artifacts-bundles-employee-packs.md` | `employee-pack-curator` |
| `docs/runbooks/dbops-*.md` | `dbops-engineer` |
| `docs/runbooks/change-request-audit.md` | `change-request-auditor` |
| `docs/routing-table.md` | `task-router-officer` |
| `docs/yuangon-process-loop.md` | `doc-knowledge-curator` + 各 area 共写 |
| `docs/runbooks/file-retention.md`、`docs/runbooks/legacy-archive.md`、`docs/runbooks/yuangon-resync.md` | `retention-officer` / `push-update-context-officer` |
| `docs/**`（其他） | `doc-knowledge-curator` |

## 四、`yuangon/` 子树

每个员工自治自己的 `yuangon/<area>/<id>/**`。跨员工写访问由两人共审：

- **`employee-interview-assistant`**：可写 `yuangon/**/README.md`、`employee.yaml`、`runbook.md`、`skills/*.md`、`tasks/**`，但只能在「访谈」流程中、且需对应员工签字。
- **`employee-pack-quality-interviewer`**：可写 `yuangon/**/employee.yaml`、`prompts/*.md`、`skills/*.md`，做静态质询时使用。
- **其余员工对 `yuangon/<other-id>/**` 是只读**。

`yuangon/_shared/**`（含本文件、模板）→ `doc-knowledge-curator` 维护。

## 五、显式忽略清单（不进任何员工 scope）

```
**/__pycache__/**
**/.pytest_cache/**
**/.mypy_cache/**
**/.ruff_cache/**
**/node_modules/**
**/.venv/**
**/.git/**
**/dist/**             # 构建产物（部署前由 deploy-release-officer 重新生成）
**/modstore.egg-info/**
**/*.pyc
**/*.pyo
.coverage
# 租户实例 / 运行时 / 临时构建产物（Yuangon 全覆盖 Phase 2 注入 employee.yaml 忽略同步）
MODstore_deploy/library/**
MODstore_deploy/modstore_server/catalog_data/**
MODstore_deploy/modstore_server/*.db
MODstore_deploy/var/**
var/**
MODstore_deploy/market/market-dist-upload.tgz
MODstore_deploy/market/tmp_tsc.log
.cursor_inspect_purge.py
```

`retention-officer` 可以**清理**这些路径下的过期文件，但不写入它们。

## 六、新增路径登记流程

1. 在本文件 §一 / §二 对应表新增一行。
2. 修改对应员工的 `yuangon/<area>/<id>/employee.yaml` 的 `scope_globs`。
3. 提交后 `git pre-push` 钩子（[`scripts/yuangon_pre_push.sh`](../../scripts/yuangon_pre_push.sh)）会自动跑 `onboard_yuangon_employees --dry-run` 校验，失败则阻止推送。
4. 推送后 `push-update-context-officer.skill-yuangon-resync` 接住 `yuangon.def.changed` → 自动 onboard + 重建路由表。

## 七、变更记录

| 日期 | 变更 | 操作人 |
|------|------|--------|
| 2026-05-08 | 初版：全仓库 25 名员工 + 显式忽略表 | admin |
| 2026-05-08 | v1.1：新增 `marketing-site-builder`；§五 扩充租户/运行时显式忽略（Phase2） | admin |
| 2026-05-08 | §一 补充 `.gitleaks.toml`；§四 访谈员范围含 `tasks/**` | admin |
