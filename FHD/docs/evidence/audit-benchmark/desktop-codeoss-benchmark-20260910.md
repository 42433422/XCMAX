# R22 外部标杆实测：桌面壳与更新恢复域开源锚点（Code - OSS / VSCodium）同任务集实测记录

> 标准版本：`external-anchors-v1`（`FHD/config/audit_benchmark_ssot.json`）。
> 本文是**单域单锚点的实测审计记录**，不是 18 域正式评分。

## 审计记录字段

| 字段 | 值 |
|---|---|
| standard_version | 1.0.0 |
| scoring_version | external-anchors-v1 |
| reference_versions_editions_regions | Code - OSS（`microsoft/vscode`，MIT，标准源锁定 source_commit=`4603a7f7b910`，main，核对日 2026-09-08）经 **VSCodium** 免遥测再发行构建实测：旧版 `1.126.04524`（vscode `4c0b0c6cc561`，2026-06-23）→ 新版 `1.135.06055`（vscode `1a46a584725d`，2026-08-25）；产物为 `VSCodium-darwin-arm64-*.zip`，本地 macOS arm64 解压安装。**版本偏差登记**：标准源锁定的 `4603a7f7b910` 是 2026-09-08 的 main SHA（文档核对快照，非稳定发行），实测按标准「正式实测选择受支持稳定版本并将确切 tag/SHA 写入审计记录」改用 VSCodium 官方稳定 tag，build 内嵌 vscode SHA 已记录；MIT 边界仅覆盖开源核心，Microsoft 专有发行与市场服务不纳入 |
| dataset_hash | 任务脚本随本文档存档（desktop-codeoss-tasks-20260910.py）；制品 SHA256：`vscodium-1126.zip`=c76a8e28b1e3c1403e0274c8bd9966d2033a83a59ab5fc42c394c8ed347d754b，`vscodium-1135.zip`=61ff9ebc3ac5563c63a0a9e1b479822647e7f2c3303b0629f15fefe9e291f7cc |
| task_protocol | B1 解压安装/真实启动/跨版本升级/重复安装/卸载可重复；B2 进程树（扩展宿主独立子进程）、IPC socket 归属、凭据落盘、多 user-data 目录隔离、退出回收；B3 更新制品损坏可检测且被 Gatekeeper 拒绝、失败后用户数据完整、回退旧版可用、重装修复、原数据直接复用 |
| predeclared_metrics_and_tolerances | CLI `--version` 返回版本三元组（精确）；运行实例 `--status` 输出含 `Version:`（精确）；升级前后版本号不同（精确）；升级后以原 user-data-dir 启动且新版本号出现在 status（精确）；`settings.json` 标记升级后仍为 `keepme`（精确）；二次解压版本字符串一致（精确）；`/Applications` 无 `VSCodium*` 残留（精确）；子进程数 ≥2 且存在扩展宿主/插件宿主进程（精确）；IPC `*.sock` 位于 user-data-dir 内（精确）；user-data 内无明文 `password` 落盘（排除 keybindings/settings.json，精确）；主进程退出后其子进程数=0（精确）；篡改制品 `codesign --verify --strict` 失败且 `spctl --assess --type execute` 拒绝（精确） |
| environment | 本机 macOS 15（Darwin arm64 25.3.0，Apple M4），VSCodium 免安装解压至 `/tmp/r22-desktop/install/`，全部 HTTP 环境变量已清空 + `no_proxy=*` |
| observed_results | B1 8/8、B2 5/5、B3 5/5 共 **18/18 PASS**（见下表）；末次运行 `results.json` 全 true |
| unknowns | 真实「应用内更新」通道未覆盖——Code - OSS 免遥测构建默认不自带自动更新服务端，本记录以制品替换 + 同一 user-data-dir 复用的等价路径验证升级与回退；Windows/macOS 管理部署（MSI/PKG、批量更新、诊断上报）与旧数据迁移属商业 90 分锚点（teams/slack/idea），本地不可得，未实测；代码签名证书链的真实公证（notarization）流程未覆盖——B3 只验证「篡改即被拒」的可检测性 |
| domain_status | desktop 域开源 60 分锚点：B1/B2/B3 实测通过（E3：真实 macOS 上完整安装→运行→升级→损坏→回退→重装链路） |
| score | 不授予（单锚点记录） |
| auditor | agent-mac-trae |
| observed_at | 2026-09-10（Asia/Shanghai） |

## 逐任务结果

| 任务 | 对应锚点 | 结果 | 关键证据 |
|---|---|---|---|
| B1-1 解压安装后 CLI 可报告版本 | desktop-B1 | PASS | `codium --version` → `1.126.04524 / 4c0b0c6cc561 / arm64` |
| B1-2 真实启动可完成并输出运行状态 | desktop-B1 | PASS | 实例运行中 `codium --status` → `Version: VSCodium 1.126.04524`, `OS Version: Darwin arm64 25.3.0`, `CPUs: Apple M4 (10 x 2400)` |
| B1-3 首次启动创建独立用户数据目录 | desktop-B1 | PASS | `userdata-v1/` 生成 `Backups/Cache/CachedData/Code Cache/Local State/Preferences…` 等 8+ 项 |
| B1-4 升级目标版本与旧版本不同 | desktop-B1 | PASS | `1.126.04524` → `1.135.06055`（构建内嵌 vscode SHA `4c0b0c6c…` → `1a46a584…`） |
| B1-5 升级后新版本以原用户数据启动成功 | desktop-B1 | PASS | 新版二进制 + 旧 `userdata-shared/` 启动，status 报 `1.135.06055`，无数据目录重建/崩溃 |
| B1-6 升级保留用户设置 | desktop-B1 | PASS | 升级前写入的 `{"r22.marker":"keepme"}` 升级后原样可读 |
| B1-7 安装可重复（二次解压版本一致） | desktop-B1 | PASS | 同一 zip 二次解压独立目录，`--version` 与首次一致 `1.126.04524` |
| B1-8 卸载=删除应用目录且无系统级残留 | desktop-B1 | PASS | 删除 app 目录后 `find /Applications -maxdepth 1 -name 'VSCodium*'` 为空 |
| B2-1 扩展宿主为独立子进程（进程边界） | desktop-B2 | PASS | 主进程直接子进程 6 个；`VSCodium Helper (Plugin)`=1、`node.mojom.NodeService` 工具进程=3 |
| B2-2 IPC socket 位于用户数据目录内（边界受控） | desktop-B2 | PASS | 单实例 socket `/tmp/r22-desktop/userdata-shared/1.13-main.sock`，落在 user-data-dir 内 |
| B2-3 用户数据目录无明文凭据落盘 | desktop-B2 | PASS | `grep -rIl -i password userdata-shared/` 命中集排除 keybindings/settings.json 后为空 |
| B2-4 多用户数据目录相互隔离 | desktop-B2 | PASS | `userdata-v1/User/globalStorage` 与 `userdata-shared/User/globalStorage` 并存且互不可见 |
| B2-5 主进程退出后子进程回收 | desktop-B2 | PASS | SIGTERM 后 `pgrep -P <pid>` 输出为空 |
| B3-1 损坏的升级制品可检测且被 Gatekeeper 拒绝 | desktop-B3 | PASS | 制品主二进制追加 8KiB 破坏后：`codesign --verify --strict` → `main executable failed strict validation`；`spctl --assess --type execute` → `rejected` |
| B3-2 更新失败后用户数据完整 | desktop-B3 | PASS | 损坏检测期间 `settings.json` 标记仍为 `keepme`，未被回滚/清空 |
| B3-3 回退旧版本仍可启动（恢复入口） | desktop-B3 | PASS | 升级前制品 `install/v1` 未被改动，`--version` 仍报 `1.126.04524` |
| B3-4 重新安装修复且版本一致 | desktop-B3 | PASS | 隔离损坏副本后由同一 zip 重装，`--version` 恢复 `1.135.06055` |
| B3-5 修复安装后原用户数据直接复用 | desktop-B3 | PASS | 重装实例直接挂原 `userdata-shared/` 启动，status 正常返回，无需迁移步骤 |

## 误判更正（重要）

2026-09-10 本项目早前两次运行记录为 4 项 FAIL，本次证明均为**测试脚本缺陷**而非被测产品缺陷，逐条更正：

1. **`--status` 误用**：原脚本在「期望启动后自行退出并打印状态」的假设下调用 `--status`，真实语义是
   `codium --status` 需**目标实例已在运行**（经 IPC 读取），否则返回
   `Warning: The --status argument can only be used if VSCodium is already running.`。
   更正为：先 `Popen` 后台起 GUI 实例，再调 `--status`。B1-2/B1-5/B3-5 由此转 PASS。
2. **扩展宿主进程名假设错误**：原判据 grep `--extensionHost`，实际该构建的扩展宿主表现为
   `VSCodium Helper (Plugin)` 与 `node.mojom.NodeService` 工具进程（`--extensionHost` 不出现于命令行）。
   更正为按 Plugin helper / NodeService / extensionHost 三者任一存在判定，B2-1 转 PASS。
3. **macOS 禁止 rename 已签名主二进制**：原 B3 用 `os.rename` 移动 `Contents/MacOS/VSCodium` 制造
   「制品缺失」，被系统拒绝（`Operation not permitted`，即使进程已全部退出、`xattr` 清理后仍拒绝）。
   更正为**复制副本 + 追加字节破坏签名**模拟不完整制品，并用 Gatekeeper 级校验取证。
4. **篡改后直接 exec 不构成有效判据**：Mach-O 尾部追加数据后进程仍可被 exec 返回 0（无 GUI 会话时），
   因此「启动被拒」不能作为唯一判据。更正为以 `codesign --verify --strict` + `spctl --assess` 的
   权威拒绝结论为准，B3-1 转 PASS。

以上四条对外结论无影响：产品侧安装/启动/升级/回退/修复链路本身第一次即通过，问题在测试脚本。

## 部署要点（复跑必读）

1. `ditto -x -k <zip> <dir>` 解压得到 `VSCodium.app`；CLI 为 `Contents/Resources/app/bin/codium`，
   主二进制为 `Contents/MacOS/VSCodium`（**不是** `Electron`）。
2. 多实例并存必须显式传 `--user-data-dir` 与 `--extensions-dir`，否则第二个实例会因单实例锁并入首个实例，
   导致升级/隔离用例失效。
3. `--status` 只对运行中的实例有效；判定「启动成功」应先用 `Popen` 起实例再查询。
4. 不得对已签名 app 内的主二进制做 `rename/mv`；模拟损坏请复制后追加字节，并以 `codesign`/`spctl` 取证。

## 与 XCMAX 侧对照

XCMAX 同域验收见 R03/R14（桌面制品 manifest、构建身份与升级链核对）与 R07
（桌面测试共享临时目录隔离修复，`updater-install` 唯一目录）。XCMAX 桌面更新失败恢复路径的
「保留用户数据 + 可操作恢复入口」语义与本锚点 B3 同构；本记录不改变 XCMAX 侧的既有验收结论。
