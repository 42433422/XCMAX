# 技术债清偿规范 (Technical Debt Remediation Spec)

> 范围：`e:\XCMAX\FHD`（含 **admin** 运营实例 host profile）+ `e:\XCMAX\成都修茈科技有限公司`  
> 注：历史目录 `FHD-个人/` 为企业版**管理员**并行实例（非商业个人版 SKU），已对齐迁入 `FHD/`；见 [FHD/docs/guides/ADMIN_OPERATOR_INSTANCE.md](../FHD/docs/guides/ADMIN_OPERATOR_INSTANCE.md)。
> 日期：2026-05-13
> 状态：执行中（产品线口径已确认）

---

## 0. 产品线执行边界（3+2）

本技术债规范服务于当前产品线策略：**三条主线 + 个人版冻结**。产品线 SSOT 见 [`product-lines-3-plus-2.md`](product-lines-3-plus-2.md)。

| 线 | 当前状态 | 工程含义 |
|----|----------|----------|
| 企业桌面 ERP + AI | P0 主交付 | `FHD/` 的桌面宿主、ERP、AI 员工、行业 Mod、交付验收优先 |
| AI 员工商店 | P1 商业化线 | `成都修茈科技有限公司/`、`MODstore_deploy/` 的目录、授权、支付、下载、更新优先 |
| 移动 AI 协同 App | P2 配套线 | `FHD/mobile-android/` 只做桌面端协同，不复刻完整 ERP |
| 个人版 | Frozen | 暂停新增投入；仅保留兼容、归档和未来恢复入口 |

因此，后续技术债清偿必须能支撑三条主线之一；不能归入三条主线的工作默认进入 backlog。个人版相关新增功能不纳入当前规范。

---

## 1. 背景与目标

全量评估发现两个项目存在以下共性和个性技术债，按优先级 P0 > P1 > P2 排列。本规范定义每项技术债的**现状、目标、验收标准**，不涉及功能新增。

### 总体目标

| 指标 | FHD（含 admin）现状 | FHD 目标 | 成都修茈 现状 | 成都修茈 目标 |
|------|---------------------|----------|-------------|-------------|
| Python 测试覆盖率 | 全量 `app` **HEAD 52.74% 行**；WIP **74.56%**（196 红灯） | 全量 **≥90% 行 / ≥85% 分支** | 全局 floor **42%** | 全局 **≥55%** |
| mypy ignore_errors 模块数 | ~20 | ≤10 | ~50 | ≤30 |
| 前端测试文件数 | 1 (smoke) | ≥5 | ~8 | ≥12 |
| 临时脚本 (fix_/check_/final_) | ~15 | 0 (归档或删除) | 0 | 0 |
| requirements.txt 混入测试/ML 依赖 | 是 | 否 | 否 | 否 |
| 查询缓存并发安全 | 已迁入 ThreadSafeLRUCache | 保持 | N/A | N/A |
| create_app() 行数 | N/A | N/A | 442 | ≤150 |

---

## 2. P0 — 必须立即修复（影响生产安全或阻塞合并）

### P0-1: FHD `app/db/session.py` 查询缓存不安全（已合入 ThreadSafeLRUCache，需保持）

**现状**：`_query_cache` 是全局字典，使用 MD5 哈希做键，无 TTL 清理、无并发安全、无 LRU 淘汰。生产环境可能导致内存泄漏和数据竞争。

**目标**：
- 替换为线程安全的 `OrderedDict` LRU 实现
- 增加 TTL 过期机制（默认 300s）
- 增加最大容量限制（默认 128 条）
- 移除 MD5 哈希，改用 `repr` + `hash` 组合键

**验收标准**：
- [ ] `_query_cache` 不再是裸 `dict`
- [ ] 并发读写无数据竞争（threading.Lock 保护）
- [ ] 条目超过 TTL 自动失效
- [ ] 容量超限时 LRU 淘汰最旧条目
- [ ] `tests/test_db/test_session_cache.py` 新增 ≥5 条用例通过

### P0-2: 成都修茈 `modstore_server/api/app_factory.py` create_app() 上帝函数

**现状**：`create_app()` 函数 442 行，混合了数据库初始化、事件订阅、后台任务启动、路由注册、中间件注册、可选模块加载等职责。

**目标**：
- 拆分为 5-6 个职责单一的私有函数
- `create_app()` 本体 ≤150 行，仅做编排调用

**拆分方案**：
```
create_app()
  ├── _init_database()          # init_db + models 注册
  ├── _init_event_subscribers() # 事件订阅器安装
  ├── _init_background_jobs()   # outbox/subscription/workflow scheduler
  ├── _register_core_routes()   # market/payment/catalog/health 等
  ├── _register_optional_routes() # _include_optional 循环
  └── _register_diagnostics()   # NeuroBus 诊断 + secure config + UI mount
```

**验收标准**：
- [ ] `create_app()` 函数体 ≤150 行
- [ ] 每个拆分函数有明确的单一职责
- [ ] 所有现有测试仍通过
- [ ] 新增 `tests/test_app_factory.py` 覆盖拆分后的函数

### P0-3: FHD `requirements.txt` 依赖分类混乱

**现状**：`requirements.txt` 混入了测试依赖（pytest、pytest-cov 等）和 ML 依赖（miniaudio、faster-whisper 等），与 `pyproject.toml` 的 `[project.optional-dependencies]` 定义冲突。

**目标**：
- `requirements.txt` 仅保留生产运行时依赖
- ML 依赖全部移至 `requirements-ml.txt`
- 测试依赖仅通过 `pip install -e ".[dev]"` 安装

**验收标准**：
- [ ] `requirements.txt` 不包含 pytest/pytest-cov/pytest-mock/pytest-asyncio
- [ ] `requirements.txt` 不包含 miniaudio/faster-whisper/PyAudio/soundcard/imageio-ffmpeg
- [ ] `requirements-ml.txt` 包含上述 ML 依赖
- [ ] `pip install -r requirements.txt` 后可正常启动 FastAPI 服务

---

## 3. P1 — 应尽快修复（影响代码质量和可维护性）

### P1-1: FHD 测试覆盖率提升至 Phase 4 定版

**现状**（2026-06-17）：**全量** `source=[app]` + branch；HEAD **52.74% 行 / 37.17% 分支**（`1569dfa4` 全绿 bump）；WIP **74.56% 行** 但有 **196 failed + 7 errors**。棘轮 floor：行 **51%**、分支 **36%**。前端 HEAD **55.82% 行**；vitest **1,143+** 测例。详见 `FHD/docs/reports/COVERAGE_RAMP.md`。

**目标**：
- Python 全量行 **≥90%**、分支 **≥85%**（Phase 4 定版）
- 前端全量 `src/**` 行 **≥80%**
- pytest / vitest **全绿** 后方可 `coverage_ratchet.py --bump`

**验收标准**：
- [x] 全量 `source=[app]` 棘轮接入 CI（`coverage_ratchet.py --check`）
- [x] HEAD 行覆盖 ≥50%（2026-06-14 已达 52.74%）
- [ ] pytest 全绿（WIP：**196 failed + 7 errors** 待清）
- [ ] 后端行 ≥90%、分支 ≥85%
- [ ] 前端 lines ≥80%

### P1-2: 成都修茈 Python 测试覆盖率提升至 55%

**现状**：全局覆盖率 42%，CI 门禁设为 42%。

**目标**：全局覆盖率 ≥55%，CI 门禁同步更新。

**重点补测模块**：
1. `modstore_server/employee_api.py` — 员工 API
2. `modstore_server/workflow_engine.py` — 工作流引擎
3. `modstore_server/knowledge_ingest.py` — 知识库导入
4. `modstore_server/llm_billing.py` — LLM 计费
5. `modstore_server/catalog_sync.py` — 目录同步

**验收标准**：
- [ ] `pytest --cov=modstore_server --cov-fail-under=55` 通过
- [ ] CI `MODSTORE_PY_COVERAGE_FLOOR` 更新为 55

### P1-3: mypy ignore_errors 清理（两项目各减半）

**FHD 现状**：`pyproject.toml` 中约 20 个第三方模块 `ignore_missing_imports = true`（合理），但 `tests.*` 整体 `ignore_errors = true`（不合理）。

**成都修茈 现状**：`pyproject.toml` 中约 50 个自有模块 `ignore_errors = true`，意味着大量业务代码无类型检查。

**目标**：
- FHD：`tests.*` 的 `ignore_errors` 改为仅忽略特定错误码
- 成都修茈：50 个 ignore 模块减少到 ≤30 个（优先恢复 `db.*`、`models_*`、`eventing.*`）

**验收标准**：
- [ ] FHD：`mypy app/` 零错误
- [ ] 成都修茈：`mypy` ignore 列表 ≤30 个模块
- [ ] `mypy modstore_server/db/` 零错误
- [ ] `mypy modstore_server/eventing/` 零错误

### P1-4: FHD 临时脚本归档

**现状**：`scripts/` 下存在 `fix_bcrypt.py`、`fix_pg.py`、`check_docker_pg.py`、`check_payment_db.py`、`diagnose_db.py`、`deep_probe.py`、`probe_api.py`、`probe_server.py`、`find_users.py`、`restore_pwd.py`、`scan_all_dbs.py`、`set_admin_pwd.py`、`set_bcrypt_pwd.py`、`set_pbkdf2_pwd.py`、`ssh_diagnose.py`、`ssh_fix_db.py`、`test_db_connection.py`、`test_remote_api.py` 等临时脚本。

**目标**：
- 仍需保留的脚本迁移到 `scripts/db_ops/`、`scripts/debug/`、`scripts/admin/` 子目录
- 一次性脚本删除或归档到 `scripts/_archived/`
- CI 门禁已有 `guard-temp-scripts`，保持不变

**验收标准**：
- [ ] `scripts/` 根目录下无 `fix_*.py`、`check_*.py`、`final_*.py` 文件
- [ ] 保留脚本按职责归入子目录
- [ ] `scripts/README.md` 更新目录说明

---

## 4. P2 — 计划修复（提升工程卓越度）

### P2-1: 成都修茈 modstore_server DDD 分层落地（启动）

**现状**：80+ 个 `*_api.py` 扁平文件，路由与业务逻辑混合。

**目标**（本规范仅启动 P2 阶段）：
- 新增 `modstore_server/application/` 目录，创建 3 个核心 application service
- 新增 `modstore_server/domain/` 目录，创建 2 个核心领域模型
- 新增 `modstore_server/infrastructure/` 目录结构（已有部分）
- 不迁移现有代码，仅确保新代码按 DDD 分层落位

**验收标准**：
- [ ] `modstore_server/application/` 存在且包含 ≥3 个 service 文件
- [ ] `modstore_server/domain/` 存在且包含 ≥2 个领域模型文件
- [ ] 新增代码通过 mypy 严格检查（不在 ignore 列表中）

### P2-2: FHD 前端 TypeScript 严格化

**现状**：前端 `tsconfig.json` 未启用严格模式，API 层类型定义薄弱。

**目标**：
- `tsconfig.json` 启用 `strict: true`
- `frontend/src/api/` 所有文件补全类型定义
- 修复所有 `vue-tsc --noEmit` 报错

**验收标准**：
- [ ] `vue-tsc --noEmit` 零错误
- [ ] `tsconfig.json` 包含 `"strict": true`
- [ ] `frontend/src/api/` 所有导出函数有完整类型签名

---

## 5. 不纳入本规范的内容

- 功能新增（Mod 商店、支付等）
- 个人版新增功能或个人版商业化
- 性能优化（OpenTelemetry、混沌工程）
- 国际化
- 文档补充
- 跨项目 NeuroBus 统一

---

## 6. 执行顺序

```
P0-1 (session.py 缓存) ──→ P1-1 (FHD 测试覆盖率)
P0-2 (app_factory 拆分) ──→ P1-2 (成都修茈 测试覆盖率)
P0-3 (requirements 清理) ──→ P1-4 (临时脚本归档)
                          ──→ P1-3 (mypy 清理，两项目并行)
                          ──→ P2-1 / P2-2 (可并行)
```
