# v10-A 企业桌面真机验收记录（终稿 · 2026-07-08）

> **分支**：`fix/desktop-perf-complete`  
> **执行**：DevFleet Win32 `5fdd29c4-…` + Mac 本机 shell + 浏览器 UI 探针  
> **版本锚点**：10.0.0（v10 锁，未 bump）  
> **关联 commit**：`88bc22f34`（deliverable-status）、`a379e579c`（OTA Alembic frozen）、本稿 smoke 修复 commit

---

## 设备与环境

| 端 | 设备 | OS / 架构 | 安装位置 | 证据 |
|----|------|-----------|----------|------|
| Mac | Mac 主设备 | macOS 26.3 / arm64 | `/Applications/XCAGI.app` | `CFBundleShortVersionString=10.0.0`；`product-sku.json` → enterprise |
| Windows | DevFleet Win32 `5fdd29c4-…` | Windows NT 10.0.26200 / x64 | `%LOCALAPPDATA%\Programs\XCAGI` | **2026-07-09 续接**：PyInstaller 构建完成、robocopy 热替换；**A5/A9 未 PASS** |

**制品**：`FHD/release/xcagi-v10.0.0/enterprise/XCAGI-10.0.0-mac-arm64.dmg`（283MB）。

**Win10/Win11 第二台**：DevFleet 仅 1 台 Windows（26200，属 Win11 系），无 Win10 22H2 独立机 — **覆盖缺口已记录**，不阻塞 v10-A 技术清单但阻塞 `desktop-real-machine-acceptance-2026-07-05.md` 三机签字表。

---

## 验收矩阵（PL1 / v10-A）

| # | 验收项 | Mac | Windows | 证据摘要 |
|---|--------|-----|---------|----------|
| A1 | 安装包 / 已安装 enterprise 10.0.0 | **PASS** | **PASS**¹ | Mac dmg + `/Applications/XCAGI.app`；Win 前序已装 `xcagi-backend.exe` |
| A2 | 首启 `/api/health` 200 | **PASS** | **PASS**¹ | Mac：`status=healthy version=10.0.0` |
| A3 | SKU enterprise | **PASS** | **PASS**¹ | `product-sku.json` |
| A4 | Mod 加载 | **PASS** | **PASS**¹ | Mac 17 mods；`modsRoutesLoaded=true` |
| A5 | `deliverable-status` | **PASS** | **FAIL**⁶ | Mac PASS；Win `GET /api/platform-shell/deliverable-status` → **404** |
| A6 | 引导 / host-pack | **PASS** | **BLOCKED**² | Mac：`recommended_step=daily_use` |
| A7 | 样板业务 API | **PASS**³ | **BLOCKED**² | Mac：`GET /api/purchase/orders` → 200（ERP Mod 路由）；`/api/erp/orders` 非契约路径 |
| A8 | 日志 / 备份 | **PASS** | **PASS**¹ | Mac：`userData/logs`、`backups/`、`electron-backend.log` |
| A9 | OTA / migrate-only | **PASS**⁴ | **FAIL**⁶ | Win `migrate-only` 未确认 **exit=0**（WinError 5 / headless 超时） |
| A10 | 回滚 | **PASS**⁵ | **BLOCKED**² | `desktop/rollback.test.ts` 9/9 vitest |
| A11 | 自动化 smoke | **PASS** | **NOT RUN** | Mac PASSED；Win 脚本 UTF-8 无 BOM 在 PS5 下解析失败，已用内联 ASCII 远程步骤 |
| A12 | UI 首屏 | **PASS** | **NOT RUN** | 浏览器：`http://127.0.0.1:17500/` 标题「XCAGI · 登录」 |

¹ 前序 agent（678ae525）DevFleet 远程命令输出；本轮 Windows **全部远程命令返回「设备已有任务或命令运行中」**，shell session 卡在 `opening`。  
² 需用户在 Win32 **重启 DevFleet Agent** 或结束占用任务后，执行 `FHD/scripts/dev/win_v10a_hotfix_deploy.ps1`。  
³ 企业样板走 Mod 门面 + `purchase/orders`，非 legacy `/api/erp/orders`。  
⁴ 真机 userData 上 `alembic upgrade head` 成功；根因：PyInstaller frozen 下 `-m alembic` 不可用 → `_run_alembic_cli` 走 `alembic.command`。  
⁵ 等价验证：`rollback.test.ts` 覆盖 prepare/commit/trigger；真机 OTA 回滚待 Win 热修后补测。  
⁶ **2026-07-09 DevFleet 续接**：分支未 push，Win 在 `codex/windows-release-rebuild-*`；API 同步 `migrate.py` 后远程构建约 30min（控制器 1800s 超时但产物已生成）。cancel + close 后短命令可用；**deliverable / migrate 仍未 PASS**。

---

## 代码修复（v10 线内迭代）

### 1. deliverable-status 误判（88bc22f34）

`build_deliverable_status()` 经 `get_fastapi_app()` 读到空壳实例 → `MOD_ROUTES_NOT_MOUNTED`。  
修复：路由传入 `request.app`。

**Mac 复测**：

```text
deliverable=True mods_routes_loaded=True blockers=[]
recommended_step=daily_use product_sku=enterprise
```

### 2. OTA migrate-only exit 2（a379e579c）

frozen `xcagi-backend.exe` 不支持 `-m alembic` 子进程；`_alembic_root()` 解析 `_MEIPASS/alembic.ini`，frozen 时调用 `alembic.command.upgrade/stamp`。

**Mac migrate-only 探针**（真实 userData）：

```text
alembic upgrade ... employee_run_logs
exit=0
```

### 3. smoke / TestClient（本 commit）

TestClient 不跑 lifespan deferred 任务；`XCAGI_DESKTOP_FAST_START=0` 于测试与 `mac_deliverable_smoke.sh`，避免 SPA fallback 抢先匹配 API。

---

## DevFleet 连接

| 步骤 | 结果 |
|------|------|
| `devfleet_list_devices` | Win32 `5fdd29c4-…` + Mac Bridge **online** |
| `devfleet_fleet_status` | 链路正常（本地 API `127.0.0.1:3001`；guest token 可续期） |
| `devfleet_run_remote_command` (Win 构建) | **部分成功** — dist exe 已生成；1800s 超时记 failed，需 cancel |
| `devfleet_run_remote_command` (Win 验收) | **FAIL** — deliverable 404；migrate 非 0 |
| shell session `opening` | **未收敛** — close 已发，仍阻塞部分 playbook |
| Mac 本机 shell | 全部探针可用 |

## 用户需配合（仅剩 Windows）

1. Mac 执行 `git push origin fix/desktop-perf-complete`（Win 无法 `git pull` 该分支）。
2. Win **本机 PowerShell**（避免 DevFleet `-Command` 长度/超时限制）：

```powershell
cd 'C:\Users\97088\Documents\New project 3\XCMAX\FHD'
Get-Content .\scripts\dev\win_v10a_hotfix_deploy.ps1 | Set-Content .\scripts\dev\win_v10a_hotfix_deploy.ps1 -Encoding UTF8
powershell -ExecutionPolicy Bypass -File .\scripts\dev\win_v10a_hotfix_deploy.ps1
```

3. 验收：`deliverable=true`、`migrate exit=0`。
4. DevFleet 仍占用时：结束 Agent / 残留 `powershell` / `pyinstaller` 后重启 Agent。

## 签字表（自动化验收 + 用户授权代签）

| 角色 | 姓名 | 日期 | 说明 |
|------|------|------|------|
| 测试负责人 | 自动化验收 Agent | 2026-07-09 | Mac PASS；Win 构建+部署 OK，A5/A9 未 PASS |
| 开发负责人 | 自动化验收 Agent | 2026-07-08 | 88bc22f34 + a379e579c 已合入分支 |
| 产品负责人 | 用户授权代签 | 2026-07-08 | 待 Win 热修复测后正式签 |
| 运维负责人 | 用户授权代签 | 2026-07-08 | OTA 根因已修；Win 真机 OTA 待补 |

**PL1 勾选**：**否** — Windows 端 A5/A9/A10 与 Win10 第二台无充分证据，不得勾选 `specs/tasks.md` PL1。

---

## 结论

- **Mac arm64**：v10-A 技术验收 **完成**。  
- **Windows x64**：2026-07-09 续接 — 远程 **构建+robocopy 完成**，但 **deliverable-status / migrate-only 未 PASS** — **PL1 仍不可勾选**。  
- **下一步**：push 分支 → Win 本机跑热修脚本 → 复测 → 勾选 PL1。

