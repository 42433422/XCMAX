# 将最新 frontend 构建产物同步到本机已安装的 XCAGI（桌面包不含 admin-vue-dist）
# Edition: generic = 默认通用壳（ADCDFG）；full = 完整 ERP
param(
  [switch]$AlsoWinUnpacked,
  [switch]$Build,
  [ValidateSet('full', 'generic', 'minimal')]
  [string]$Edition = 'generic',
  [ValidateSet('personal', 'enterprise')]
  [string]$ProductSku = 'enterprise',
  [string]$Version = '1.0.0.1'
)

$ErrorActionPreference = 'Stop'
$Root = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$Src = Join-Path $Root 'templates\vue-dist'

$skuEditionMap = @{
  personal   = 'minimal'
  enterprise = 'full'
}

if ($Build -or -not (Test-Path (Join-Path $Src 'index.html'))) {
  Push-Location (Join-Path $Root 'frontend')
  if (-not (Test-Path 'node_modules')) {
    npm install
  }
  $buildEdition = if ($skuEditionMap.ContainsKey($ProductSku)) {
    $skuEditionMap[$ProductSku]
  } else {
    $Edition
  }
  $env:VITE_XCAGI_PRODUCT_SKU = $ProductSku
  $env:VITE_XCAGI_EDITION = $buildEdition
  if ($buildEdition -eq 'minimal') {
    npm run build:minimal
  } elseif ($buildEdition -eq 'full') {
    npm run build:full
  } else {
    npm run build
  }
  Remove-Item Env:VITE_XCAGI_EDITION -ErrorAction SilentlyContinue
  Remove-Item Env:VITE_XCAGI_PRODUCT_SKU -ErrorAction SilentlyContinue
  Pop-Location
}

if (-not (Test-Path (Join-Path $Src 'index.html'))) {
  throw "Missing vue-dist at $Src — run with -Build or build frontend first."
}

$hash = 'unknown'
$html = Get-Content (Join-Path $Src 'index.html') -Raw -Encoding UTF8
if ($html -match 'index-([A-Za-z0-9]+)\.js') { $hash = $Matches[1] }

$targets = @(
  (Join-Path $env:LOCALAPPDATA 'Programs\XCAGI\resources\backend\_internal\templates\vue-dist'),
  (Join-Path $env:LOCALAPPDATA 'Programs\XCAGI\resources\frontend')
)
if ($AlsoWinUnpacked) {
  $ver = $Version.TrimStart('v', 'V')
  $unpacked = Join-Path $Root "release\xcagi-v$ver\$ProductSku\win-unpacked\resources"
  if (Test-Path $unpacked) {
    $targets += @(
      (Join-Path $unpacked 'backend\_internal\templates\vue-dist'),
      (Join-Path $unpacked 'frontend')
    )
  } else {
    Write-Warning "win-unpacked not found: $unpacked (build with -ProductSku $ProductSku first)"
  }
}

function Sync-Robocopy([string]$from, [string]$to) {
  $parent = Split-Path $to
  if (-not (Test-Path $parent)) { return $false }
  if (Test-Path $to) { Remove-Item $to -Recurse -Force }
  New-Item -ItemType Directory -Force -Path $parent | Out-Null
  robocopy $from $to /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "robocopy failed: $to (exit $LASTEXITCODE)" }
  return $true
}

$synced = 0
foreach ($dst in $targets) {
  if (Sync-Robocopy $Src $dst) { $synced++ }
}

# 若旧安装残留 admin-vue-dist，主动清掉（桌面禁止本地管理端）
$staleAdmin = @(
  (Join-Path $env:LOCALAPPDATA 'Programs\XCAGI\resources\backend\_internal\templates\admin-vue-dist')
)
if ($AlsoWinUnpacked) {
  $ver = $Version.TrimStart('v', 'V')
  $unpacked = Join-Path $Root "release\xcagi-v$ver\$ProductSku\win-unpacked\resources"
  if (Test-Path $unpacked) {
    $staleAdmin += (Join-Path $unpacked 'backend\_internal\templates\admin-vue-dist')
  }
}
foreach ($adminPath in $staleAdmin) {
  if (Test-Path $adminPath) {
    Remove-Item $adminPath -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Removed stale admin-vue-dist: $adminPath"
  }
}

$cacheRoot = Join-Path $env:APPDATA 'xcagi-desktop'
foreach ($sub in @('Cache', 'Code Cache', 'GPUCache')) {
  $p = Join-Path $cacheRoot $sub
  if (Test-Path $p) {
    Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Cleared Electron cache: $p"
  }
}

Write-Host "Synced vue-dist (edition=$Edition, index-$hash.js) -> $synced path(s)."
Write-Host 'Desktop package does not include admin-vue-dist (web admin only).'
Write-Host 'Restart XCAGI from Start Menu.'
Write-Host 'If menu still shows 产品管理/出货记录: Settings -> switch industry to 考勤 (saved profile may be 涂料).'
