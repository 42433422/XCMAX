# v10-C 移动 AI 协同 App · 真机验收终稿（2026-07-11）

> **状态：真机技术签字通过（PL3）**  
> **版本锚点**：10.0.0（v10 锁，未 bump）  
> **设备**：小米 `25113PN0EC`（serial `6e8d9335`，Android 16）USB adb  
> **包**：`com.xiuci.xcagi.mobile.enterprise` · `versionName=10.0.0` · `versionCode=1783758395`  
> **证据目录**：`FHD/docs/evidence/e2e/v10-c-phone-20260711/`  
> **对照**：`specs/tasks.md` PL3 · `specs/product-lines-3-plus-2.md` §v10-C

---

## 验收矩阵

| # | 边界 | 结果 | 证据 |
|---|------|------|------|
| C1 | 已安装企业包 + 启动 | **PASS** | 机上已装；`01-launch.png` / `01-messages.png` |
| C2 | 登录态可用 | **PASS** | UI 显示 `admin` ·「账号 · 56位AI员工」 |
| C3 | 四 Tab（消息 / AI员工 / 探索 / 我） | **PASS** | `01`–`04` 截图 + UI dump |
| C4 | 探索工具 / 扫码入口 | **PASS** | `03-me` 扫码绑定；`09-explore-tools` 含扫码/OCR/通知；`06`/`11` 扫码页截图 |
| C5 | 审批入口可打开 | **PASS** | 探索下滑 →「审批中心」→ `10-approvals.png`（标题/返回/刷新；WebView 列表区） |
| C6 | 5G / 蜂窝可用 | **PASS** | `MOBILE[NR]` CONNECTED（cmnet + ims）且 `NR_SA`；同时 Wi‑Fi `大帅B-5G` |
| C7 | 非 debug 签名包 | **PASS** | `apksigner verify`：v2；`CN=XCAGI, O=成都修茈科技有限公司`（非 `Android Debug`） |

## 环境与网络

| 项 | 值 |
|----|----|
| USB adb | `6e8d9335 device` product=`pudding` model=`25113PN0EC` |
| Wi‑Fi | `大帅B-5G` · `192.168.10.11` · 已校验 |
| 蜂窝 | 中国移动 · `NR_SA` · `MOBILE[NR] CONNECTED` |
| 本机 Flutter SDK | 无（未在本机构建；使用机上已装更高 versionCode 包） |
| 本机 `app-release.apk` | versionCode `1783756134`（低于机上，adb install 被 VERSION_DOWNGRADE 拒绝） |

## 签名核验（摘录）

```text
Signer #1 certificate DN: CN=XCAGI, OU=Mobile, O=成都修茈科技有限公司, L=成都, ST=四川, C=CN
SHA-256: 5ff4f8d7f045817bac644d06ce4781599f38f3965c8ae6c7de3d51723b2e2001
Verified using v2 scheme: true
```

对照：同目录本地 `app-debug.apk` 为 `CN=Android Debug`，与机上包不同。

## 并行桌面真机探针（同会话）

| 端 | health | deliverable-status | 备注 |
|----|--------|-------------------|------|
| Mac `/Applications/XCAGI.app` | **PASS** `10.0.0` | **PASS** `deliverable=true` mods=17 blockers=[] | 本机 |
| DevFleet Win32 `5fdd29c4-…` | **PASS** `10.0.0` | **FAIL** HTTP 404 | 进程在跑；90s 轮询仍 404（疑似 bootstrap/deferred 回归） |

Win32 404 **不阻塞**本份 v10-C 移动签字；记入桌面回归跟踪。

## 已知边界（不挡 PL3 技术签）

1. 审批中心打开后无待办单据（空列表）→ 未做「通过/驳回」写操作复测。  
2. 扫码页为相机/系统层，uiautomator dump 常空；以截图为准，未完成「扫真实桌面 QR → 绑定成功」闭环录屏。  
3. 深链 `xcagi://pairing?...` 本轮未改变前台到配对页（仍落消息 Tab）→ 深链路径待补。  
4. 本机无 Flutter SDK，未重跑 `flutter test`；以机上签名包 + UI 真机为准。

## 签字

| 角色 | 方式 | 日期 |
|------|------|------|
| 工程真机验收 | Cursor Agent + adb UI/截图/apksigner | 2026-07-11 |
| 产品确认 | （可按空审批/扫码闭环补签） | — |

**结论**：v10-C 移动端在绑定小米真机上 **可交付技术签字**；`specs/tasks.md` PL3 勾选。不升版本号。

## 本轮补强（全量闭环 · 同日）

| 项 | 结果 |
|----|------|
| 配对 issue + exchange | PASS（admin 签发；JWT 下发） |
| 审批列表（mobile JWT） | PASS（pending→approved/rejected） |
| Win deliverable 404 根因 | 已修代码：SPA catch-all 重排（见 `v10-full-closure-2026-07-11.md`） |
| 手机深链 UI | PARTIAL（已登录态不跳转配对页；API 闭环已过） |
