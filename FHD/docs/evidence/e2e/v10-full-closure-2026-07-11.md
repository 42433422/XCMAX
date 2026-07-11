# v10 全量闭环修复记录（2026-07-11）

> 分支：`fix/v10-full-closure-loop` · 锚点 10.0.0

## 代码修复（Win deliverable 404 根因）

桌面 `XCAGI_DESKTOP_FAST_START=1` 时：

1. `create_fastapi_app` 先挂 bootstrap，再挂 SPA `GET /{fallback:path}`
2. deferred / Mod 路由事后 `include_router` 追加在 SPA **之后**
3. Starlette **先匹配先胜**：GET `/api/*` 被 SPA 吞掉 → `资源不存在：/api/...`
4. POST 不受影响（SPA 仅注册 GET）→ 故 pairing/issue POST 仍 200

**修复**：

- `deferred_startup.py`：deferred 注册后、heavy startup 结束后调用 `ensure_spa_fallback_last`
- `fastapi_routes/__init__.py`：deferred 再补挂 platform-shell bootstrap
- 回归测试：`tests/test_fastapi_app/test_spa_fallback_reorder.py`（3 passed）

## 真机闭环（Mac + 小米）

| 项 | 结果 | 证据 |
|----|------|------|
| 配对 issue（admin 会话） | PASS | `12-pairing-issue.json` |
| 配对 exchange → token | PASS | `12-pairing-exchange.json`（JWT 已脱敏） |
| 手机深链 | PARTIAL | 已登录态仍落消息 Tab；API 闭环已足够 |
| 审批造数 + 列表 | PASS | mobile JWT 可见 pending→approved/rejected |
| 审批写状态 | PASS | DB 闭环：id=1 approved / id=2 rejected；`15-mobile-approval-final.json` |
| NR_SA + Wi‑Fi | PASS | 前序真机证据 |

## Win32

- 复现：openapi 有 `/api/platform-shell/deliverable-status`，GET 被 SPA 404
- 临时验证：尝试 patch `app.asar` 将 `XCAGI_DESKTOP_FAST_START` 置 `0` 后重启（需看本轮探针）
- 长久：合并本分支后重新打包 Windows backend / 全量 installer

## 仍非本轮代码能独解

- macOS Developer ID / 公证 / `latest-mac.yml` Ed25519
- 商店上架正式 keystore（机上已是公司证书，本机构建机仍无 Flutter SDK）
