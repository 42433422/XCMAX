# Windows 侧真机验收交接（能力中心「按平台分别验证」框架，2026-09-22）

> 交接对象：Windows 侧 AI / 执行人。
> 背景：能力中心过去把「单个平台有证据」当成整项能力通过——只有 macOS 证据就能标「已验证」。
> 这不符合「Windows 与 macOS 分别验证」的标准，已改为**逐平台独立判定**。

## 1. 本轮要求（原文）

> 把每项能力固定列出适用平台，每个平台有独立状态和证据，总体状态由平台自动汇总，不能手动标绿。
> 即使暂时没有 Windows 证据，也必须显示 Windows 待验证，不能直接消失。
> 改完框架，再让 Windows AI 按同一结构补真机验收。

## 2. 框架规则（已生效，构建脚本强制）

- 适用平台清单在 `成都修茈科技有限公司/data/capabilities/catalog.json` 的 `platforms` 字段声明，**固定展示**。
- 平台状态只有三档，且**只由该平台的实机验收记录产生**：
  - `已验证`：该平台至少一条实机验收记录，且本项全部用例通过；
  - `部分验证`：该平台有验收记录，但存在失败或未覆盖项；
  - `待验证`：该平台尚无验收记录。**代码已合入、单测与 CI 通过都不算**，仍显示「待验证」。
- 总体状态由平台状态自动汇总，规则固定：
  - 全部适用平台都 `已验证` → `已验证`；
  - 至少一个平台有验收记录但未全部通过 → `部分验证`；
  - 所有适用平台都 `待验证` → `已实现待验证`（仅表示代码已合入）；
  - 无实现 → `规划中`。
- 目录里**不允许再出现 `status` 字段**：构建脚本遇到即报错退出（防止手写绿灯）。

## 3. Windows 侧要产出的结构（与 macOS 同一结构）

每条功能一份验收记录 `FHD/docs/evidence/e2e/<轮次>/<feature>/<feature>-windows-run.json`：

```json
{
  "kind": "feature-acceptance",
  "feature": "<catalog id>",
  "platform": "windows",            // 必需；缺这一项不会计入任何平台状态
  "status": "passed",               // passed | failed
  "app_git_sha": "<40 位 hex>",
  "app_version": "1.0.0.5",
  "verified_at": "YYYY-MM-DD",
  "reviewed_at": "YYYY-MM-DD",
  "passed": 6, "failed": 0,
  "cases": [
    {"input": "...", "actions": "...", "expected": "...", "observed": "...", "result": "passed"}
  ],
  "media": [
    {"feature": "<id>", "path": "<仓库相对路径>", "sha256": "<文件字节 sha256>",
     "visual_review": "accepted", "visible_result": "<这张图/这段录像里能看到什么>",
     "reviewed_at": "YYYY-MM-DD"}
  ]
}
```

本轮已随交接提供脚本，**它直接产出上面这份记录，不要手工拼 JSON**：
`FHD/docs/evidence/e2e/feature-acceptance-20260922/base-login/windows/accept-base-login.ps1`
（用法见同目录 `base-login/windows/HANDOFF.md`）。脚本把机器字段全部填好，只把
`media[]` 的三项复核字段留空（`visual_review: "pending_review"`）——**必须真的打开每张截图、
看完每段录像后再填**，这是唯一允许手填的部分；未复核的媒体会被构建脚本拒绝，平台不会变绿。

硬性约束（构建脚本逐条校验，不满足即不计入该平台）：

- `platform` 必须是该功能 `platforms` 里声明过的值；
- `cases` 每条都要有 `input/actions/expected/observed/result` 四要素加判定；
- `media` 每条的 `sha256` 必须与磁盘文件**逐字节一致**，且 `path` 必须同时列在该功能的
  `evidence.screenshots` 或 `evidence.videos` 里；
- 六项证据缺一不可：截图、录像、日志、产品版本、应用 SHA、验证时间。日志放
  `evidence.logs`，原始抓取放 `evidence.raw`，并在 `evidence.platform_assets.windows`
  下点名，才算绑到 Windows 平台。

## 4. 回传后要在目录里接上

1. 把记录路径写进该功能 `evidence.runs`；
2. 把截图/录像路径写进 `evidence.screenshots` / `evidence.videos`；
3. 日志与原始抓取写进 `evidence.logs` / `evidence.raw`，并在 `evidence.platform_assets.windows` 下点名；
4. 在 `成都修茈科技有限公司/` 下运行 `python3 scripts/build_capability_center.py`，确认 Windows 平台状态从
   「待验证」变为实际结论、且总体状态按规则自动变化；
5. 运行 `python3 scripts/build_capability_center.py --check` 与
   （在 `FHD/` 下）`python3 scripts/dev/check_net_deletion.py`。

## 5. 边界

- **不得用 macOS 证据替代 Windows 证据**，也不得用「代码存在、CI PASS、health=200」替代实机验收。
- 失败也要如实回传：`status: "failed"` 会让该平台显示「部分验证」，这是允许且应当保留的结论；
  写明第一个真实断点，保留现场、日志与原始 JSON。
- 每个平台独立判定，互不抵扣：某平台通过不会让另一个平台变绿。

## 6. 本轮建议顺序

1. 先补 `base-login`「登录与会话管理」的 Windows 实机验收（交接细节见同目录
   `base-login/windows/HANDOFF.md`，本文件只定义结构）；
2. 再按 catalog 里 `platforms` 含 `windows` 的能力逐项推进，每项独立一轮；
3. 每项回传后由 Mac 侧合并并复跑构建门禁。