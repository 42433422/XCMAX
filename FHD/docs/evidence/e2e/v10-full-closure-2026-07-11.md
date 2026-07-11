# v10 全量闭环修复记录（2026-07-11）

> 分支：`fix/v10-full-closure-loop` · 锚点 10.0.0 · PR [#147](https://github.com/42433422/XCMAX/pull/147)

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

## Win32 热修验证（2026-07-11 晚 · DevFleet）

设备：`5fdd29c4-9140-48fa-a28b-ab5db375201f`（Win32）

1. `git checkout` → `0a7caa66` / `fix/v10-full-closure-loop`
2. `win_v10a_hotfix_deploy.ps1` 重建并部署 `Local\\Programs\\XCAGI\\resources\\backend`
3. 探针：

| URL | 结果 |
|-----|------|
| `GET /api/health` | **200** `healthy` `10.0.0` |
| `GET /api/platform-shell/deliverable-status` | **200** `deliverable=true` `mods_routes=true` `blockers=0` |
| `GET /api/mods` | **200** JSON 列表（非 SPA 404） |

说明：脚本尾部 `migrate-only` 因 PowerShell 把 INFO 日志当 NativeCommandError 退出码 1，**不影响** deliverable 闭环（已单独复验 200）。

## 发布面

| 项 | 状态 |
|----|------|
| CDN `latest-mac.yml` Ed25519 | **PASS**（公钥验签 OK，`xiu-ci.com/.../enterprise/latest-mac.yml`） |
| 本机 `/Applications/XCAGI.app` | adhoc（非正式公证安装包；需 Developer ID 重打） |
| macOS CI Release Desktop | 曾因 `npm Invalid version: main` 失败；`build-installer.sh` 已加 semver 兜底 `10.0.0`；已对 `fix/v10-full-closure-loop` `workflow_dispatch` `version=10.0.0`（run 29163785828） |
| ASC Issuer ID（本机 notarytool） | **缺**（Team API Key 需 Issuer UUID；仅在 GitHub Secrets，本机 `mac-signing.env` 未填 Issuer） |
| Win 热修证据 | `19-win-deliverable-pass.json` |

## 下一步（运维）

1. 合并 PR #147（勿再改 `FHD/.github/workflows/`，免 Guard Guards）
2. 本机公证：把 `APP_STORE_CONNECT_API_ISSUER_ID`（UUID）写入 `mac-signing.env` 后 `setup-mac-signing.sh` + `build-installer.sh 10.0.0 enterprise`
3. 跟进 CI Release Desktop run `29163785828` 产物与 CDN 上传
