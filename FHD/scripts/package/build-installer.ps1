param(
  [string]$Version = "10.0.0",
  [switch]$SkipBackend,
  [Parameter(Mandatory = $true)]
  [ValidateSet('personal', 'enterprise')]
  [string]$ProductSku,
  [switch]$SkipUiInstaller,
  [string]$SunbirdSeedZipPath = '',
  [string]$InstallerOutputSubdir = '',
  [string]$InstallerFileName = ''
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root
$Version = $Version.TrimStart("v", "V")

$skuLabels = @{
  personal   = 'Personal'
  enterprise = 'Enterprise'
}
$skuAppIds = @{
  personal   = 'com.xcagi.desktop.personal'
  enterprise = 'com.xcagi.desktop.enterprise'
}
$skuUpdateUrls = @{
  personal   = 'https://update.xcagi.com/releases/stable/personal/'
  enterprise = 'https://update.xcagi.com/releases/stable/enterprise/'
}

function Assert-TextFileContains {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string[]]$Markers,
    [Parameter(Mandatory = $true)][string]$Label
  )
  if (-not (Test-Path $Path)) {
    throw "$Label missing: $Path"
  }
  $content = Get-Content $Path -Raw
  foreach ($marker in $Markers) {
    if (-not $content.Contains($marker)) {
      throw "$Label is stale or incomplete; missing marker '$marker' in $Path"
    }
  }
}

function Assert-FileExists {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$Label
  )
  if (-not (Test-Path $Path)) {
    throw "$Label missing: $Path"
  }
}

function Write-SkuJson {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$Sku
  )
  $json = @{ sku = $Sku; schema_version = 1 } | ConvertTo-Json -Compress
  $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($Path, "$json`n", $utf8NoBom)
}

$label = $skuLabels[$ProductSku]
$releaseRoot = Join-Path $Root "release\xcagi-v$Version"
$outSubdir = if ($InstallerOutputSubdir) { $InstallerOutputSubdir } else { $ProductSku }
$outDir = Join-Path $releaseRoot $outSubdir
if ($InstallerFileName) {
  $finalSetupName = $InstallerFileName
} else {
  $finalSetupName = "XCAGI-$label-Setup-$Version-x64.exe"
}
$finalSetupPath = Join-Path $outDir $finalSetupName
$licenseSrc = Join-Path $Root "tools\XcagiInstaller\Assets\LICENSE.zh-CN.txt"
if (-not (Test-Path $licenseSrc)) {
  $licenseSrc = Join-Path $Root "LICENSE"
}

New-Item -ItemType Directory -Force -Path $outDir | Out-Null

if (-not $SkipBackend) {
  & "$PSScriptRoot\build-backend.ps1" -Version $Version -ProductSku $ProductSku
} else {
  python -m pip install "Pillow>=10.2.0" -q
}

$backendExe = Join-Path $Root "dist\xcagi-backend\xcagi-backend.exe"
Assert-FileExists $backendExe "Windows backend executable"

$desktopSku = Join-Path $Root "desktop\resources\product-sku.json"
Write-SkuJson -Path $desktopSku -Sku $ProductSku
$backendSku = Join-Path $Root "dist\xcagi-backend\_internal\product-sku.json"
$backendSkuDir = Split-Path $backendSku -Parent
if (Test-Path $backendSkuDir) {
  Write-SkuJson -Path $backendSku -Sku $ProductSku
}

& "$PSScriptRoot\create-installer-assets.ps1"

Push-Location (Join-Path $Root "desktop")
if (-not (Test-Path "node_modules")) {
  npm install
}
npm run build
if ($LASTEXITCODE -ne 0) { throw "desktop npm run build failed" }
Assert-TextFileContains `
  -Path (Join-Path $Root "desktop\dist\main.js") `
  -Label "Electron main bundle" `
  -Markers @(
    "packagedBackendCandidates",
    "electron-backend.log",
    "backend', '_internal'",
    "180_000"
  )
npm version $Version --no-git-tag-version --allow-same-version
$ebAppId = $skuAppIds[$ProductSku]
$ebPublishUrl = $skuUpdateUrls[$ProductSku]
$ebArtifact = "XCAGI-$label-Setup-`${version}-`${arch}.`${ext}"
npx electron-builder --win nsis zip --x64 --publish never `
  "--config.directories.output=../release/xcagi-v$Version/$outSubdir" `
  "--config.appId=$ebAppId" `
  "--config.publish.url=$ebPublishUrl" `
  "--config.nsis.artifactName=$ebArtifact" `
  "--config.extraMetadata.productSku=$ProductSku"
Pop-Location

Assert-FileExists (Join-Path $outDir "win-unpacked\resources\app.asar") "Electron app.asar"
Assert-FileExists (Join-Path $outDir "win-unpacked\resources\backend\xcagi-backend.exe") "Packaged backend executable"
Assert-FileExists (Join-Path $outDir "win-unpacked\resources\product-sku.json") "Packaged product-sku.json"

$nsisExe = Get-ChildItem $outDir -Filter "XCAGI-$label-Setup-*.exe" -File -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1
if (-not $nsisExe) {
  $nsisExe = Get-ChildItem $outDir -Filter "XCAGI-*-Setup-*.exe" -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
}

if (-not $SkipUiInstaller) {
  if (-not $nsisExe) {
    throw "NSIS artifact not found in $outDir; cannot build single-file installer."
  }

  $stagingNsis = Join-Path $outDir 'nsis-payload.tmp.exe'
  Copy-Item $nsisExe.FullName $stagingNsis -Force

  $uiProj = Join-Path $Root "tools\XcagiInstaller\XcagiInstaller.csproj"
  $uiOut = Join-Path $outDir "ui-build"
  New-Item -ItemType Directory -Force -Path $uiOut | Out-Null

  $publishArgs = @(
    "publish", $uiProj,
    "-c", "Release",
    "-r", "win-x64",
    "--self-contained", "true",
    "-p:PublishSingleFile=true",
    "-p:IncludeNativeLibrariesForSelfExtract=true",
    "-p:EnableCompressionInSingleFile=true",
    "-p:Version=$Version",
    "-p:SetupPayloadPath=$stagingNsis",
    "-o", $uiOut
  )
  if (Test-Path $licenseSrc) {
    $publishArgs += "-p:LicenseFilePath=$licenseSrc"
  }
  if ($SunbirdSeedZipPath -and (Test-Path $SunbirdSeedZipPath)) {
    $publishArgs += "-p:SunbirdSeedZipPath=$SunbirdSeedZipPath"
  }
  & dotnet @publishArgs

  $uiExe = Get-ChildItem $uiOut -Filter "XcagiInstaller.exe" | Select-Object -First 1
  if (-not $uiExe) {
    throw "WPF installer publish failed."
  }

  if (Test-Path $finalSetupPath) {
    Remove-Item $finalSetupPath -Force
  }
  Move-Item $uiExe.FullName $finalSetupPath -Force
  Remove-Item $uiOut -Recurse -Force -ErrorAction SilentlyContinue
  Remove-Item $stagingNsis -Force -ErrorAction SilentlyContinue
  if ($nsisExe -and (Test-Path $nsisExe.FullName) -and $nsisExe.FullName -ne $finalSetupPath) {
    Remove-Item $nsisExe.FullName -Force
  }

  $legacyPayload = Join-Path $outDir "_payload"
  if (Test-Path $legacyPayload) {
    Remove-Item $legacyPayload -Recurse -Force
  }
  Get-ChildItem $outDir -Filter "XCAGI-*-*.exe" -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like '*安装程序*' } |
    Remove-Item -Force -ErrorAction SilentlyContinue

  node (Join-Path $Root "scripts\package\generate-update-metadata.mjs") $finalSetupPath $Version win
} elseif ($nsisExe) {
  node (Join-Path $Root "scripts\package\generate-update-metadata.mjs") $nsisExe.FullName $Version win
}

$dlProj = Join-Path $Root "tools\XcagiDownloader\XcagiDownloader.csproj"
$dlOut = Join-Path $outDir "tools"
New-Item -ItemType Directory -Force -Path $dlOut | Out-Null
dotnet publish $dlProj -c Release -r win-x64 --self-contained true `
  -p:PublishSingleFile=true `
  -p:IncludeNativeLibrariesForSelfExtract=true `
  -p:EnableCompressionInSingleFile=true `
  -o $dlOut

Write-Host ""
Write-Host "Done: release\xcagi-v$Version\$outSubdir\$finalSetupName"
