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
| v10-B | Mod pilot 四图 + `v10-b-*-acceptance` 签字 | **部分**：01/02/04 绿；03 支持买家 env / `MOD_PILOT_ALIPAY_MANUAL=1`；底稿已写 |
| v10-C | Flutter release 签名 | **可接**：`key.properties` / `XCAGI_ANDROID_*`；无密钥仍回退 debug |

## 下一步（最短）

1. 填 `~/.xcmax/mod-pilot.env` 买家，或 `MOD_PILOT_ALIPAY_MANUAL=1` 人工付 → 刷 `03-payment.png`
2. 03 绿后把 `v10-b-store-desktop-acceptance-2026-07-11.md` 升格 `*-final` 并勾 PL2
3. 本机装 Flutter SDK 后 `flutter test`；配 release keystore 后设 `XCAGI_REQUIRE_RELEASE_SIGNING=1`
