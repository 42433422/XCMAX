param(
  [string]$Version = "10.0.0",
  [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$Version = $Version.TrimStart("v", "V")

$FhdRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$RepoRoot = Resolve-Path (Join-Path $FhdRoot "..")
$DeliveryDir = Join-Path $RepoRoot "太阳鸟"
$SeedRoot = Join-Path $FhdRoot "delivery\sunbird-seed"
$BuildDir = Join-Path $FhdRoot "build\sunbird-delivery"
$SeedZip = Join-Path $BuildDir "sunbird-seed.zip"
$SetupName = "太阳鸟-Setup-$Version-x64.exe"
$ReleaseExe = Join-Path $FhdRoot "release\xcagi-v$Version\sunbird\$SetupName"

New-Item -ItemType Directory -Force -Path $DeliveryDir, $BuildDir | Out-Null

Write-Host "==> Building sunbird seed (template + roster + mod db) ..."
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
python -m pip install "openpyxl>=3.1" -q
python (Join-Path $FhdRoot "scripts\package\build-sunbird-seed.py")
if ($LASTEXITCODE -ne 0) { throw "build-sunbird-seed.py failed" }

$modsDest = Join-Path $SeedRoot "mods"
New-Item -ItemType Directory -Force -Path $modsDest | Out-Null
foreach ($modId in @("taiyangniao-pro", "attendance-industry")) {
  $src = Join-Path $FhdRoot "mods\$modId"
  if (-not (Test-Path $src)) {
    throw "Missing mod source: $src"
  }
  $dst = Join-Path $modsDest $modId
  if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
  Copy-Item $src $dst -Recurse -Force
  Write-Host "  staged mod: $modId"
}

if (Test-Path $SeedZip) { Remove-Item $SeedZip -Force }
Compress-Archive -Path (Join-Path $SeedRoot '*') -DestinationPath $SeedZip -CompressionLevel Optimal
Write-Host "  seed zip: $SeedZip"

if (-not $SkipBuild) {
  Write-Host "==> Install Python runtime deps (mod staging + PyInstaller) ..."
  python -m pip install --upgrade pip -q
  python -m pip install -e $FhdRoot -q
  if ($LASTEXITCODE -ne 0) { throw "pip install -e FHD failed" }
  python -m pip install "pyinstaller>=6.0" appdirs -q
  if ($LASTEXITCODE -ne 0) { throw "pip install pyinstaller/appdirs failed" }

  Write-Host "==> Building Sunbird custom installer (enterprise base + embedded seed) ..."
  & (Join-Path $PSScriptRoot "build-installer.ps1") `
    -Version $Version `
    -ProductSku enterprise `
    -SunbirdSeedZipPath $SeedZip `
    -InstallerOutputSubdir sunbird `
    -InstallerFileName $SetupName
} else {
  Write-Host "==> SkipBuild: expect existing $ReleaseExe"
}

if (-not (Test-Path $ReleaseExe)) {
  throw "Sunbird installer not found: $ReleaseExe"
}

Copy-Item $ReleaseExe (Join-Path $DeliveryDir $SetupName) -Force

$hash = (Get-FileHash (Join-Path $DeliveryDir $SetupName) -Algorithm SHA256).Hash.ToLower()
@{
  product     = "太阳鸟 PRO"
  delivery_id = "customer-taiyangniao"
  variant     = "sunbird-custom-installer"
  version     = $Version
  installer   = $SetupName
  sha256      = $hash
  built_at    = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
  mod_ids     = @("attendance-industry", "taiyangniao-pro")
  notes       = "定制安装包；安装向导可勾选「获取太阳鸟业务数据」。通用 Enterprise 安装包不变。"
} | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $DeliveryDir "manifest.json") -Encoding UTF8

Write-Host ""
Write-Host "Done."
Write-Host "  Release: $ReleaseExe"
Write-Host "  Delivery folder: $DeliveryDir\$SetupName"
