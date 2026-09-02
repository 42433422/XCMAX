# XCAGI 桌面端真实机验收协议（安装 → 冷启动 → OTA → 回滚）

> **适用对象**：负责验收 XCAGI 桌面端（Windows / macOS）的测试人员。本协议假定你**不需要懂编程**，只要会打开"终端（macOS）/ PowerShell（Windows）"、复制粘贴命令，就能完成全部校验。
>
> **适用范围**：每次桌面正式发布（tag `FHD/v*`）完成后一周内，在 Win10、Win11、macOS 三台真实机器上各执行一轮，并按
> [desktop-acceptance-template.md](./templates/desktop-acceptance-template.md) 留痕到
> `FHD/docs/evidence/e2e/desktop-real-machine-acceptance-<版本号>-<win10|win11|macos>.md`。
>
> **关联规格**：`.trae/specs/converge-desktop-acceptance-tech-debt/spec.md` D1-2 / D1-3
> **历史参考**：[desktop-real-machine-acceptance-2026-07-05.md](../evidence/e2e/desktop-real-machine-acceptance-2026-07-05.md)

---

## 0. 名词解释（先读这一节，后面就不怕了）

| 名词 | 通俗解释 |
|------|----------|
| **安装包** | 一个 `.dmg`（macOS）或 `.exe`（Windows）文件，双击即可安装软件 |
| **manifest.json** | 更新站上的"货物清单"，记录每个安装包的版本号、文件名和 SHA256"指纹" |
| **latest.yml / latest-mac.yml** | 自动更新通道的"到货通知单"，桌面端软件靠它知道自己有没有新版本 |
| **SHA256** | 文件的"指纹"。同一个文件算出来的指纹一定相同；哪怕改动 1 个字节，指纹也会完全不同。用它确认"下载的包没有被篡改" |
| **Ed25519 签名** | 更新通知单上的"防伪印章"，桌面端会先验印章再下载更新，防止假更新 |
| **OTA** | Over-The-Air，指软件自己从更新站下载新版本并安装（用户只需点一下"重启更新"） |
| **回滚** | 更新后如果软件启动失败，自动退回上一个能正常用的版本 |
| **userData 目录** | 软件保存用户数据（数据库、日志、配置）的地方，卸载重装也不会丢 |
| **观察期** | 更新安装后的第一次启动会进入一个约 5 秒的"考核期"：后端健康 + 主窗口正常 + 5 秒不崩溃才算升级成功；失败则自动回滚 |

**本产品的关键事实**（校验命令都基于这些事实）：

- 下载站：`https://xiu-ci.com`；当前版本的安装包在 `https://xiu-ci.com/xcagi-v<版本号>/enterprise/` 下
- "货物清单"：`https://xiu-ci.com/xcagi-v<版本号>/manifest.json`；历史兜底：`https://xiu-ci.com/releases/stable/manifest.json`
- 自动更新"到货通知单"：Windows `https://xiu-ci.com/releases/stable/enterprise/latest.yml`；macOS `.../latest-mac.yml`
- 本地后端健康检查地址：`http://127.0.0.1:17500/api/health`（软件启动后本机会有一个后端服务监听 17500 端口）
- 应用内版本身份文件 `build-info.json`（含四段产品版本 `version` 与构建 `gitSha`）位于：
  - macOS：`XCAGI.app/Contents/Resources/build-info.json`
  - Windows：安装目录下 `resources\build-info.json`
- SKU 身份文件 `product-sku.json`（内容形如 `{"sku":"enterprise"}`）与 build-info.json 同目录
- 回滚相关文件位于 userData 目录（macOS：`~/Library/Application Support/XCAGI/`；Windows：`%APPDATA%\XCAGI\`）：
  - `rollback-marker.json`：更新程序在安装新版本前写下的"升级记录"，也是"观察期"开始的标志
  - `rollback-applied.json`：回滚发生后写下的"回滚记录"，下次启动软件会提示"已回滚到 X 版本"
  - `updater-events.jsonl`：更新过程的流水账日志

---

## 1. 验收前准备

### 1.1 机器与账号要求

| 项目 | Win10 | Win11 | macOS |
|------|-------|-------|-------|
| 系统版本 | Windows 10 22H2 (19045+) | Windows 11 23H2 (22631+) | macOS 13 / 14 / 15+ |
| 架构 | x64 | x64 | Apple Silicon (arm64) 或 Intel (x64) |
| 内存 / 磁盘 | ≥ 8GB / ≥ 5GB 可用 | 同左 | 同左 |
| 网络 | 能访问 `https://xiu-ci.com` | 同左 | 同左 |
| 权限 | 标准用户即可（装到本人目录） | 同左 | 标准用户即可 |
| 工具 | PowerShell 5.1+（系统自带） | 同左 | 终端（系统自带） |

### 1.2 需要提前知道的信息

1. **本次要验收的版本号**：从 `FHD/VERSION.md`（"XCAGI 稳定产品版本"一行）或 macOS 执行
   `FHD/scripts/package/acceptance-macos.sh`（不传 `--version` 会自动读取）获得。
2. **确认线上渠道已就绪**（验收组长做一次即可）：
   ```bash
   # "到货通知单"能打开（返回一串文字而不是 404）
   curl -sS https://xiu-ci.com/releases/stable/enterprise/latest-mac.yml
   curl -sS https://xiu-ci.com/releases/stable/enterprise/latest.yml
   # "货物清单"能打开
   curl -sS https://xiu-ci.com/xcagi-v<版本号>/manifest.json
   ```
   > 已知偏差处理：若 `xcagi-v<版本号>/manifest.json` 返回 404 但 latest*.yml 已是新版本，
   > 说明该版本 manifest 未发布（发布流程缺陷，需登记 issue）；此时 SHA256 校验改为
   > "记录实测值 + 与 latest*.yml 的 buildSha 核对版本身份"，并在证据中注明。
3. **确认机器上没有正在运行的旧 XCAGI**：冷启动要求"从零开始"，如果软件已经在跑，请先完全退出
   （macOS：右键 Dock 图标 → 退出；Windows：右下角托盘图标 → 退出）。
   **如果这是你自己的主力机器且正在使用 XCAGI，不要强行退出——改用"验收机/备用机"执行本协议。**

---

## 2. 步骤一：安装

目标：从正式渠道拿到安装包 → 确认"指纹"与官方清单一致 → 确认包是官方签名 → 完成安装 → 确认装上的版本正确。

### 2.1 操作步骤

**第 1 步 · 下载安装包**

- macOS：浏览器打开 `https://xiu-ci.com/xcagi-v<版本号>/enterprise/XCAGI-Enterprise-<版本号>-mac-<arm64|x64>.dmg`
  （Apple Silicon 机器选 arm64，Intel 机器选 x64；不确定就用脚本自动判断）。
- Windows：浏览器打开 `https://xiu-ci.com/xcagi-v<版本号>/enterprise/XCAGI-Enterprise-Setup-<版本号>-x64.exe`。
- 偷懒方式：直接运行引导脚本帮你下载（macOS：`FHD/scripts/package/acceptance-macos.sh`；
  Windows：`FHD/scripts/package/acceptance-windows.ps1`）。

**第 2 步 · 校验 SHA256 指纹**

打开终端 / PowerShell，执行（把 `<文件路径>` 换成实际下载位置）：

| 平台 | 命令 |
|------|------|
| macOS | `shasum -a 256 ~/Downloads/XCAGI-Enterprise-<版本号>-mac-arm64.dmg` |
| Windows | `Get-FileHash "C:\Users\你\Downloads\XCAGI-Enterprise-Setup-<版本号>-x64.exe" -Algorithm SHA256` |

把输出的指纹与 manifest.json 里对应条目的 `sha256` 逐字符比对（manifest 获取方式见 1.2 节；脚本会自动比对）。

**第 3 步 · 校验官方签名**

| 平台 | 命令 | 预期 |
|------|------|------|
| macOS（对 .app） | `codesign -dv --verbose=2 <拖入 XCAGI.app>`（看签名身份）<br>`codesign --verify --deep --strict <XCAGI.app> && echo 签名完整`<br>`spctl -a -vv -t execute <XCAGI.app>` | `Authority=Developer ID Application: ...`；`valid on disk`；`accepted` + `Notarized Developer ID` |
| Windows（对 .exe） | `Get-AuthenticodeSignature "C:\...\XCAGI-Enterprise-Setup-<版本号>-x64.exe" \| Format-List Status,StatusMessage,SignerCertificate` | `Status: Valid`，证书 Subject 为发布方，且有可信时间戳 |

> macOS 更简单的做法：挂载 dmg 后直接双击 .app，若系统不弹"无法验证开发者"即 Gatekeeper 放行。

**第 4 步 · 安装**

- macOS：双击 dmg → 把 XCAGI 拖入"应用程序"（或按引导脚本装到 `~/Applications/acceptance/`，避免影响已有安装）→ 安装完成后 `hdiutil detach <卷名>`（或 Finder 里点弹出按钮）弹出安装盘。
- Windows：双击 exe，按提示"下一步"完成安装；熟练者可用静默安装：
  `.\XCAGI-Enterprise-Setup-<版本号>-x64.exe /S /D=C:\XCAGI-acceptance`
  （`/S` 静默；`/D=` 自定义安装目录，必须放在最后且路径不含中文/空格——装到独立目录可避免影响现有安装）。

**第 5 步 · 确认安装版本**

| 平台 | 命令 | 预期 |
|------|------|------|
| macOS | `defaults read /Applications/XCAGI.app/Contents/Info.plist CFBundleShortVersionString`<br>`cat /Applications/XCAGI.app/Contents/Resources/build-info.json`<br>`cat /Applications/XCAGI.app/Contents/Resources/product-sku.json` | Info.plist 的 `CFBundleShortVersionString` 与验收目标对应（1.0.0.x 构建实测写入四段产品版本；最终判据以 build-info.json 的 `version` 为准）；build-info.json 的 `version` 为四段产品版本且与验收目标一致；`sku` 正确 |
| Windows | `(Get-Item "C:\安装目录\XCAGI.exe").VersionInfo.ProductVersion`<br>`Get-Content "C:\安装目录\resources\build-info.json"`<br>`Get-Content "C:\安装目录\resources\product-sku.json"` | ProductVersion 为四段产品版本；build-info.json 一致；sku 正确 |

Windows 安装结果还可从"开始菜单/桌面出现 XCAGI 图标"以及安装目录生成时间佐证；如需安装日志，
NSIS 静默安装可加 `/LOG=安装日志.txt` 参数留存。

### 2.2 通过判据

1. 下载完成的文件 SHA256 与 manifest.json 对应条目**完全一致**（manifest 缺失该条目时：记录实测值并注明"manifest 无该版本条目"，此项改判 PARTIAL 并登记发布流程 issue）；
2. 签名校验：macOS `spctl` 结果为 `accepted`（Developer ID + 公证）；Windows `Get-AuthenticodeSignature.Status = Valid` 且证书 Subject 符合发布配置；
3. 安装后 build-info.json 的 `version` 与验收目标版本一致、`gitSha` 与 manifest / latest*.yml 的 buildSha 一致；
4. 安装过程中系统无"病毒/无法验证"类拦截弹窗（SmartScreen / Gatekeeper）。

### 2.3 失败时的记录方式

- 在证据文件"安装"一节记录：实际得到的 SHA256、期望值、差异描述；
- 保存截图（拦截弹窗、报错提示）到证据目录 `assets/`；
- 指纹不一致 = **P0 阻断**（制品可能被篡改），停止后续步骤并上报；
- 其余失败项标 FAIL + 原因，能继续的步骤继续（不要因为一个失败丢弃整轮证据）。

---

## 3. 步骤二：冷启动

目标：装好后第一次启动 → 记录从双击到主窗口出现的秒数 → 确认本地后端健康 → 截图留证。

### 3.1 操作步骤

1. 确认没有其他 XCAGI 实例在运行（见 1.2 节第 3 条）。
2. 启动软件并掐表（手机秒表即可）：
   - macOS：双击 XCAGI.app（或在终端 `open -n ~/Applications/acceptance/XCAGI.app`）；
   - Windows：双击桌面/开始菜单 XCAGI 图标。
3. 等主窗口完整出现（能看到侧栏/界面内容，不是白屏），记录秒数。
4. 健康检查：

| 平台 | 命令 | 预期 |
|------|------|------|
| macOS | `curl -sS http://127.0.0.1:17500/api/health` | 返回 JSON，`status=healthy`，`version` 为当前产品版本 |
| Windows | `Invoke-RestMethod http://127.0.0.1:17500/api/health` | 同上 |

5. 端口监听佐证：macOS `lsof -nP -iTCP:17500 -sTCP:LISTEN`（进程名 `xcagi-bac...`）；Windows `Get-NetTCPConnection -LocalPort 17500 -State Listen`。
6. 截图主窗口：
   - macOS：`screencapture -x /tmp/xcagi-acceptance-main.png`（或 Cmd+Shift+4）；
   - Windows：`PrtSc` 或截图工具，保存到证据目录。
7. （引导脚本可代劳以上计时、健康检查与截图，并输出耗时数值。）

### 3.2 通过判据

1. 主窗口在 **60 秒内**出现且内容完整（无白屏/无限转圈）；
2. `/api/health` 返回 200 且 `status=healthy`；
3. 17500 端口被本安装实例的后端进程监听；
4. 截图已归档且能看清主界面。

### 3.3 失败时的记录方式

- 记录实际耗时（或"120 秒未出现"）、health 命令的完整输出、截图；
- 白屏/崩溃时同时保留日志：macOS `~/Library/Logs/XCAGI/main.log` 与 `~/Library/Application Support/XCAGI/logs/`；Windows `%APPDATA%\XCAGI\logs\main.log`；
- 无法冷启动 = **P0 阻断**，OTA/回滚步骤可顺延但必须登记。

---

## 4. 步骤三：OTA（在线自动更新）

目标：从当前稳定版通过**真实更新通道**升级到新版本，记录升级前后版本号与更新源。软件内置的更新器（electron-updater）会自己读 latest.yml / latest-mac.yml，先验 Ed25519 防伪签名再下载，所以**只需要在软件里点"检查更新"**。

### 4.1 操作步骤

1. **确认更新源已就绪且确实有新版本**（没有新版本时本步只能做"通道可达性"验收，见 4.4）：
   - Windows 通知单：`curl -sS https://xiu-ci.com/releases/stable/enterprise/latest.yml`（PowerShell：`Invoke-RestMethod` 同地址）
   - macOS 通知单：`curl -sS https://xiu-ci.com/releases/stable/enterprise/latest-mac.yml`
   - 记录其中的 `productVersion`（升级目标）与当前已装版本（升级前版本）。
2. 在软件菜单中点 **"检查更新"**（设置 → 关于/更新）。
3. 等待提示"发现新版本 → 自动下载完成 → 立即重启安装"，点击确认。
4. 软件自动退出并安装新版本 → 自动重新启动。
5. **观察期（软件自动完成，你只需要等待并观察）**：
   - 重启后的第一次启动，软件检测到 `rollback-marker.json`（升级记录）即进入观察期；
   - 判定"升级成功"的条件：本地后端健康检查通过 + 业务路由就绪 + 主窗口加载成功 + **5 秒稳定性窗口**内不崩溃；
   - 全部通过后软件自动删除 marker（升级正式生效）；期间窗口若提示"正在检查更新结果/正在提交更新"属正常现象，请勿强制退出。
6. 复核升级结果：

| 平台 | 命令 | 预期 |
|------|------|------|
| macOS | `cat "/Applications/XCAGI.app/Contents/Resources/build-info.json"`<br>`cat ~/Library/Application\ Support/XCAGI/rollback-marker.json 2>/dev/null \|\| echo marker已提交`<br>`curl -sS http://127.0.0.1:17500/api/health` | `version` = 新版本；marker 已删除；health healthy |
| Windows | `Get-Content "C:\安装目录\resources\build-info.json"`<br>`Get-Content "$env:APPDATA\XCAGI\rollback-marker.json" -ErrorAction SilentlyContinue`<br>`Invoke-RestMethod http://127.0.0.1:17500/api/health` | 同上 |

7. 记录更新流水账（可选但推荐）：打开 userData 目录下的 `updater-events.jsonl`，把最后几行复制进证据文件——里面有"检查 → 下载 → 安装"的完整事件与时间戳。

### 4.2 通过判据

1. 更新前版本号、更新后版本号均有记录且更新后与 latest*.yml 的 `productVersion` 一致；
2. 更新源 URL 已记录（latest.yml / latest-mac.yml 的完整地址）；
3. 更新过程中**未出现签名校验失败提示**（说明 Ed25519 验签通过）；
4. 观察期顺利度过（marker 被自动删除、health healthy），未触发回滚。

### 4.3 失败时的记录方式

- 记录卡住的阶段（检查/下载/安装/观察期）与提示原文截图；
- 附上 `updater-events.jsonl` 最后 20 行与 `main.log` 尾部；
- OTA 失败但自动回滚成功 = 记 FAIL（更新能力）+ PASS（回滚兜底有效），两处分开写。

### 4.4 没有新版本可升怎么办（如实标注）

当前已是线上最新版本时，无法完成"升级"动作。此时本步记录为：
`SKIP（当前版本 X 已是 latest*.yml 最新版本 productVersion=Y，无升级目标）`，并至少完成：
- 更新通道可达性检查（latest*.yml 能打开、`signature: ed25519:` 字段存在）；
- 引用最近一次 OTA 闭环证据（如 `FHD/docs/evidence/e2e/desktop-ota-closed-loop-20260724/`）。

---

## 5. 步骤四：回滚

目标：验证"更新把软件搞坏时能自动退回旧版本"。回滚有两条路径，至少验证其一：

- **路径 A（观察期自动回滚，首选）**：更新后首次启动失败（后端起不来/主窗口崩溃），软件在观察期内自动从备份还原旧版本并写 `rollback-applied.json`；
- **路径 B（降级安装）**：用上一版本的 dmg/exe 手动重装覆盖（软件会保留 userData 数据）。

### 5.1 路径 A 操作步骤（需要构造"坏更新"，建议由验收组长在专用验收机上做）

1. 确认当前版本为旧版（记下版本号 V0）；
2. 让更新通道短暂指向一个"坏包"（由组长在测试更新站准备同版本号但后端损坏的包），在软件里检查更新并安装；
3. 软件重启后进入观察期 → 预期软件自己发现启动异常 → 界面提示"已回滚到 V0"（或自动重启后恢复正常）；
4. 核对回滚证据：

| 平台 | 命令 | 预期 |
|------|------|------|
| macOS | `cat ~/Library/Application\ Support/XCAGI/rollback-applied.json`<br>`cat ~/Library/Application\ Support/XCAGI/rollback-marker.json 2>/dev/null \|\| echo marker已清理`<br>`defaults read /Applications/XCAGI.app/Contents/Info.plist CFBundleShortVersionString`<br>`curl -sS http://127.0.0.1:17500/api/health` | applied 记录含 `reason / fromVersion / toVersion`；marker 已清理；版本回到 V0；health healthy |
| Windows | `Get-Content "$env:APPDATA\XCAGI\rollback-applied.json"`<br>（marker 同理）<br>`(Get-Item "C:\安装目录\XCAGI.exe").VersionInfo.ProductVersion`<br>`Invoke-RestMethod http://127.0.0.1:17500/api/health` | 同上 |

5. 提示弹窗/横幅截图留证。

> **不想构造坏更新时的替代做法（如实标注）**：引用桌面端自动化证据
> `FHD/desktop/rollback.test.ts`（回滚单测）与 `FHD/desktop/e2e/update-rollback.e2e.spec.ts`
> （真实链路：预置 marker → 观察期 → commitRollback/triggerRollback），本步标
> `PARTIAL（真实机未注入坏更新，回滚机制以自动化 E2E + 代码评审佐证）`。

### 5.2 路径 B 操作步骤（降级安装）

1. 从更新站历史目录取上一版本安装包（如 `https://xiu-ci.com/xcagi-v<旧版本>/enterprise/`）；
2. 重复步骤一（SHA256 + 签名校验）后覆盖安装；
3. 启动后确认版本回到旧版本、health healthy、历史业务数据仍在（登录后看一眼既有订单/对话）。

### 5.3 通过判据

1. 回滚后版本号 = 回滚前版本号（V0），有 applied 记录或降级安装凭证；
2. 回滚后 `/api/health` 为 healthy；
3. 用户数据未丢失（可登录、可见历史数据）。

### 5.4 失败时的记录方式

- 记录回滚前/后版本、applied 文件内容（或"无 applied 文件"）、health 输出、界面提示截图；
- 回滚失败且软件不可用 = **P0 阻断**（比 OTA 失败更严重：连兜底都没有），立即上报并冻结该版本发布。

---

## 6. 结果判定与归档

### 6.1 每步结果只能取以下之一

| 标记 | 含义 |
|------|------|
| PASS | 完整执行且通过判据全部满足 |
| FAIL | 执行了但判据未满足（附证据与原因） |
| PARTIAL | 部分执行/以替代证据佐证（附替代证据说明） |
| SKIP | 未执行（必须写明原因，如"无升级目标""无独立 Win10 机"） |

### 6.2 验收结论规则

- **签字发布**：三台机器（Win10 / Win11 / macOS）安装+冷启动均 PASS，OTA 与回滚合计无 FAIL（PARTIAL/SKIP 需附替代证据）；
- **任一平台存在 FAIL 或 P0**：该版本桌面验收未闭环，不得对外宣称"三平台可用"；
- 证据文件命名：`FHD/docs/evidence/e2e/desktop-real-machine-acceptance-<版本号>-<win10|win11|macos>.md`，
  按模板填写，截图放同目录 `assets/` 子目录并在文中引用相对路径。

### 6.3 引导脚本速查

| 平台 | 脚本 | 一句话用法 |
|------|------|-----------|
| macOS | `FHD/scripts/package/acceptance-macos.sh` | `bash FHD/scripts/package/acceptance-macos.sh --version 1.0.0.1`（自动下载/验签/挂载/签名校验/装到 ~/Applications/acceptance/，`--skip-launch` 跳过真实启动） |
| Windows | `FHD/scripts/package/acceptance-windows.ps1` | `powershell -ExecutionPolicy Bypass -File acceptance-windows.ps1 -Version 1.0.0.1`（逐步引导，每步人工确认 [Y/N]） |

脚本只做"下载、校验、安装位、计时、截图、读版本"，**OTA 与回滚两步永远输出人工操作指引**（涉及真实更新源与破坏性场景，不允许脚本静默执行）。

---

*协议版本：v1（2026-09-01，随 converge-desktop-acceptance-tech-debt D1-2/D1-3 建立）*
