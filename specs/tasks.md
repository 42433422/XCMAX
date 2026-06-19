# 技术债清偿任务分解 (Tasks)

> 关联规范：`e:\XCMAX\specs\spec.md`
> 日期：2026-05-13
> **2026-06-07 全量复核更新** — v10 线内迭代

---

## 产品线执行任务（3+2）

> 产品线 SSOT：[`product-lines-3-plus-2.md`](product-lines-3-plus-2.md)。所有新增任务必须归入 AI 员工商店、企业桌面 ERP + AI、移动 AI 协同 App 三条主线之一；个人版保持冻结。

- [x] PL0: 建立三条主线 + 个人版冻结的产品线 SSOT
- [x] PL0-1: 产品版本锁死 v10，锚点恒 `10.0.0`
  - 不使用 `v10.1` / `v10.2` / `v10.3` / `v11` 表达路线；改用 v10-A/B/C/D 阶段、channel、git tag、`git_sha`、`sha256` 和 manifest
- [ ] PL1: 企业桌面 ERP + AI — 固化 v10-A 可交付验收清单
  - 安装包、首次启动、引导、`deliverable-status`、行业样板流程、日志、升级 / 回滚说明
- [ ] PL2: AI 员工商店 — 固化 v10-B 桌面端联动闭环
  - Catalog、企业授权、下载源、桌面端安装、启用、禁用、回滚
- [ ] PL3: 移动 AI 协同 App — 固化 v10-C 协同闭环
  - 企业登录、扫码连接、AI 对话、通知、审批、任务 / 订单简表
- [x] PL4: 个人版冻结
  - 暂停新增功能；仅允许兼容、归档、未来恢复入口文档维护

---

## P0-1: FHD session.py 查询缓存重构

- [x] T1: 创建 `app/db/session_cache.py`，实现 `ThreadSafeLRUCache` 类 — **已完成（更早）**
- [x] T2: 重构 `app/db/session.py`，替换 `_query_cache` 为 `ThreadSafeLRUCache`
- [x] T3: 新增 `tests/test_db/test_session_cache.py` — **9 条用例，2026-06-07 补全**

## P0-2: 成都修茈 app_factory.py 拆分

- [ ] T4: 提取 `_init_database()` 函数
  - 包含 `init_db()`、`models_project_context` 注册、`sync_employee_triggers`
- [ ] T5: 提取 `_init_event_subscribers()` 函数
  - 包含 `install_default_subscribers()`
- [ ] T6: 提取 `_init_background_jobs()` 函数
  - 包含 outbox worker、subscription scheduler、workflow scheduler
  - 保留 `MODSTORE_RUN_BACKGROUND_JOBS` 开关逻辑
- [ ] T7: 提取 `_register_core_routes()` 函数
  - 包含 health、config、catalog、authoring、sync、debug、market、payment 等
- [ ] T8: 提取 `_register_optional_routes()` 函数
  - 包含 `_include_optional` 循环和 `workflow_hooks_router`
- [ ] T9: 提取 `_register_diagnostics()` 函数
  - 包含 NeuroBus 诊断、secure config、UI mount、vibe subapp
- [ ] T10: 重写 `create_app()` 为编排函数（≤150 行）
- [ ] T11: 新增 `tests/test_app_factory.py`
  - 测试各子函数独立调用
  - 测试 `AppConfig(profile="llm-only")` 路径
  - 测试可选路由加载失败不崩溃

## P0-3: FHD requirements.txt 依赖分类

- [ ] T12: 从 `requirements.txt` 移除测试依赖
  - 移除：pytest、pytest-cov、pytest-mock、pytest-asyncio
  - 这些已由 `pyproject.toml [dev]` 管理
- [ ] T13: 从 `requirements.txt` 移除 ML 依赖
  - 移除：miniaudio、imageio-ffmpeg、soundcard、PyAudio、faster-whisper
  - 确认 `requirements-ml.txt` 已包含这些依赖
- [ ] T14: 验证 `pip install -r requirements.txt` 后服务可正常启动

## P1-1: FHD 测试覆盖率提升至 70%

- [ ] T15: 补充 `app/db/session.py` 测试（依赖 P0-1 完成后的新缓存实现）
- [ ] T16: 补充 `app/services/rule_engine.py` 测试
- [ ] T17: 补充 `app/utils/cache_manager.py` 测试
- [ ] T18: 补充 `app/utils/rate_limiter.py` 测试
- [ ] T19: 补充 `app/services/train_intent.py` 测试
- [ ] T20: 新增前端 `frontend/src/api/__tests__/` 测试文件
  - `core.test.ts` — HTTP 客户端基础
  - `auth.test.ts` — 认证 API
  - `orders.test.ts` — 订单 API
- [ ] T21: 新增前端 `frontend/src/stores/__tests__/` 测试文件
  - `mods.test.ts` — Mod Store
- [ ] T22: 更新 CI `cov-fail-under` 为 70

## P1-2: 成都修茈 Python 测试覆盖率提升至 55%

- [ ] T23: 补充 `modstore_server/employee_api.py` 测试
- [ ] T24: 补充 `modstore_server/workflow_engine.py` 测试
- [ ] T25: 补充 `modstore_server/knowledge_ingest.py` 测试
- [ ] T26: 补充 `modstore_server/llm_billing.py` 测试
- [ ] T27: 补充 `modstore_server/catalog_sync.py` 测试
- [ ] T28: 更新 CI `MODSTORE_PY_COVERAGE_FLOOR` 为 55

## P1-3: mypy ignore_errors 清理

- [ ] T29: FHD — 将 `tests.*` 的 `ignore_errors = true` 改为逐文件或逐错误码忽略
- [ ] T30: 成都修茈 — 从 ignore 列表移除 `modstore_server.db.*`（5 个模块）
- [ ] T31: 成都修茈 — 从 ignore 列表移除 `modstore_server.eventing.*`（2 个模块）
- [ ] T32: 成都修茈 — 从 ignore 列表移除 `modstore_server.models_*` 中优先级最高的 5 个
- [ ] T33: 成都修茈 — 修复上述模块的 mypy 错误
- [ ] T34: 两项目分别运行 `mypy` 验证零新增错误

## P1-4: FHD 临时脚本归档

- [ ] T35: 创建 `scripts/db_ops/` 目录，迁移数据库运维脚本
  - `check_docker_pg.py`、`check_payment_db.py`、`diagnose_db.py`、`scan_all_dbs.py`、`check_db_connection.py`
- [ ] T36: 创建 `scripts/admin/` 目录，迁移管理员脚本
  - `find_users.py`、`restore_pwd.py`、`set_admin_pwd.py`、`set_bcrypt_pwd.py`、`set_pbkdf2_pwd.py`
- [ ] T37: 创建 `scripts/debug/` 目录，迁移调试脚本
  - `deep_probe.py`、`probe_api.py`、`probe_server.py`、`ssh_diagnose.py`、`ssh_fix_db.py`、`test_remote_api.py`
- [ ] T38: 删除一次性脚本
  - `fix_bcrypt.py`、`fix_pg.py`
- [ ] T39: 更新 `scripts/README.md` 目录说明

## P2-1: 成都修茈 DDD 分层启动

- [ ] T40: 创建 `modstore_server/application/` 目录
  - `__init__.py`
  - `catalog_service.py` — 目录用例编排
  - `employee_service.py` — 员工用例编排
  - `payment_service.py` — 支付用例编排
- [ ] T41: 创建 `modstore_server/domain/` 目录
  - `__init__.py`
  - `catalog.py` — 目录领域模型
  - `employee.py` — 员工领域模型
- [ ] T42: 确保新文件不在 mypy ignore 列表中

## P2-2: FHD 前端 TypeScript 严格化

- [ ] T43: `frontend/tsconfig.json` 启用 `strict: true`
- [ ] T44: 修复 `vue-tsc --noEmit` 所有报错
- [ ] T45: `frontend/src/api/` 所有导出函数补全类型签名
- [ ] T46: 验证 `npm run build:strict` 通过

---

## 测试纪律与覆盖率治理（2026-05，关联 COVERAGE_RAMP）

- [x] G1: 统一 FHD `test.yml` / `ci-cd.yml` / `verify_governance_deliverable.sh` 窄包 `cov-fail-under=60`
- [x] G2: `backend-coverage-report` 输出全量 `--cov=app` XML + summary artifact
- [x] G3: 新增 `tests/integration/`（auth、ERP、finance/report、rbac）+ CI `backend-integration-test` job
- [x] G4: `test_services` / `test_application` 补 purchase、inventory、finance
- [x] G5: 前端 `src/api` 补 auth、orders、materials、modStore、core 单测；Vitest lines 50 / statements 30
- [x] G6: MODstore `docs/coverage-gates.md` + `tests/integration/test_payment_webhook_flow.py`
- [x] G7: `specs/checklist.md` PR 测试纪律 + `.trae/specs/_template/checklist.md`
- [x] G8: 全量 `app` 覆盖率 HEAD **85.07%** 行（2026-06-20 bump）；WIP **74.56%**（待清红灯）— 见 `metrics/coverage-dual-summary.json` / `COVERAGE_RAMP.md`
