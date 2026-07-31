# 历史离线版与个人版停发 — 站外操作清单

当前正式发布只允许 **enterprise**。`offline` 与 `personal` 目录仅为旧客户端兼容保留，不接收新制品。

## update.xcagi.com

- 新包仅上传到 `/releases/stable/enterprise/`
- **不再**向 `/releases/stable/offline/` 上传新版本（历史目录可只读保留）
- **不再**向 `/releases/stable/personal/` 上传新版本（历史目录可只读保留）

## MODstore 官网下载页

在 `MODstore_deploy`（或实际 market 前端仓库）：

1. 下载卡片只展示 **企业版**
2. 移除「离线版」标题与 `XCAGI-Offline-Setup-*.exe` 链接
3. 环境变量仍为：

```env
VITE_XCAGI_DOWNLOAD_VERSION=1.0.0.1
VITE_XCAGI_DOWNLOAD_BASE_URL=https://xiu-ci.com/xcagi-v1.0.0.1
```

4. 重建并部署 market 前端

## Android 分发

- 对外只提供签名后的 `XCAGI-Enterprise-Android-1.0.0.1.apk`
- 历史 `personal` applicationId 不再新增版本；恢复前必须先重新评审产品线规范
