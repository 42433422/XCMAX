# v10-B/C 交付推进记录（2026-07-11 · v10 线内迭代）

> 状态：**进行中**，非正式签字终稿。  
> 对照：`specs/tasks.md` PL2/PL3 · `specs/product-lines-3-plus-2.md` v10-B/C。

## 本次收口

| 阶段 | 项 | 状态 |
|------|----|------|
| v10-C | Flutter `preferCloudIfLanUnreachable` + session base 路由 | **代码落地**（单测 `lan_cloud_routing_test.dart`） |
| v10-C | 探索 Tab 增加「审批」入口 | **代码落地** |
| v10-C | 通知页去掉 API 空/失败时的假数据 fallback | **代码落地** |
| v10-C | 审批驳回触发 `notify_mobile_user`（与通过路径对齐） | **代码落地** |
| v10-B | 支付履约写 `user_mods`（`pkg_id` → entitlement 桌面可见） | **代码落地** |
| v10-C | Flutter 发版 CI 切离 `mobile-android` | **已切**（`fhd-ci-mobile-flutter` / `fhd-release-android` / `android-build`） |
| v10-C | 真机 E2E 证据（登录/扫码/5G/审批闭环） | **未做** |
| v10-B | Mod pilot 四图 + `v10-b-*-acceptance` 签字 | **部分**：01/02/04 已刷新；03 仍需 `MOD_PILOT_ALIPAY_BUYER*` |

## 下一步（最短）

1. 配置沙箱买家后重跑 `03-payment`，再写 `v10-b-*-acceptance`
2. `cd FHD/mobile-flutter-poc && flutter test`（本机需 Flutter SDK）
3. Flutter release 签名（仍 debug）+ 真机 E2E 后升格 `*-final.md` 并勾选 PL2/PL3
