# 最终发布审计总表（staging，主干 HEAD 收口审计）

审计对象：main HEAD 280225ac77ce0b5f66470d2d7a11ad2844cdad67（含 #1935/#1923/#1920/#1938 全部收口）
审计时间：2026-09-15（进行中）
判定规则：无证据 = UNKNOWN；不强行绿灯。

## A. 关键 PR 清理

| PR | 内容 | 状态 | 证据 |
|---|---|---|---|
| #1935 | 1.0.0.3 Release Ready 回填 | ✅ MERGED（3d872b32e 前） | git log / PR merged |
| #1923 | Windows 故障注入 CI 场景 | ✅ MERGED（c05a005ae，rebase 后） | PR merged |
| #1920 | 发货单流程修复+升版 1.0.0.4 | ✅ MERGED（3d872b32e squash） | PR merged |
| #1938 | 故障注入误报修复（场景隔离） | ✅ MERGED（280225ac7，backend-test success） | PR merged |
| #1937/#1939 | 旧 metrics 快照/被覆盖 PR | ✅ CLOSED（#1937 内容折入 #1938） | PR closed |

回滚检查：G9 isQuitting 修复在 main HEAD 保留（desktop-install-update.ts 预置逻辑在位）；1.0.0.4 升版内容与 main 一致。✅

## B. Mac 方向（1.0.0.4）

| 项 | 状态 | 证据 |
|---|---|---|
| 代码进 main | ✅ | 280225ac7 |
| 扫描对 ×2 零漏洞 | ✅ | run 34851505749 + 34855340685，同 SHA，间隔 35min44s |
| OTA 产物上线 | ✅ | 公网四路复验 + 7 文件 SHA256 全匹配 + manifest/feed 锚定 |
| G8 更新发现 | ✅ | updater-events + UI 截图，productVersion/buildSha 锚定 |
| G8.5 下载完整性 | ✅ | blockmap 增量 + 下载包 SHA256 与发布产物一致 |
| G9 安装 | ⏳ 进行中 | install_start 已记录；ShipIt 特权授权等待用户输入（root:wheel 环境阻塞，非产品缺陷） |
| G9 自动退出（isQuitting 修复） | ⚠️ 结构性无法本轮验证 | 触发方 1.0.0.3 不含修复；归 1.0.0.4→1.0.0.5 |
| G10 数据保持 | ⏳ 待 1.0.0.4 启动 | t5 脚本就绪（pre digest 已记录） |
| G11 业务复测 | ⏳ 待 1.0.0.4 启动 | g7_business_retest.py 就绪 |
| G12 重启复验 | ⏳ 待 G11 后 | t6-post-reboot-verify.sh 就绪 |
| Mod/AI 员工加载 | ⏳ 待 1.0.0.4 启动 | 1.0.0.3 证据 GREEN（62 mods），1.0.0.4 待复测 |

## C. Windows 方向

| 项 | 状态 | 证据 |
|---|---|---|
| 双进程/迁移互斥 | ✅ CI runner 真实证据 | run 34841838624（3484 场景隔离判据下双 PASS）+ 34851567425（#1938 修复后脚本回归双 PASS） |
| disk-full/power-cut | ⚠️ 等真实机器 | CI 无法执行实体机场景，标记 SKIP 而非伪造（两份 receipt 一致） |
| #1938 判定修复验证 | ✅ | run 34851567425 在修复后脚本上隔离场景 PASS |

## D. #1841 弱网 OTA

| 项 | 状态 | 证据 |
|---|---|---|
| 根因 | ✅ 成文 | ISP 中间设备 QoS 会话重置（非客户端/服务端缺陷）；blockmap 放大因子已修 |
| 落地缓解 | ✅ | 增量更新（本轮实跑 blockmap 生效）、直连绕代理、8443 通道 |
| 产品化后续 | ✅ 回填 issue | 多源 fallback + 断点续传规划在案 |

## E. 版本口径

| 项 | 状态 | 证据 |
|---|---|---|
| health + git sha 口径 | ✅ 定稿 | Runbook 第 0 条已写入双平台 `SSOT` |
| 已知显示差异 | ✅ 记录 | npm/Electron/Dart `1.0.0` 工具链映射；mobile `(12)` vs versionCode=10（待下版同步）；feed `version: 1.0.0` vs productVersion（electron-updater 标准行为） |

## F. 交付结论（闭环完成后定稿）

- 待 G9-G12 完成：按 Gate 证据给「能交付 / 不能交付」结论
- 当前阻塞：ShipIt 特权授权等待用户输入（物理依赖）
