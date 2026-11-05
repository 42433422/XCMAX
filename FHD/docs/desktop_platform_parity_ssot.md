# 桌面双端平级 SSOT(Windows / macOS)

> **本文档是桌面端 Windows 与 macOS 平级发布、双端完成定义、平台差异架构收口的唯一真相源。**
> 生效日期:2026-09-09。任何流程、流水线、验收模板与本文件冲突时,以本文件为准。

## 规则一:Windows 与 macOS 平级发布

1. Windows 与 macOS 是**平级发布通道**:同一版本号、同一 `release_sha`(40 位源码 SHA)、同一发布窗口出包。
2. 发布以「双端制品齐备」为完成条件:任一平台的构建、签名/公证、安装验证失败,即**整体发布失败**,禁止单平台先行发布、另一平台后补。
3. 发布流水线锚点:`FHD/.github/workflows/release-desktop.yml` 必须同时包含 `windows-latest` 与 `macos-latest` 构建 job,由同一 `release_sha` 驱动。
4. 版本冻结、update feed、manifest 对双端同时生效;禁止出现「Mac 已发、Windows 还在追」的版本错位状态。

## 规则二:双端验证通过才算完成

1. 所有桌面端功能(含宿主能力、更新/回滚、安装器、托盘、窗口行为)必须在 **Windows 与 macOS 双端验证通过**,才允许标记为完成;单端通过 = 未完成。
2. 验收证据双端齐全:验收文档(`docs/evidence/e2e/`)中同一功能须有 Windows 与 macOS 两份记录,缺一即视为未验收。
3. PR 合并前,涉及桌面端行为的改动需声明双端验证结果;无法在本机验证的平台,走 CI 双端 job 或真机验收流程补证。

## 规则三:平台差异收口到适配层

1. 平台相关代码统一收口到 **`FHD/desktop/platform/` 适配层**:
   - `platform/index.ts`:按 `process.platform` 选择实现的唯一入口(工厂);
   - `platform/darwin.ts`:macOS 实现;`platform/win32.ts`:Windows 实现;
   - 能力接口(更新安装、回滚、窗口/托盘、路径、签名)在适配层定义,双端各提供实现。
2. 适配层以外的业务模块**禁止直接出现** `process.platform`、`isWindows`、`isMac`、`darwin`、`win32` 分支判断;新增平台差异必须先扩展适配层接口。
3. 现存散落在业务模块中的平台判断(`updater.ts`、`rollback-windows.ts`、`desktop-install-update.ts` 等约 20 处)按「先收口、后删除分支」逐步回迁到适配层;**不再允许 Windows 实现追着 Mac 实现打补丁**,双端实现同层并列、同步演进。
4. 新功能评审时,若改动触及平台行为,必须同时给出 `darwin.ts` 与 `win32.ts` 两侧实现(或显式标注为共享实现),否则不予通过。

## 派生锚点

| 锚点 | 路径 | 校验 |
|------|------|------|
| 双端发布流水线 | `FHD/.github/workflows/release-desktop.yml` | 含 `windows-latest` 与 `macos-latest` runner |
| 平台适配层 | `FHD/desktop/platform/` | 规则三目标位置（收口进行中；目录创建后须补登 ssot.yaml `derived`） |

## 治理

- 本域在 `FHD/config/ssot.yaml` 注册为 `desktop-platform-parity`,lint 模式,CI 阻断。
- 校验命令:`python scripts/dev/ssot_cli.py check desktop-platform-parity`。
- 修改本文件三条例规需同步更新 check 插件 `scripts/dev/ssot_plugins/desktop_platform_parity.py` 的必需片段。
