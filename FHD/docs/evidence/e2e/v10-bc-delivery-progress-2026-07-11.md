# v10-B/C 交付推进记录（2026-07-11 · v10 线内迭代）

> 状态：**v10-B PL2 / v10-C PL3 均已技术签字**（2026-07-11）。  
> 对照：`specs/tasks.md` PL2/PL3 · `specs/product-lines-3-plus-2.md` v10-B/C。

## 收口结果

| 阶段 | 项 | 状态 |
|------|----|------|
| v10-B | Mod pilot 四图 + acceptance | **终稿** → `v10-b-store-desktop-acceptance-2026-07-11-final.md`；PL2 已勾 |
| v10-B | 支付履约 → `user_mods` | **代码落地** |
| v10-C | Flutter 主线 / CI / 路由与审批 | **代码落地** |
| v10-C | 真机 E2E + 非 debug 签名包 | **终稿** → `v10-c-mobile-acceptance-2026-07-11-final.md`；PL3 已勾 |

## 上线动作（本轮）

1. `git push origin main`（含 PL2/PL3 签字文档）
2. `workflow_dispatch`：CI/CD `push_to_cvm=true`（生产 channel）
3. `workflow_dispatch`：Deploy MODstore Production
4. `workflow_dispatch`：Release Orchestrator（桌面/Web/Android 客户端制品）

正式对外发布仍受桌面发布面约束：macOS Developer ID/公证、`latest-mac.yml` Ed25519、以及 Win32 `deliverable-status` 404 回归。
