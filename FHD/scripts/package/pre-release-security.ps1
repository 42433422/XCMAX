param(
  [ValidateSet('pre', 'post')]
  [string]$Phase = 'pre',
  [string]$Version = '10.0.0',
  [ValidateSet('personal', 'enterprise', 'all')]
  [string]$ProductSku = 'all'
)

$ErrorActionPreference = 'Stop'
$Root = Resolve-Path (Join-Path $PSScriptRoot '..\..')
Set-Location $Root
$Version = $Version.TrimStart('v', 'V')
$erpMod = 'xcagi-erp-domain-bridge'
$excludedMods = @('taiyangniao-pro', 'sz-qsm-pro', '_employees', 'industry-solutions')
$skus = if ($ProductSku -eq 'all') { @('personal', 'enterprise') } else { @($ProductSku) }

function Fail([string]$msg) {
  Write-Error "[pre-release-security] $msg"
}

function Scan-SecretsInTree {
  param([string]$Dir, [string]$Label)
  if (-not (Test-Path $Dir)) { return }
  $hits = Get-ChildItem -Path $Dir -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object {
      $_.Name -match '\.env$' -and $_.Name -ne '.env.example' -or
      $_.Name -match 'secret|private_key' -or
      $_.Extension -in @('.pem', '.key')
    } |
    Where-Object {
      $_.FullName -notmatch '\\node_modules\\' -and
      $_.FullName -notmatch '\\.git\\'
    }
  foreach ($h in $hits) {
    Fail "${Label} sensitive file: $($h.FullName)"
  }
}

function Assert-WindowsGuiSubsystem {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$Label
  )
  if (-not (Test-Path $Path)) {
    Fail "$Label missing: $Path"
  }

  $stream = [System.IO.File]::OpenRead($Path)
  $reader = New-Object System.IO.BinaryReader($stream)
  try {
    if ($reader.ReadUInt16() -ne 0x5A4D) {
      Fail "$Label is not a PE executable: $Path"
    }
    $stream.Seek(0x3C, [System.IO.SeekOrigin]::Begin) | Out-Null
    $peOffset = $reader.ReadUInt32()
    $stream.Seek($peOffset, [System.IO.SeekOrigin]::Begin) | Out-Null
    if ($reader.ReadUInt32() -ne 0x00004550) {
      Fail "$Label has invalid PE signature: $Path"
    }
    $stream.Seek(20, [System.IO.SeekOrigin]::Current) | Out-Null
    $optionalHeaderOffset = $stream.Position
    $magic = $reader.ReadUInt16()
    if ($magic -ne 0x10B -and $magic -ne 0x20B) {
      Fail "$Label has unsupported PE optional header: 0x$($magic.ToString('x'))"
    }
    $stream.Seek($optionalHeaderOffset + 68, [System.IO.SeekOrigin]::Begin) | Out-Null
    $subsystem = $reader.ReadUInt16()
    if ($subsystem -ne 2) {
      Fail "$Label must be Windows GUI subsystem (2), got $subsystem. Console subsystem builds show a terminal window."
    }
    Write-Host "OK $Label Windows GUI subsystem"
  } finally {
    $reader.Dispose()
    $stream.Dispose()
  }
}

function Test-StagedSku {
  param([string]$Sku, [bool]$ExpectErp)
  & "$PSScriptRoot\stage-bundled-mods.ps1" -ProductSku $Sku | Out-Null
  $stage = Join-Path $Root "build\staged-mods-$Sku"
  if (-not (Test-Path $stage)) {
    Fail "staging failed: $stage"
  }
  $hasErp = Test-Path (Join-Path $stage $erpMod)
  if ($ExpectErp -and -not $hasErp) {
    Fail "SKU $Sku must include $erpMod"
  }
  if (-not $ExpectErp -and $hasErp) {
    Fail "SKU $Sku must NOT include $erpMod"
  }
  foreach ($bad in $excludedMods) {
    if (Test-Path (Join-Path $stage $bad)) {
      Fail "SKU $Sku staged excluded mod: $bad"
    }
  }
  Write-Host "OK staged $Sku (erp=$hasErp)"
}

if ($Phase -eq 'pre') {
  Write-Host '=== Pre-build security scan ==='
  Scan-SecretsInTree (Join-Path $Root 'mods') 'mods/'
  Scan-SecretsInTree (Join-Path $Root 'config') 'config/'
  Scan-SecretsInTree (Join-Path $Root 'resources') 'resources/'
  $dotEnv = Join-Path $Root '.env'
  if (Test-Path $dotEnv) {
    Write-Warning 'Root .env exists; PyInstaller spec must ship only .env.example'
  }
  foreach ($sku in $skus) {
    Test-StagedSku $sku ($sku -eq 'enterprise')
  }
  & "$PSScriptRoot\verify-desktop-database-default.ps1"
  Write-Host 'Pre-build security: PASSED'
  exit 0
}

Write-Host '=== Post-build security scan ==='
$releaseRoot = Join-Path $Root "release\xcagi-v$Version"
if (-not (Test-Path $releaseRoot)) {
  Fail "release dir missing: $releaseRoot (run build-all-skus first)"
}

$legacy = Get-ChildItem $releaseRoot -Filter 'XCAGI-Setup-*.exe' -File -ErrorAction SilentlyContinue
if ($legacy) {
  Fail "release 根目录不得放置 legacy 单包（请仅保留 personal/enterprise 子目录）: $($legacy.Name -join ', ')"
}
$flatSku = Get-ChildItem $releaseRoot -Filter 'XCAGI-*-Setup-*-x64.exe' -File -ErrorAction SilentlyContinue
if ($flatSku) {
  Fail "安装包必须位于 SKU 子目录内，不得放在 release 根: $($flatSku.Name -join ', ')"
}

foreach ($sku in $skus) {
  $skuDir = Join-Path $releaseRoot $sku
  if (-not (Test-Path $skuDir)) {
    Fail "missing SKU dir: $skuDir"
  }
  $backendExe = Join-Path $skuDir 'win-unpacked\resources\backend\xcagi-backend.exe'
  if (-not (Test-Path $backendExe)) {
    Fail "$sku missing packaged backend executable: $backendExe"
  }
  Assert-WindowsGuiSubsystem -Path $backendExe -Label "$sku packaged backend executable"
  $modsDir = Join-Path $skuDir 'win-unpacked\resources\backend\_internal\mods'
  if (Test-Path $modsDir) {
    $verifyErrorCount = $Error.Count
    & "$PSScriptRoot\verify-bundled-mods.ps1" -ProductSku $sku -UnpackedDir $modsDir
    if (-not $? -or $Error.Count -gt $verifyErrorCount) {
      Fail "verify-bundled-mods failed for $sku"
    }
    Scan-SecretsInTree $modsDir "built-mods-$sku"
  } else {
    Fail "$sku missing bundled mods dir: $modsDir"
  }
  $skuJson = Join-Path $skuDir 'win-unpacked\resources\product-sku.json'
  if (Test-Path $skuJson) {
    $meta = Get-Content $skuJson -Raw | ConvertFrom-Json
    if ($meta.sku -ne $sku) {
      Fail "product-sku.json sku=$($meta.sku) != folder $sku"
    }
  } else {
    Fail "$sku missing product-sku.json: $skuJson"
  }
  $setup = Get-ChildItem $skuDir -Filter 'XCAGI-*-Setup-*-x64.exe' -File -ErrorAction SilentlyContinue |
    Select-Object -First 1
  $yml = Join-Path $skuDir 'latest.yml'
  if (-not $setup) { Fail "$sku missing Setup exe" }
  if (-not (Test-Path $yml)) { Fail "$sku missing latest.yml" }
  Write-Host "OK $sku artifact: $($setup.Name)"
}

Write-Host 'Post-build security: PASSED'
