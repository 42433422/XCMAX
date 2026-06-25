param(
  [string]$Version = "10.0.0",
  [switch]$SkipUiInstaller,
  # 个人版已停产（config/product.yaml editions.personal=discontinued）。
  # 默认只产 enterprise；仅未来恢复时显式 -IncludePersonal 才一并构建 personal。
  [switch]$IncludePersonal
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Version = $Version.TrimStart("v", "V")
$releaseRoot = Join-Path $Root "release\xcagi-v$Version"

$skus = @('enterprise')
if ($IncludePersonal) { $skus += 'personal' }

foreach ($sku in $skus) {
  New-Item -ItemType Directory -Force -Path (Join-Path $releaseRoot $sku) | Out-Null
}

$personalLine = if ($IncludePersonal) {
  "personal/    — (已停产，仅 -IncludePersonal 恢复) XCAGI-Personal-Setup-$Version-x64.exe`n"
} else { "" }

$readme = @"
XCAGI v$Version — 发行目录（企业版唯一在产；个人版已停产）

enterprise/  — XCAGI-Enterprise-Setup-$Version-x64.exe + latest.yml + tools/
$personalLine
上传: scripts/package/upload-release-skus.ps1
官网: {BASE}/enterprise/{文件名}
"@
Set-Content -Path (Join-Path $releaseRoot "README.txt") -Value $readme -Encoding UTF8

foreach ($sku in $skus) {
  Write-Host "========== Building SKU: $sku =========="
  $args = @(
    '-File', (Join-Path $PSScriptRoot 'build-installer.ps1'),
    '-Version', $Version,
    '-ProductSku', $sku
  )
  if ($SkipUiInstaller) { $args += '-SkipUiInstaller' }
  & powershell @args
  if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
    throw "build-installer failed for SKU $sku (exit $LASTEXITCODE)"
  }
}

Write-Host ""
Write-Host "Built SKUs:"
foreach ($sku in $skus) { Write-Host "  $releaseRoot\$sku\" }
