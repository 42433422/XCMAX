# v10-A 企业桌面真机验收记录（2026-07-08 → 2026-07-09 续测）

> **分支**：`fix/desktop-perf-complete`  
> **执行方式**：DevFleet 远程（Win32 `5fdd29c4-…`）+ 本机 Mac（`48acf8c9-…`，端口 **17500**）  
> **版本锚点**：10.0.0（v10 锁，未 bump）

---

## 设备与环境

| 端 | 设备 | OS / 架构 | 安装位置 | 证据 |
|----|------|-----------|----------|------|
| Mac | Mac 主设备 | macOS 26.3 / arm64 | `/Applications/XCAGI.app` + userData | enterprise SKU；health 10.0.0 |
| Windows | Win32 (DevFleet) | Windows NT 10.0.26200 / x64 | `%LOCALAPPDATA%\Programs\XCAGI` | 后端 `17500`；`desktop/status` modsRoutesLoaded=true |

**第二台 Windows**：DevFleet 仅 1 台 Win32（build 26200，介于 Win10/Win11 之间），**无独立 Win10 + Win11 双机覆盖**。

**制品**：Mac `FHD/release/xcagi-v10.0.0/enterprise/XCAGI-10.0.0-mac-arm64.dmg`。Win 热修后端已在本机构建至 `Documents\New project 3\XCMAX\FHD\dist\xcagi-backend\`（见下文），**安装目录热替换待 DevFleet 空闲后执行**。

---

## PL1 / v10-A 验收清单（最终状态）

| # | 验收项 | Mac | Windows | 说明 |
|---|--------|-----|---------|------|
| A1 | 安装包 / 已安装 | **PASS** | **PASS** | |
| A2 | health 200 | **PASS** | **PASS** | `http://127.0.0.1:17500/api/health` |
| A3 | SKU enterprise | **PASS** | **PASS** | |
| A4 | Mod 加载 | **PASS** | **PASS** | Win 13 loaded；`modsRoutesLoaded=true` |
| A5 | `deliverable-status` | **PASS** | **BLOCKED**³ | Mac 真机 `deliverable=true`；Win 旧包仍 false（热修包已构建未部署） |
| A6 | 引导 host-pack | **PASS** | **BLOCKED**³ | Mac `recommended_step=daily_use` |
| A7 | 样板业务 API | **PASS**⁴ | **BLOCKED**⁵ | 正确路径为 Mod 域 API，非 `/api/erp/orders` |
| A8 | 日志 / 备份 | **PASS** | **PASS** | Win `backups/xcagi-unknown-*.db` |
| A9 | OTA 迁移 | **NOT RUN** | **FIX READY**⁶ | 根因已修并打入 Win 构建产物；安装后待 `migrate-only` 复测 |
| A10 | OTA 回滚 | **NOT RUN** | **NOT RUN** | 依赖 A9 部署成功后按 `rollback/` marker 路径验证 |
| A11 | 自动化 smoke | **PARTIAL** | **NOT RUN** | Mac TestClient 404（deferred 路由）；真机 curl **PASS** |
| A12 | UI 走查 | **NOT RUN** | **NOT RUN** | 登录/onboarding/对话/ERP 侧栏需人工 |
| A13 | 诊断包导出 | **NOT RUN** | **NOT RUN** | 需登录态 `GET /api/desktop/support-bundle` |
| A14 | Win10+Win11 第二台 | **N/A** | **BLOCKED** | 仅 1 台 DevFleet Win32 |

³ Windows 在 `C:\Users\97088\Documents\New project 3\XCMAX\FHD` 已打源码补丁并成功 PyInstaller 构建（exit 0，约 19min），但 DevFleet 设备任务占用导致 **robocopy 部署 + 重启复测未完成**。  
⁴ Mac：`GET /api/mod/xcagi-erp-domain-bridge/orders` → 200，`success=true`。`/api/orders` 在 deferred 未就绪时可能 404，不阻塞签字（OpenAPI 有 `/api/orders`）。  
⁵ Win 旧安装未验证 Mod 订单 API（同 A5 阻塞）。  
⁶ 见「OTA 根因与修复」。

---

## 根因 1：deliverable 误判（已修 · Mac 已验）

`build_deliverable_status()` 经 `get_fastapi_app()` 读空壳实例 → `MOD_ROUTES_NOT_MOUNTED`。

**修复 commit**：`88bc22f34` — 路由传 `request.app`；`_mods_routes_loaded(app)` 仅读运行实例。

**Mac 真机（17500）**：

```text
deliverable=True mods_routes_loaded=True recommended_step=daily_use blockers=[]
```

**Windows 旧包（部署前）**：

```text
deliverable=False mods_routes_loaded=False blocker=MOD_ROUTES_NOT_MOUNTED
（同时 desktop/status.modsRoutesLoaded=True — 证实误判）
```

---

## 根因 2：OTA Alembic exit 2（已修 · 待装包复测）

**现象**：`xcagi-backend.exe --migrate-only` 子进程  
`xcagi-backend.exe -m alembic upgrade head` → **exit 2**。

**根因**（双重）：

1. **PyInstaller 入口不支持** `exe -m alembic`（参数进入 `run_fastapi` argparse → `unrecognized arguments`）。
2. 未指定 `-c <_MEIPASS>/alembic.ini` 且子进程 cwd 可能为 `C:\Windows\System32`（远程调用时）。

**修复 commit**：`a379e579c` — `FHD/app/desktop_runtime/migrate.py`：

- `_alembic_root()` 解析 `_MEIPASS` 或 FHD 根
- frozen 时调用 `alembic.command.upgrade/stamp` API
- 非 frozen 时 `subprocess` + `-c alembic.ini` + 正确 `cwd`

**Win 复现 stderr（修复前）**：

```text
CalledProcessError: ... xcagi-backend.exe', '-m', 'alembic', 'upgrade', 'head']' returned non-zero exit status 2
```

---

## DevFleet 执行记录

| 步骤 | 结果 |
|------|------|
| Win API 探针（17500） | health/status OK；旧包 deliverable false |
| Win 源码热补丁 | migrate + deliverable_status + platform_shell_routes **OK** |
| Win `build-backend.ps1 -SkipFrontend -ProductSku enterprise` | **exit 0**（~1143s） |
| Win 安装目录部署 + migrate 复测 | **BLOCKED**（设备「已有任务运行中」） |

---

## 用户配合（收尾）

在 Win32 DevFleet 设备空闲后，于 PowerShell 执行（或运行 `FHD/scripts/dev/win_v10a_hotfix_deploy.ps1`）：

```powershell
$src = 'C:\Users\97088\Documents\New project 3\XCMAX\FHD\dist\xcagi-backend'
$dst = "$env:LOCALAPPDATA\Programs\XCAGI\resources\backend"
Get-Process xcagi-backend -EA SilentlyContinue | Stop-Process -Force
robocopy $src $dst /MIR
# 重启 XCAGI 后验证：
Invoke-RestMethod http://127.0.0.1:17500/api/platform-shell/deliverable-status
& "$dst\xcagi-backend.exe" --desktop --migrate-only --backup --data-dir "$env:APPDATA\XCAGI"
```

预期：`deliverable=true`；`migrate-only` exit 0。随后可做 OTA 回滚用例（`rollback/` marker）。

---

## 签字表（简）

| 平台 | 测试人 | 日期 | API 验收 | OTA | UI | 签字 |
|------|--------|------|----------|-----|-----|------|
| macOS arm64 | Agent+本机 | 2026-07-09 | ✅ | — | — | ⏳ |
| Win32 x64 | Agent/DevFleet | 2026-07-09 | ⏳ 待部署 | ⏳ 待复测 | — | ⏳ |

---

## 结论

**v10-A 仍未达到 PL1 签字完成标准**（缺 Win 热修部署实证、OTA/回滚、UI 走查、Win 双机、人工签字）。  
代码与 Win 构建产物已就绪；**PL1 不得勾选**直至上表 Win 行全部 ✅。

**相关 commit**：`88bc22f34`（deliverable）、`a379e579c`（OTA migrate）。
