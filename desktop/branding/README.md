# 桌面 / Android 双 SKU 图标

| 文件 | SKU |
|------|-----|
| `app-icon-personal-source.png` | **个人版**（XC 渐变标） |
| `app-icon-source.png` | **企业版**（现有图标，主图源） |
| `app-icon-enterprise-source.png` | 企业版备用（与 `resources/icon-enterprise.png` 同步时可作备份） |

重新生成：

```powershell
cd E:\XCMAX\FHD
python scripts/package/generate-desktop-resources.py --sku all
python scripts/package/generate-android-icons.py
```

打安装包时 `build-installer.ps1 -ProductSku personal|enterprise` 会自动选用对应图标。
