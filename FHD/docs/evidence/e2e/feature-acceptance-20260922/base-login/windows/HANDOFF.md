# base-login「登录与会话管理」Windows 真机验收交接（本轮 2026-09-22）

> 交接对象：Windows 侧 AI / 执行人。目标：在 **Windows 真机**上独立完成能力中心功能
> 「登录与会话管理」（catalog id `base-login`，平台含 windows）的本轮实机验收，
> 产出**本轮**证据（历史证据不算）。**不得用 macOS 侧证据替代**。

## 0. 前置

- 机器上已安装 XCAGI 桌面客户端（Enterprise），后端在 `127.0.0.1:17500`。
- 记录本次验收使用的安装包身份（installer sha256 + `resources\build-info.json` 的 `gitSha`/`version`）。
  脚本会自己抓 `build-info.json` 与 `XCAGI.exe` 的 sha256；如果手工安装，请把安装包路径用 `-InstallerPath` 传入。
- 企业验收账号：`SUNBIRD / SUN123456`（真实修茈市场企业账号，桌面端仅企业账号可登录）。

## 1. 运行（API + 身份 + 证据打包）

```powershell
cd <拷贝到 Windows 的目录>
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
| W6 Web 端同账户体系 | 同一账号在修茈市场（Web）`POST https://xiu-ci.com/api/auth/login` | `success=true` |

脚本同时录制桌面视频（需要 ffmpeg；未找到会记 `video=false`）并截屏 W3 重启后画面。

## 2. 必须由人/AI 在真实 GUI 上完成的步骤（脚本不代劳）

在脚本运行期间（视频在录）用真实鼠标键盘操作 XCAGI 窗口：

1. **W2-GUI**：退出已有会话（若已登录）→ 停在登录页，截图存 `shot\W2-login-page.png`；
   输入 `SUNBIRD / SUN123456` → 点「登 录」→ 进入工作台（应出现左侧导航、主区「智能对话」、
   左上角显示账号 SUNBIRD），截图存 `shot\W2-login-workspace.png`。
2. **W4-GUI**：在工作台执行「退出登录」（若界面无该入口，用系统托盘/菜单退出应用后重新打开，停在登录页），
   截图存 `shot\W4-login-page-again.png`，并在日志里写明你走的是哪条退出路径。
3. 观察并写进日志（`log\`）：每一步看到的标题/按钮/错误提示原文；有异常必须原样记录，不得只写结论。

## 3. 六项证据契约（`windows-evidence-1.0.0.5/rules.json`）

`PASS` 需要同时具备：截图 + 视频 + 日志 + 产品版本 + 应用 SHA + 验证时间；缺一项最高只能 `PARTIAL`。
脚本输出的 `base-login-windows.json` 会给出 `six_elements` 与总 verdict（FAIL/PARTIAL/PASS/BLOCKED），
**不要手改 verdict**；失败时保留现场与原始 JSON。

## 4. 回传

把整个 `OutDir`（`base-login-windows.json` + `shot\` + `video\` + `log\`）回传到 Mac 侧，
放在 `FHD/docs/evidence/e2e/feature-acceptance-20260922/base-login/windows/` 下（或提交到交接分支，
由 Mac 侧合并）。回传后本功能才算 Windows 侧验收成立；在此基础上才推进下一个功能。