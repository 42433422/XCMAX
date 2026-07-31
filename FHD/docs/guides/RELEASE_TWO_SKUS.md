# XCAGI 1.0.0.1 企业版稳定发版指南

> 发布范围遵循 [`specs/product-lines-3-plus-2.md`](../../../specs/product-lines-3-plus-2.md)：当前稳定发布 SKU 只有 `enterprise`。`personal` 已冻结，不进入版本目标、销售口径、构建矩阵、上传目录、下载清单或验收门禁。历史文件名保留，是为了兼容旧链接与未来恢复入口。

对外产品版本固定为 `1.0.0.1`，Electron 工具链版本映射为 `1.0.0`。

## 1. 发版前安全自检

```powershell
cd e:\XCMAX\FHD
powershell -ExecutionPolicy Bypass -File scripts/package/pre-release-security.ps1 `
  -Phase pre -Version 1.0.0.1 -ProductSku enterprise
```

## 2. 构建企业版安装包

Windows 正式包必须包含 `win-unpacked/resources/backend/xcagi-backend.exe`：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/package/build-installer.ps1 `
  -Version 1.0.0.1 -ProductSku enterprise -SkipUiInstaller
```

macOS 安装包：

```bash
bash scripts/package/build-installer.sh 1.0.0.1 enterprise
```

发布元数据必须使用 CI 中的 `XCAGI_UPDATE_ED25519_PRIVATE_KEY` 签名；私钥不得写入仓库。

## 3. 构建后验收

```powershell
$v = "1.0.0.1"
powershell -File scripts/package/verify-bundled-mods.ps1 `
  -ProductSku enterprise `
  -UnpackedDir "release/xcagi-v$v/enterprise/win-unpacked/resources/backend/_internal/mods"
powershell -File scripts/package/pre-release-security.ps1 `
  -Phase post -Version $v -ProductSku enterprise
```

post 验收会硬性检查 Windows 后端 exe、`product-sku.json`、staged mods 和 enterprise `industry-seeds/`，任何缺项都不得发布。

## 4. 上传与目录约束

手工上传只允许指定企业版：

```powershell
powershell -File scripts/package/upload-release-skus.ps1 `
  -Version 1.0.0.1 -ProductSku enterprise
```

正式目录只写入：

```text
/var/www/update/releases/stable/enterprise/
/var/www/xcagi-v1.0.0.1/enterprise/
```

禁止把新制品写入 `/personal/`。个人版历史文件可以为兼容旧客户端保留，但不得出现在新的 `manifest.json` 或 `download-release.json` 中。

## 5. 官网下载

官网运行时读取：

```text
https://xiu-ci.com/download-release.json
https://xiu-ci.com/xcagi-v1.0.0.1/manifest.json
```

`release_ready=true` 只在企业版 Windows 与 macOS 制品都完成上传、HTTP 200、大小、SHA256 和安装包 magic 校验后生成。下载页只展示企业版入口。

## 6. 发版后抽检

- Windows 企业版 URL 可下载，SHA256 与 manifest 一致
- macOS 企业版 URL 可下载，SHA256 与 manifest 一致，Developer ID 签名有效
- 企业版安装后 ERP 菜单、AI 员工与行业 Mod 可用
- 自动更新只读取 `/releases/stable/enterprise/latest*.yml`
- manifest 中 `active_skus=["enterprise"]`，且不存在 `personal` 下载项
- 官网根 `download-release.json` 仅在以上检查全部通过后原子切换

## 7. 个人版冻结边界

允许保留个人版构建代码、旧测试和历史下载文件，用于兼容与未来恢复；默认 CI、正式发布、官网和销售资料不得调用这些入口。恢复个人版必须先修改产品线规范并重新评审发布门禁。
