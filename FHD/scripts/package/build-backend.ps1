# FrontendEdition: generic = 默认通用壳（ADCDFG）；full = 完整 ERP 侧栏
param(
  [string]$Version = '',
  [switch]$SkipFrontend,
  [ValidateSet('full', 'generic', 'minimal')]
  [string]$FrontendEdition = 'generic',
  [ValidateSet('personal', 'enterprise', '')]
  [string]$ProductSku = ''
)

$ErrorActionPreference = "Stop"
# Windows redirects Python output through the runner's legacy code page unless
# this is set before the first source/dependency check.
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
. (Join-Path $PSScriptRoot 'product-version.ps1')
$Version = Resolve-ProductVersion -Version $Version
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root
& python scripts/dev/mods_ssot.py check
if ($LASTEXITCODE -ne 0) { throw 'Mod source/export drift; synchronize the authoritative mods/ source before packaging.' }
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
  Write-Host "[backend-build] $(Get-Date -Format o) frontend started"
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
  # 桌面包不构建 admin-console（管理端仅网页 SSOT）
  Write-Host "[backend-build] $(Get-Date -Format o) frontend command completed"
} else {
  Write-Host "[backend-build] $(Get-Date -Format o) frontend skipped by request"
}

# 硬门禁：缺 Vite 产物会打出「白屏/无页面」桌面包。
$vueDist = Join-Path $Root 'templates\vue-dist'
$vueIndex = Join-Path $vueDist 'index.html'
if (-not (Test-Path $vueIndex)) {
  throw "missing $vueIndex; refuse to package empty frontend. Build frontend first (or omit -SkipFrontend)."
}
$jsCount = @(Get-ChildItem -Path (Join-Path $vueDist 'assets\js') -Filter '*.js' -File -ErrorAction SilentlyContinue).Count
if ($jsCount -lt 1) {
  throw "$vueDist\assets\js has no *.js (count=$jsCount); refuse empty vue-dist package."
}
Write-Host "[ok] vue-dist gate: index.html present, assets/js count=$jsCount"

Write-Host "[backend-build] $(Get-Date -Format o) runtime dependency installation started"
python -m pip install --upgrade pip
python -m pip install -c deploy/requirements-server-api.lock.txt -e ".[server-api]"
if ($LASTEXITCODE -ne 0) { throw "pip install -e FHD[server-api] failed" }
python -m pip check
if ($LASTEXITCODE -ne 0) { throw "server-api runtime dependencies are inconsistent" }
python -m pip install "pyinstaller>=6.0" appdirs
if ($LASTEXITCODE -ne 0) { throw "pip install pyinstaller/appdirs failed" }
Write-Host "[backend-build] $(Get-Date -Format o) runtime dependency installation completed"

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
Write-Host "[backend-build] $(Get-Date -Format o) PyInstaller started"
python -m PyInstaller --noconfirm --clean "scripts\package\xcagi_backend.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller xcagi_backend.spec failed" }
Write-Host "[backend-build] $(Get-Date -Format o) PyInstaller completed"

$bundledIndex = Join-Path $Root 'dist\xcagi-backend\_internal\templates\vue-dist\index.html'
if (-not (Test-Path $bundledIndex)) {
  throw "PyInstaller output missing bundled vue-dist index: $bundledIndex"
}
$bundledJs = @(Get-ChildItem -Path (Join-Path $Root 'dist\xcagi-backend\_internal\templates\vue-dist\assets\js') -Filter '*.js' -File -ErrorAction SilentlyContinue).Count
if ($bundledJs -lt 1) {
  throw 'bundled vue-dist/assets/js empty — desktop would show no page'
}
Write-Host "[ok] bundled vue-dist ($bundledJs js)"

$backendExe = Join-Path $Root 'dist\xcagi-backend\xcagi-backend.exe'
if (-not (Test-Path -LiteralPath $backendExe)) {
  throw "PyInstaller output missing backend executable: $backendExe"
}
# Use the finished windowed executable outside the source checkout. A developer
# Python environment can mask missing bundled dependencies such as defusedxml.
$probeDir = Join-Path ([System.IO.Path]::GetTempPath()) ("xcagi-frozen-probe-" + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $probeDir | Out-Null
try {
  Write-Host "[backend-build] $(Get-Date -Format o) frozen runtime probe started"
  $probe = Start-Process -FilePath $backendExe `
    -ArgumentList @('--verify-frozen-critical-runtime', '--data-dir', "`"$(Join-Path $probeDir 'data')`"") `
    -WorkingDirectory $probeDir -PassThru `
    -RedirectStandardOutput (Join-Path $probeDir 'stdout.log') `
    -RedirectStandardError (Join-Path $probeDir 'stderr.log')
  if (-not $probe.WaitForExit(300000)) {
    # Stop only the probe created above; do not terminate other desktop runtimes.
    Stop-Process -Id $probe.Id -Force -ErrorAction SilentlyContinue
    [void]$probe.WaitForExit(5000)
    throw "Frozen critical runtime probe timed out after 300 seconds (pid=$($probe.Id))"
  }
  $probe.Refresh()
  if ($probe.ExitCode -ne 0) {
    throw "Frozen critical runtime probe failed with exit code $($probe.ExitCode)"
  }
  Write-Host "[backend-build] $(Get-Date -Format o) frozen runtime probe completed"
} finally {
  # Windowed Python can fall back to its bootstrap file when stdio is absent.
  # Emit all synthetic probe diagnostics to the CI log before removing them.
  foreach ($relativeLog in @('stdout.log', 'stderr.log', 'data\logs\backend-bootstrap.log', 'data\logs\frozen-runtime-probe.log')) {
    $probeLog = Join-Path $probeDir $relativeLog
    if (Test-Path -LiteralPath $probeLog) {
      Write-Host "[frozen-runtime-probe] $relativeLog"
      Get-Content -LiteralPath $probeLog -ErrorAction SilentlyContinue
    }
  }
  Remove-Item -LiteralPath $probeDir -Recurse -Force -ErrorAction SilentlyContinue
}

if ($ProductSku) {
  Remove-Item Env:XCAGI_STAGED_MODS_DIR -ErrorAction SilentlyContinue
  Remove-Item Env:XCAGI_STAGED_INDUSTRY_SEEDS_DIR -ErrorAction SilentlyContinue
}

Write-Host "Backend build complete: dist\xcagi-backend"
