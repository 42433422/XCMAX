# 内部运营实例（admin SKU）— 本地开发包提示，非客户 update 通道
param(
    [string]$Version = "9.0.0"
)

$ErrorActionPreference = "Stop"
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Write-Host "XCAGI admin operator instance — use FHD source tree with:"
Write-Host "  XCAGI_PRODUCT_SKU=admin"
Write-Host "  FASTAPI_PORT=5100"
Write-Host "  See: docs/guides/ADMIN_OPERATOR_INSTANCE.md"
Write-Host ""
Write-Host "Version anchor: $Version (align with VERSION.md)"
Write-Host "No installer build in this script; run enterprise/personal via build-all-skus.ps1 for customers."

exit 0
