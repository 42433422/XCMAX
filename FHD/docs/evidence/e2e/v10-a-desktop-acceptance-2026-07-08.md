# v10-A 企业桌面真机验收记录（2026-07-08）

> **分支**：`fix/desktop-perf-complete`  
> **执行方式**：DevFleet 远程（Win32 `5fdd29c4-…`）+ 本机 Mac（`48acf8c9-…` 主设备，本地 shell 补测）  
> **版本锚点**：10.0.0（v10 锁，未 bump）

---

## 设备与环境

| 端 | 设备 | OS / 架构 | 安装位置 | 证据 |
|----|------|-----------|----------|------|
| Mac | Mac 主设备 | macOS 26.3 / arm64 | `/Applications/XCAGI.app` + userData | `product-sku.json` → enterprise；`CFBundleShortVersionString` 10.0.0 |
| Windows | Win32 (DevFleet) | Windows NT 10.0.26200 / x64 | `%LOCALAPPDATA%\Programs\XCAGI` | `XCAGI.exe` FileVersion 10.0.0；`product-sku.json` enterprise |

**制品**：`FHD/release/xcagi-v10.0.0/enterprise/XCAGI-10.0.0-mac-arm64.dmg`（283MB，含 `latest-mac.yml`）。仓库内未找到 Windows `*Enterprise*Setup*.exe` 本地副本；Windows 机已装 10.0.0 企业版。

---

## PL1 / v10-A 可执行验收清单（精简）

| # | 验收项 | Mac | Windows | 说明 |
|---|--------|-----|---------|------|
| A1 | 安装包存在 / 已安装 | **PASS** | **PASS** | Mac 有 dmg；Win 已装含 `xcagi-backend.exe` |
| A2 | 首启 health 200 | **PASS** | **PASS** | `/api/health` version=10.0.0 |
| A3 | SKU 识别 enterprise | **PASS** | **PASS** | product-sku.json |
| A4 | Mod 加载 | **PASS** | **PASS** | Mac 17 mods；Win 13 mods；`modsRoutesLoaded=true` |
| A5 | `deliverable-status` | **PASS**¹ | **FAIL**² | 见下文根因与修复 |
| A6 | 引导 / host-pack | **PASS**¹ | **BLOCKED** | Mac 修复后 `recommended_step=daily_use` |
| A7 | 样板业务 API | **PARTIAL** | **PARTIAL** | `/api/erp/orders` 404（路由前缀待 UI/登录态验证） |
| A8 | 日志 / 备份 | **PASS** | **PASS** | userData 含 logs、backups、electron-backend.log |
| A9 | OTA 升级 | **NOT RUN** | **FAIL** | Win `updater-events.jsonl`：`install_failed` Alembic exit 2 |
| A10 | 回滚 | **NOT RUN** | **NOT RUN** | 未触发损坏包回滚用例 |
| A11 | 自动化 smoke | **PARTIAL** | **NOT RUN** | `mac_deliverable_smoke.sh` TestClient 缺 deferred 路由 404（脚本环境限制） |

¹ Mac 在修复 `build_deliverable_status` 并重启 headless 后端后：`deliverable=true`，`blockers=[]`。  
² Windows `desktop/status` 显示 `modsRoutesLoaded=true`，但旧版 `deliverable-status` 误报 `MOD_ROUTES_NOT_MOUNTED`（同代码缺陷，需新包或热修后重启）。

---

## 根因（已修）

`build_deliverable_status()` 通过 `get_fastapi_app()` 懒创建**空壳** FastAPI 实例读取 `mods_routes_loaded`，与 uvicorn 实际服务实例不一致，导致真机 Mod 已挂载仍 `deliverable=false`。

**修复**（v10 线内迭代，未升版）：

- `deliverable-status` 路由传入 `request.app`
- `_mods_routes_loaded()` 仅查询运行实例，无实例时不误报

**Mac 复测证据**（修复 + 重启 `run_fastapi.py` 后）：

```text
deliverable= True mods_routes= True blockers= []
```

---

## DevFleet 连接

| 步骤 | 结果 |
|------|------|
| `devfleet_list_devices` | Mac 主设备 + Win32 均 online |
| `devfleet_preflight_remote_control` | **超时**（shell session opening） |
| `devfleet_run_remote_command` | **可用**，完成 Win 预检/探针/汇总 |

---

## 阻塞项与用户配合

1. **Windows 需重装/打补丁**：合入 deliverable-status 修复后发 10.0.0 热修包，或从 `fix/desktop-perf-complete` 构建 enterprise exe 后重装；重启 XCAGI 再验 `deliverable=true`。
2. **Windows OTA 迁移失败**：`alembic upgrade head` exit 2，需单独排查 `migrate.py` / 打包内 alembic 路径（与 deliverable 误判无关）。
3. **Mac 远程命令超时**：主设备对自身 DevFleet 远程 bash 120s 无响应，本机 shell 补测。
4. **签字级全链路**：`desktop-real-machine-acceptance-2026-07-05.md` 要求 Win10+Win11+macOS 共 3 台、OTA 回滚实测、人工签字——**本次未全部完成**，PL1 不得勾选完成。

---

## 签字状态

**结论**：v10-A **未签字完成**。核心 API 误判已修并在 Mac 验证；Windows 待新包 + OTA/回滚复测 + 人工 UI 走查。
