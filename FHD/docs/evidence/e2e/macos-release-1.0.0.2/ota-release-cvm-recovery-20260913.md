# 1.0.0.2 正式发布 CVM 恢复证据（2026-09-13）

## 背景

release run 34732266439（checkout 6eda2203df27c53958b9d7af0e6db26d22b560c4 = main HEAD #1912）
构建+签名+公证+扫描对门禁全部通过，仅「Publish macOS OTA artifacts to CVM」步骤
180min 超时失败。按 workflow 设计走 artifact 手动恢复路径。

## 扫描对（fail-closed 证据）

- A: run 34729999599, success, 锚定 6eda2203d, 完成 2026-09-13T01:22:27Z
- B: run 34731821526, success, 锚定 6eda2203d, 完成 2026-09-13T02:04:11Z（实际结论，v10 脚本误判为空）
- 间隔: 35 分 07 秒（≥30min）
- release run 内 verify_security_scan_pair.py: PASS

## SHA256 比对（本地 artifact vs CVM stable 路径）

```
f00801b0679f6cd10af2c844c29846d2cd26acb729414f38d147aea5e77b2a28  XCAGI-Enterprise-1.0.0.2-mac-arm64.dmg        (307,268,181 B)
44c1a3807100c9805af0fe276af790e083cf77da942e710c75e63c1495a6e7b6  XCAGI-Enterprise-1.0.0.2-mac-arm64.zip        (264,517,668 B)
9f800ab610d04b97615fba1ecaea79855cef71a71a65b911f9b0fef5cbea9e7f  XCAGI-Enterprise-1.0.0.2-mac-arm64.dmg.blockmap
b4943e2940c5d67df2d9515a277f633d09a803d3bd809662fb4485343072215b  XCAGI-Enterprise-1.0.0.2-mac-arm64.zip.blockmap
c1b53da6037f4ac21c6da16a687ad82bf2e3dbdd379c10d2ac648be0b646f9aa  latest-mac.yml
```

本地 artifact 与 CVM（官方 `/var/www/xcagi-v1.0.0.2/enterprise/` + stable
`/var/www/update/releases/stable/enterprise/`）双路径全部一致。

## latest-mac.yml 身份

- productVersion: 1.0.0.2
- buildSha: 6eda2203df27c53958b9d7af0e6db26d22b560c4
- releaseDate: 2026-09-13T02:22:10.223Z
- signature: ed25519:Twgy+6jsF9J9T2k15uGEjQINKW6EwxnnWYHpNQiWvqWv/dISuDHQcRYyv+XpyoxkOpXYxgzdJHEgDBXrDqnrAA==

## 签名与公证实测（发布 DMG 原件挂载）

- codesign --verify --deep --strict: PASS (exit=0)
- flags=0x10000 (hardened runtime), TeamIdentifier=G26WSH472M
- spctl --assess --type execute: exit=0 (accepted, 公证通过)

## 公开 URL 复验

- https://xiu-ci.com/releases/stable/enterprise/latest-mac.yml → buildSha=6eda2203d ✓
- https://xiu-ci.com/xcagi-v1.0.0.2/manifest.json → git_sha=6eda2203d，DMG SHA256/size 与实测一致 ✓
- https://xiu-ci.com/xcagi-v1.0.0.2/enterprise/XCAGI-Enterprise-1.0.0.2-mac-arm64.zip → HTTP 206 可下载 ✓

## 异常处置记录

1. stable 路径曾被并行会话写入 **fa3c8832e 未验证产物**（v8 扫描 B 失败，该 SHA 从未通过扫描对）
   → 已备份后用合法 6eda2203d 产物覆盖，备份文件已清理。
2. rsync 断链两次 → `--partial` 断点续传 + SHA256 达标循环直至完成。
