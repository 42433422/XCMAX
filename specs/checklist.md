# 技术债清偿验收清单 (Checklist)

> 关联规范：`e:\XCMAX\specs\spec.md`
> 关联任务：`e:\XCMAX\specs\tasks.md`
> 日期：2026-05-13
> **2026-06-07 全量复核更新** — 标注实测状态（v10 线内迭代）

---

## P0 验收（必须全部通过才能合并）

### P0-1: session.py 查询缓存

- [x] `app/db/session_cache.py` 文件存在且包含 `ThreadSafeLRUCache` 类 — **已验证 2026-06-07**
- [x] `ThreadSafeLRUCache` 使用 `threading.Lock` 保护并发访问
- [x] `ThreadSafeLRUCache` 支持 TTL 过期（默认 300s）
- [x] `ThreadSafeLRUCache` 支持 LRU 淘汰（默认 128 条）
- [x] `app/db/session.py` 中 `_query_cache` 类型为 `ThreadSafeLRUCache`
- [x] `_make_cache_key` 不再使用 `hashlib.md5`
- [x] `tests/test_db/test_session_cache.py` 存在且 ≥5 条用例 — **新建 9 条，2026-06-07**
- [x] `pytest tests/test_db/test_session_cache.py` 全部通过 — **9 passed**
- [x] 现有 `tests/test_db/` 测试全部通过（无回归）

### P0-2: app_factory.py 拆分

- [x] `create_app()` 函数体 ≤150 行 — **实测 ~78 行，2026-06-07**
- [x] 以下私有函数存在且有明确单一职责：
  - [x] `_init_database()`
  - [x] `_init_event_subscribers()`
  - [x] `_init_background_jobs()`
  - [x] `_register_core_routes()`
  - [x] `_register_optional_routes()`
  - [x] `_register_diagnostics()`
- [ ] `tests/test_app_factory.py` 存在且覆盖：（仍缺）
  - [ ] `AppConfig(profile="llm-only")` 路径
  - [ ] 可选路由加载失败不崩溃
  - [ ] 各子函数可独立调用
- [ ] 现有 `MODstore_deploy/tests/` 测试全部通过（部分预存失败，见 P3 阻塞项）

### P0-3: requirements.txt 依赖分类

- [x] `requirements.txt` 不包含以下包名 — **已验证 2026-06-07（仅含 `-r requirements-base.txt`）**
  - [x] pytest
  - [x] pytest-cov
  - [x] pytest-mock
  - [x] pytest-asyncio
  - [x] miniaudio
  - [x] faster-whisper
  - [x] PyAudio
  - [x] soundcard
  - [x] imageio-ffmpeg
- [x] `requirements-ml.txt` 包含上述 ML 依赖
- [x] `pip install -r requirements.txt` 成功
- [x] `pip install -e ".[dev]"` 成功
- [x] `uvicorn app.fastapi_app:get_fastapi_app --factory` 可启动（`APP IMPORT OK`）

---

## P1 验收

### P1-1: FHD-个人 测试覆盖率

- [x] CI 全量 `source=[app]` 棘轮 `coverage_ratchet.py --check`（行 floor **84%**）
- [x] `pyproject.toml` `fail_under=84`（全量口径，非窄包 70%）
- [x] API 响应信封：`app/` + `mods/` JSON `"ok"` 已全量迁移为 `"success"`（`response_envelope.py` SSOT）
- [x] 前端 `vitest run` 有 ≥5 个 API/Store 测试文件 — **`src/api/__tests__/` + `src/stores/__tests__/`**
- [x] CI 前端 `vue-tsc --noEmit` 硬门禁
- [x] Codecov `fail_ci_if_error: true`

### P1-2: 成都修茈 测试覆盖率

- [ ] `pytest --cov=modstore_server --cov-fail-under=55 --cov-report=term-missing` 通过（依赖完整服务环境；本地 2 个测试预存失败）
- [ ] `.github/workflows/ci-backend-python.yml` 中 `MODSTORE_PY_COVERAGE_FLOOR` 更新为 55

### P1-3: mypy 清理

- [x] FHD-个人：`mypy strict gate`（4 路径）零错误 — **2026-06-07**
- [x] FHD-个人：`pyproject.toml` 中 `tests.*` 不再整包 `ignore_errors = true`（改为 `disable_error_code`）
- [x] 成都修茈：`mypy --no-error-summary` 零错误 — **2026-06-07（宽口径调整后）**
- [x] FHD-个人：`pyproject.toml` 宽口径 ≤6（已达成 6/6）

### P1-4: 临时脚本归档

- [x] `scripts/` 根目录下无 `fix_*.py` 文件 — **2026-06-05 归零**
- [x] `scripts/` 根目录下无 `check_*.py` 文件（保留 `scripts/dev/` 下的除外）— **2026-06-05 归零**
- [x] `scripts/db_ops/` 目录存在且包含数据库运维脚本
- [x] 管理类一次性脚本已归档 — 无独立 `admin/`；见 [`FHD/scripts/_archived/`](../FHD/scripts/_archived/)
- [x] `scripts/debug/` 目录存在且包含调试脚本
- [x] `scripts/README.md` 已更新目录说明（含 [`FHD/docs/ENV_FILES.md`](../FHD/docs/ENV_FILES.md) 链）

---

## P2 验收

### P2-1: 成都修茈 DDD 分层启动

- [x] `modstore_server/application/` 目录存在 — **超额：≥10 个 service 文件**
- [x] `modstore_server/application/` 包含 ≥3 个 service 文件
- [x] `modstore_server/domain/` 目录存在 — **包含 employee.py + mod_catalog.py + neuro_domain.py**
- [x] `modstore_server/domain/` 包含 ≥2 个领域模型文件
- [x] 新增文件不在 mypy ignore 列表中（`application.*`/`domain.*` 已 `ignore_errors = false`）
- [x] `mypy modstore_server/application/` 零错误 — **2026-06-07**
- [x] `mypy modstore_server/domain/` 零错误 — **2026-06-07**

### P2-2: FHD-个人 前端 TypeScript 严格化

- [x] `frontend/tsconfig.json` 包含 `"strict": true` — **已验证 2026-06-07**
- [ ] `cd frontend && npx vue-tsc --noEmit` 零错误（src/ 内 14 个预存错误；AMIN/ 580 个预存错误）
- [x] `frontend/src/api/` 所有导出函数有完整类型签名（补充了 6 个缺失方法）
- [x] `cd frontend && npm run build` 通过 — **2026-06-07**
- [x] `cd frontend && npm run build:full` 通过 — **2026-06-07**

---

## PR 合并测试纪律（所有改动 FHD / MODstore 的 PR）

命名规范：[`specs/test-naming.md`](test-naming.md)

- [x] 改 `app/fastapi_routes/*` 或 `app/http/*`：至少 1 条 `TestClient` 或 `tests/integration/` 用例
- [x] 改 `app/application/*`（含 `*_v2.py`）：应用服务单测或集成路径覆盖
- [x] 改 `frontend/src/api/*`：对应 `*.test.ts` 更新或新增（367 个 API 测试）
- [x] SPA fallback 顺序：`ensure_spa_fallback_last` 在 `spa_fallback.py`（Mod 批量挂载后调用）

## 测试与覆盖率治理（2026-05 计划）

- [x] FHD `ci-cd.yml` 全量 `--cov=app` + `coverage_ratchet.py --check`（行 floor **84%**）
- [x] FHD `backend-coverage-report` 全量 `--cov=app` 可观测（无 fail）
- [x] FHD `tests/integration/`：auth、ERP、finance/report、rbac
- [x] FHD 前端 `src/api` ≥5 个 `*.test.ts`（实际 30 个文件，367 测例）
- [x] MODstore `tests/integration/test_payment_webhook_flow.py` + `docs/coverage-gates.md`
- [x] 全量覆盖率棘轮 M3→Phase4（`fail_under` **84%** 行，分支 floor **73%**）已落地
- [ ] MODstore 全局 `pytest --cov-fail-under=55`（需完整服务环境）

---

## 全局回归检查（2026-06-07 实测）

- [x] FHD-个人：`ruff check app/ tests/` 零错误 — **2026-06-07 全绿**
- [x] FHD-个人：`ruff format --check app/ tests/` 零错误 — **2026-06-07 全绿**
- [x] FHD：pytest 全量套件 HEAD **85.07% 行**（2026-06-20 `bb5e15a7` bump）；WIP 2026-06-17 红灯已收口（purchase_service / wechat_* / tools_workflow / im_sync 全绿）
- [x] 成都修茈：`black --check modstore_server modman tests` 零错误 — **2026-06-07 全绿**
- [x] 成都修茈：`isort --check-only modstore_server modman tests` 零错误 — **2026-06-07 全绿**
- [x] 成都修茈：`flake8 modman/ modstore_server/ tests/` 零错误 — **2026-06-07 全绿（含 .flake8 配置）**
- [x] 成都修茈：`mypy --no-error-summary` 零错误 — **2026-06-07 全绿**

---

## 本地范围外 / 阻塞项（不在本轮内，见 plan BLOCKERS.md T36–T37/T59）

- ⛔ **staging 7 天 SLO**（T36/T37）：K3d/KinD/k3s 本机不可用；staging 7 天流量/截图依赖独立 K8s
- ⛔ **拆仓 push**（T59）：`git subtree split` dry-run 已生成，push 需 git-filter-repo
- ⛔ **docker build**：需 Docker 守护进程（macOS Docker Desktop 未挂载）
- ⛔ **全栈 e2e**：已有 mock 14/14，full_stack 需起后端服务 + Playwright 浏览器
- ⛔ **windows-only 测试**：`backend-test` 在 `windows-latest` 跑（`test_erp_*`），macOS 仅近似复现
- ⛔ **`tests/test_app_factory.py`**（MODstore）：P0-2 遗留，create_app 拆分已完成但测试文件尚未补充
