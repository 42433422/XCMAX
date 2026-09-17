# 1.0.0.4 macOS 交付记录（staging，闭环完成后合入 MACOS_RELEASE_SSOT.md）

## 构建锚定
- main HEAD / release_sha：280225ac77ce0b5f66470d2d7a11ad2844cdad67（#1938 squash 合并，backend-test success）
- 扫描对：A=34851505749（13:48:11Z）+ B=34855340685（14:23:55Z），同日间隔 35min44s，双 success 零漏洞
- OTA run：34856380264（构建+签名+公证完成，artifact 551856690B；CVM 直传步骤主动取消——10-40KB/s 链路必超时，走 1.0.0.3 同款恢复路径）

## 发布产物（本机中转，全量指纹核验）
- 官方目录 https://xiu-ci.com/xcagi-v1.0.0.4/enterprise/：DMG+DMG.blockmap+ZIP+ZIP.blockmap+latest-mac.yml 五文件
- OTA 通道 https://xiu-ci.com/releases/stable/enterprise/：ZIP 264533286 + ZIP.blockmap + latest-mac.yml
- 元数据：manifest.json（git_sha/release_id/build_run_id 三锚定 + ed25519 feed 签名）+ download-release.json
- 核验：本地↔CVM 7 文件 SHA256 全匹配；公网四路复验（DMG/manifest/feed/ZIP = 206/200/200/206）；feed 内容 productVersion=1.0.0.4 + buildSha=280225ac77ce + stagingPercentage=100

## 真机闭环（1.0.0.3 → 1.0.0.4 OTA 路径，实跑证据目录 evidence/e2e/macos-release-1.0.0.4/）
- G8 发现：update_available（自动检查 18:00-18:03Z + 启动检查 21:52Z），productVersion/buildSha 锚定一致；UI 三截图
- 下载：blockmap 增量，download_start 18:04:41Z → update_downloaded 18:13:27Z；下载包 SHA256=5514e649… 与发布产物五点同指纹
- G9 安装：install_start 22:14:40Z；ShipIt 替换被 /Applications root:wheel 所有权阻塞（本机 9-13 手动安装污染，非产品缺陷）→ ShipIt 特权 helper 授权中（g9-watch.log）
- G10 数据保持 / G11 业务复测 / G12 重启复验：待 1.0.0.4 启动后跑 t5-post-ota-verify.sh + t6-post-reboot-verify.sh

## 已知结论（供 §7/§8 引用）
- G9 isQuitting 修复（#1930）在触发方 installUpdate()，1.0.0.3 触发方不含修复 → 本轮应用不自动退出为预期复现；完整验证归 1.0.0.4→1.0.0.5 OTA
- 首次点击时「更新并重新加载」按钮 disabled（应用重启后恢复）——update_downloaded 状态跨重启恢复时序，记小缺陷待查
