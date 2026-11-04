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

## 3. 产出：与新框架同构的验收记录

本轮能力中心已改为**按平台分别判定**（详见同目录上级 `WINDOWS-HANDOFF.md`）。因此 Windows 侧不能只给一份
「verdict 摘要」，必须给出与 macOS 同一结构的记录 `base-login-windows-run.json`——**脚本已直接产出该文件**，
不需要手工拼。

脚本产出（都在 `<OutDir>` 下）：

| 文件 | 用途 |
|------|------|
| `base-login-windows-run.json` | 能力中心读取的验收记录，`platform="windows"`、与 `base-login-macos-run.json` 同构 |
| `base-login-windows-identity.json` | 安装目录/版本/SHA/探活快照（作为该平台的原始抓取） |
| `shot\` `video\` `log\` | 截图、录屏与本轮日志 |

记录里的机器字段（`status` / `passed` / `failed` / `cases[].result` / `observed` / `app_git_sha` /
`app_version` / `verified_at`）由脚本自动生成，**一律不得手改**。六项证据缺一最高只能 `PARTIAL`：
截图 + 视频 + 日志 + 产品版本 + 应用 SHA + 验证时间（口径见 `windows-evidence-1.0.0.5/rules.json`）。
失败时保留现场与原始 JSON，写明第一个真实断点（`first_real_breakpoint`）。

### 3.1 唯一允许你填写的部分：媒体内容复核

脚本把 `media[]` 每一项都写成 `visual_review: "pending_review"`、`visible_result: ""`、`reviewed_at: ""`。
**这是故意的**：能力中心会拒绝未经复核的媒体，所以不会因为你跑完脚本就自动变绿。

你的动作：逐张打开 `shot\` 里的截图、逐段看完 `video\` 里的录像，然后把**该文件**对应的三项填上：

- `visual_review` → `"accepted"`（只有你真的看过、且画面与说明一致时才填）；
- `visible_result` → 你在这张图/这段录像里**实际看到**的内容（例如登录页标题、输入框、
  「登 录」按钮、工作台左侧导航与账号名）。不得照抄 macOS 的描述，不得写你没看到的结论；
- `reviewed_at` → 复核日期 `YYYY-MM-DD`。

若画面与预期不符，**不要**填 `accepted`：保持 `pending_review` 并如实写明你看到了什么，
同时在日志里记录——这属于必须如实回传的失败信息。

## 4. 回传

把整个 `OutDir`（`base-login-windows-run.json` + `base-login-windows-identity.json` + `shot\` + `video\` + `log\`）
回传到 `FHD/docs/evidence/e2e/feature-acceptance-20260922/base-login/windows/`：从 **main** 新建回传分支
（例如 `evidence/feature-acceptance-base-login-20260922-windows`），把这几个文件与子目录原样提交进去开 PR，
由 Mac 侧复核合并（`evidence/feature-acceptance-base-login-20260922` 是上一轮的历史分支，**不要**再往里提交）。
并在 issue #2007 回评论说明 verdict 与任何 FAIL/BLOCKED 的第一断点。

回传后由 Mac 侧在目录里登记（`evidence.runs` / `evidence.videos` / `evidence.screenshots` /
`evidence.platform_assets.windows`），本功能才算 Windows 侧验收成立；在此基础上才推进下一个功能。
方法：整目录带回收即可——把 `shot\`、`video\`、`log\` 原样拷进
`.../base-login/windows/` 下同名子目录，记录与身份文件放在该目录根（脚本已按 `-RepoRelDir`
写好 `media[].path`，路径自然对齐）。

## 5. 2026-09-24 复验轮（同一目录，记录被本轮取代）

本轮按「当前正在交付的安装包」重新做了一轮完整验收，覆盖此前的 6 个用例并补齐三个新用例：

| 用例 | 覆盖 |
|------|------|
| W0 安装 + 首次启动 | 官网下载指针（`download-windows-hotfix.json`）与实装安装包 sha256、`resources/build-info.json` 三方一致；内嵌后端存在；全新空数据目录下首启停在登录页、无会话 |
| W4b 退出后重启不恢复 | 真实 GUI 退出登录 → 关闭应用 → 重启 → 仍停在登录页，退出前捕获的 session cookie 已被拒绝 |
| W7 前后端状态一致 | 已登录工作台稳态：`/api/health` 全绿且侧栏状态文字「系统正常」与载荷一致；重启后的冷启动预热窗口（neuro/本地 LLM 未就绪）与登出态载荷如实记录，不隐藏 |

执行方式（本轮脚本、操作员与采样日志都在 `log/` 里）：

1. 覆盖安装官网当前交付包（同版本；安装包先复制到本地磁盘，网络盘会触发 Windows 的
   “打开文件-安全警告”对话框挡住静默安装），安装事实见 `log/install-facts.json`；
2. 全新空数据目录 + `XCAGI_DESKTOP_USER_DATA_DIR` 隔离启动，`log/install-facts.json` 与
   `base-login-windows-identity.json` 的 `backend_cmdline` 可核对 `--data-dir` 确实指向隔离目录；
3. `operator-base-login.mjs --phase a`（首启/登录/登出/再登录 + 截图 + 录像 A）→
   `accept-base-login.ps1 -WithVideo ... -OperatorJson ... -OperatorJsonPost ...` →
   `operator-base-login.mjs --phase c`（登出/重启/断言/稳态采样）。

新增工具（与本目录其余脚本同一接口）：`operator-base-login.mjs`（真实 GUI 驱动 + 事实 JSON）、
`cdp.mjs`（CDP 客户端）、`health-sampler.ps1` / `ui-sampler.mjs`（后端与前端状态时间线）、
`record-until-marker.ps1`（按标记文件开关的整屏录像，`-b:v 600k`）。
录像与后端/前端时间线文件较大（`log/health-timeline.jsonl`、`log/ui-timeline.jsonl` 约 240 KB），
均为本轮原始抓取，未做裁剪。