# FrontendEdition: generic = 默认通用壳（ADCDFG）；full = 完整 ERP 侧栏
param(
  [string]$Version = "10.0.0",
  [switch]$SkipFrontend,
  [ValidateSet('full', 'generic', 'minimal')]
  [string]$FrontendEdition = 'generic',
  [ValidateSet('personal', 'enterprise', '')]
  [string]$ProductSku = ''
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root
$Version = $Version.TrimStart("v", "V")

$skuFrontendMap = @{
  personal = 'minimal'
  enterprise = 'full'
}
if ($ProductSku) {
  if (-not $skuFrontendMap.ContainsKey($ProductSku)) {
    throw "Unknown ProductSku: $ProductSku"
  }
  $buildDir = Join-Path $Root "build"
  New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
  $skuJson = @{ sku = $ProductSku; schema_version = 1 } | ConvertTo-Json -Compress
  $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText((Join-Path $buildDir "product-sku.json"), "$skuJson`n", $utf8NoBom)
  $FrontendEdition = $skuFrontendMap[$ProductSku]
  & "$PSScriptRoot\stage-bundled-mods.ps1" -ProductSku $ProductSku
  & "$PSScriptRoot\stage-industry-seeds.ps1" -ProductSku $ProductSku
}

if (-not $SkipFrontend) {
  Push-Location (Join-Path $Root "frontend")
  if (-not (Test-Path "node_modules")) {
    npm install
  }
  if ($ProductSku) {
    $env:VITE_XCAGI_PRODUCT_SKU = $ProductSku
  }
  $env:VITE_XCAGI_EDITION = $FrontendEdition
  if ($FrontendEdition -eq 'minimal') {
    npm run build:minimal
  } elseif ($FrontendEdition -eq 'full') {
    npm run build:full
  } else {
    npm run build
  }
  Remove-Item Env:VITE_XCAGI_EDITION -ErrorAction SilentlyContinue
  if ($ProductSku) {
    Remove-Item Env:VITE_XCAGI_PRODUCT_SKU -ErrorAction SilentlyContinue
  }
  Pop-Location
}

python -m pip install --upgrade pip
python -m pip install -e ".[server-api]"
if ($LASTEXITCODE -ne 0) { throw "pip install -e FHD[server-api] failed" }
python -m pip install "pyinstaller>=6.0" appdirs
if ($LASTEXITCODE -ne 0) { throw "pip install pyinstaller/appdirs failed" }

$env:XCAGI_VERSION = $Version
if ($ProductSku) {
  $env:XCAGI_PRODUCT_SKU = $ProductSku
}
& "$PSScriptRoot\write-version.ps1" -Version $Version
if ($ProductSku) {
  $stageDir = Join-Path $Root "build\staged-mods-$ProductSku"
  if (Test-Path $stageDir) {
    $env:XCAGI_STAGED_MODS_DIR = $stageDir
    $env:XCAGI_MODS_ROOT = $stageDir
    python "$PSScriptRoot\generate_mods_index.py"
    if ($LASTEXITCODE -ne 0) { throw "generate_mods_index.py failed" }
  }
  $industryStageDir = Join-Path $Root "build\staged-industry-seeds-$ProductSku"
  if (Test-Path $industryStageDir) {
    $env:XCAGI_STAGED_INDUSTRY_SEEDS_DIR = $industryStageDir
  }
}
python -m PyInstaller --noconfirm --clean "scripts\package\xcagi_backend.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller xcagi_backend.spec failed" }
if ($ProductSku) {
  Remove-Item Env:XCAGI_STAGED_MODS_DIR -ErrorAction SilentlyContinue
  Remove-Item Env:XCAGI_STAGED_INDUSTRY_SEEDS_DIR -ErrorAction SilentlyContinue
}

Write-Host "Backend build complete: dist\xcagi-backend"
