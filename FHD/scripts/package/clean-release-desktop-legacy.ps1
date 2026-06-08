<#
.SYNOPSIS
  删除 E:\FHD\release 下旧的桌面构建目录，只保留当前使用的输出目录。

.DESCRIPTION
  会删除（若存在）：
    release/desktop
    release/desktop-designed
    release/desktop-designed-final
    release/v6.0.0

  保留：
    release/desktop-designed-final2  （electron-builder 当前 output，v7 桌面安装包）

  若提示 app.asar 被占用：请退出从上述 win-unpacked 启动的 XCAGI、关闭可能锁定该文件的
  编辑器/索引后再执行本脚本。

.PARAMETER StripUnpacked
  若指定，则额外删除 release/desktop-designed-final2/win-unpacked（仅保留 Setup.exe、
  zip、latest.yml、blockmap 等分发文件，可省大量磁盘空间；本地免安装调试需重新 dist）。
#>
param(
  [switch]$StripUnpacked
)

$ErrorActionPreference = "Continue"
$Repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Release = Join-Path $Repo "release"

$legacy = @(
  "desktop",
  "desktop-designed",
  "desktop-designed-final",
  "v6.0.0"
)
foreach ($name in $legacy) {
  $p = Join-Path $Release $name
  if (-not (Test-Path $p)) { continue }
  Write-Host "Removing $p ..."
  try {
    Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction Stop
  } catch {
    Write-Warning "未能删除（通常因 win-unpacked/resources/app.asar 被占用）: $p — 请退出 XCAGI/Cursor 后重试。"
  }
}

if ($StripUnpacked) {
  $unpacked = Join-Path $Release "desktop-designed-final2\win-unpacked"
  if (Test-Path $unpacked) {
    Write-Host "Removing $unpacked ..."
    try {
      Remove-Item -LiteralPath $unpacked -Recurse -Force -ErrorAction Stop
    } catch {
      Write-Warning "未能删除 win-unpacked（有进程占用 app.asar）。"
    }
  }
}

Write-Host "Done. Kept: desktop-designed-final2 (v7)"
Get-ChildItem $Release -Directory | Select-Object Name, LastWriteTime
