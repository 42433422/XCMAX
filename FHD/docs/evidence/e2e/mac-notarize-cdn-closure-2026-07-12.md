# macOS 公证 → staple → CDN → 公网复测闭环（2026-07-12）

> **状态：正式发布面 macOS 闭环 PASS（enterprise + personal）**  
> **版本锚点**：10.0.0（v10 锁，未 bump）  
> **CI**：[Release Desktop #29184238077](https://github.com/42433422/XCMAX/actions/runs/29184238077)（`main` · `version=10.0.0`）  
> **buildSha**：`3f00c87b1792f754e5846935b5c79d6a8b58bab0`

## 链路结果

| 步骤 | 结果 | 说明 |
|------|------|------|
| Apple 公证 | **Accepted** | 多条 `XCAGI.zip` 提交均为 Accepted（含 `4d3a1b66-…`） |
| CI 构建 + Developer ID | **PASS** | `macos (personal/enterprise)` success；codesign 非 adhoc |
| afterSign notarize + staple | **PASS** | 包内 `XCAGI.app`：`Notarization Ticket=stapled` |
| Ed25519 `latest-mac.yml` | **PASS** | CI `Sign update metadata` 已签；本机公钥验签 OK |
| 上传 CDN | **PASS** | CI→CDN 过慢已取消；本机 rsync 上传 `stable/{enterprise,personal}/` |
| 公网下载 | **PASS** | `https://xiu-ci.com/releases/stable/enterprise/…` HTTP 200 |
| SHA512 | **PASS** | 公网 DMG 与 yml `sha512` / `size` 一致 |
| Gatekeeper | **PASS** | `spctl --type install/execute` → `accepted` · `Notarized Developer ID` |
| 更新 feed | **PASS** | `latest-mac.yml` HTTP 200 + Ed25519 |

## CDN 制品（enterprise）

| 文件 | size | releaseDate |
|------|------|-------------|
| `XCAGI-10.0.0-mac-arm64.dmg` | 236693837 | 2026-07-12T07:40:09Z |
| `latest-mac.yml` | 571 | 含 `signature: ed25519:…` · `buildSha: 3f00c87b…` |

personal 同步上架（DMG 235787843 · 同 buildSha）。

## 公网复测摘要

1. `curl` 拉取 `latest-mac.yml` → 桌面内嵌 Ed25519 公钥验签 **PASS**
2. 公网下载 DMG → `size_match` / `sha512_match` **True**
3. 挂载 DMG → `codesign` Developer ID + ticket stapled → `stapler validate` OK
4. `ditto` 到隔离目录 + quarantine 模拟 → `spctl --type execute` **accepted**（Notarized Developer ID）
5. 更新源 `https://xiu-ci.com/releases/stable/enterprise/latest-mac.yml` → HTTP 200

证据目录（文本日志；大体积 DMG 不入库）：`FHD/docs/evidence/e2e/mac-notarize-cdn-20260712/retest/`

## 备注

- CI `deploy-macos` rsync 约 1MB/min，已 `gh run cancel`；改由本机 SSH rsync（~15MB/s）完成上传。
- DMG 外壳未单独 staple（`spctl --type open` 对 dmg 可能仍报 Unnotarized）；**包内 app 已 staple**，拖入 Applications / Gatekeeper 安装路径已通过。
- 本机启动复测时 17555 未监听（参数未透传）；既有 17500 实例 `deliverable-status` 返回 `deliverable=true` · `blockers=[]`（对照用，非本轮 CDN 新包冷启）。
