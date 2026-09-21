# base-login「登录与会话管理」Windows 真机验收交接（本轮 2026-09-22）

> 交接对象：Windows 侧 AI / 执行人。目标：在 **Windows 真机**上独立完成能力中心功能
> 「登录与会话管理」（catalog id `base-login`，平台含 windows）的本轮实机验收，
> 产出**本轮**证据（历史证据不算）。**不得用 macOS 侧证据替代**。
>
> 脚本 `accept-base-login.ps1` 为 ASCII-only 源码（Windows PowerShell 5.1 会把无 BOM 的
> UTF-8 当 ANSI 解码，中文字面量会变乱码，因此脚本内字符串全部用英文；本 markdown 不受影响）。

## 0. 前置与自检（先跑这一步，不产生副作用）

- 机器上已安装 XCAGI 桌面客户端（Enterprise），后端在 `127.0.0.1:17500`。
- **企业验收账号凭据不再写在脚本/本文里**（仓库是公开仓库）。请由操作员按既有约定提供：
  - 环境变量：`$env:XCAGI_TEST_USER`（默认 SUNBIRD）、`$env:XCAGI_TEST_PASS`（必填）；
  - 或命令行显式传 `-Account/-Password`；
  - 既有参考：仓库主线的 `FHD/scripts/package/acceptance-sunbird-windows.ps1`（同一验收账号的来源）。
  未提供密码时脚本会立即以清晰提示退出（exit 2），不会跑出半截证据。
- **2026-09-19 那轮 base-login 之所以是 BLOCKED，原因就是当时没有企业账号凭据**
  （记录见 `windows-evidence-1.0.0.5/records.jsonl` 的 base-login：MARKET_AUTH_FAILED + 登录按钮保持禁用）。
  这一轮把凭据交给操作员后，同一套用例可以真正跑完成功路径。
- 先运行自检（只读：解析安装目录/版本/SHA、探活、探一次 `/api/auth/me`）：

```powershell
$env:XCAGI_TEST_PASS = '<由操作员提供>'
powershell -ExecutionPolicy Bypass -File .\accept-base-login.ps1 -SelfTest
```

自检会打印 `app_dir / exe_sha256 / git_sha / product_version / backend health / app processes / ffmpeg / api me`。
若 `backend health` 不是 200，先启动客户端并等本地服务就绪，再进入正式轮。

## 1. 正式运行（身份 + API 断言 + 截图/录屏 + 打包）

```powershell
powershell -ExecutionPolicy Bypass -File .\accept-base-login.ps1 -WithVideo `
  -InstallerPath "C:\...\XCAGI-Enterprise-Setup-1.0.0.5-x64-unsigned.exe" `
  -OutDir "C:\XCAGI-acceptance\feature-base-login"
```

脚本自动执行（全部是真实 HTTP 打到本机后端）：

| 用例 | 断言 | 判据 |
|------|------|------|
| W1 未登录拒绝 | 无会话访问 `/api/auth/me`、`/api/auth/session/validate` | 两者 `valid=false` |
| W2 企业账号登录（API 侧） | `POST /api/auth/login` → `Set-Cookie: session_id` → `GET /api/auth/me` | 200 且 `success=true`、`account_kind=enterprise` |
| W3 会话保持（进程重启） | 结束 XCAGI 进程 → 重新启动 → 同一 cookie 再访问 | health 200 且 `me.success=true`、`validate.valid=true` |
| W4 安全退出 | `POST /api/auth/logout` → 旧 cookie 再访问 | 退出前 200，退出后 `valid=false` |
| W5 边界负例 | 错误密码 / `account_kind=admin` / 空凭据 | 三者均 `success=false` |
| W6 Web 端同账户体系 | 同一账号在修茈市场（Web）`POST https://xiu-ci.com/api/auth/login` | `ok=true` 且带 `access_token` |

脚本同时录制桌面视频（需要 ffmpeg；未找到会记 `video=false` 并降级为 PARTIAL）并截屏 W3 重启后画面。
`-SkipRestart` 可跳过 W3（不建议）。执行策略被拦时统一用 `-ExecutionPolicy Bypass`。

## 2. 必须由人/AI 在真实 GUI 上完成的步骤（脚本不代劳）

在脚本运行期间（视频在录）用真实鼠标键盘操作 XCAGI 窗口：

1. **W2-GUI**：退出已有会话（若已登录）→ 停在登录页，截图存 `shot\W2-login-page.png`；
   输入操作员提供的 `XCAGI_TEST_USER / XCAGI_TEST_PASS`（验收账号）→ 点「登 录」→ 进入工作台（应出现左侧导航、主区「智能对话」、
   左上角显示账号 SUNBIRD），截图存 `shot\W2-login-workspace.png`。
2. **W4-GUI**：在工作台执行「退出登录」（macOS 侧路径为 系统设置 → 账号卡片「退出登录」→
   确认「确定退出本机账号？」→「确定」；Windows 侧以实际界面为准，若入口不同请写明你走的路径），
   截图存 `shot\W4-login-page-again.png`，并在日志里写明退出路径与点击的按钮原文。
3. 观察并写进日志（`log\`）：每一步看到的标题/按钮/错误提示原文；有异常必须原样记录，不得只写结论。

## 3. 六项证据契约（`windows-evidence-1.0.0.5/rules.json`）

`PASS` 需要同时具备：截图 + 视频 + 日志 + 产品版本 + 应用 SHA + 验证时间；缺一项最高只能 `PARTIAL`。
脚本输出的 `base-login-windows.json` 会给出 `six_elements` 与总 verdict（FAIL/PARTIAL/PASS/BLOCKED），
**不要手改 verdict**；失败时保留现场与原始 JSON，写明第一个真实断点（`first_real_breakpoint`）。

## 4. 回传

把整个 `OutDir`（`base-login-windows.json` + `identity.json` + `shot\` + `video\` + `log\`）回传到
`FHD/docs/evidence/e2e/feature-acceptance-20260922/base-login/windows/`（提交到分支
`evidence/feature-acceptance-base-login-20260922` 或新建回传分支由 Mac 侧合并），
并在 issue #2007 回评论说明 verdict 与任何 FAIL/BLOCKED 的第一断点。
回传后本功能才算 Windows 侧验收成立；在此基础上才推进下一个功能。