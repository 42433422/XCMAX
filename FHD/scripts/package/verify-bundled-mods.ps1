param(
  [Parameter(Mandatory = $true)]
  [ValidateSet('personal', 'enterprise')]
  [string]$ProductSku,
  [string]$UnpackedDir = ''
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")

$readProfileScript = Join-Path $PSScriptRoot "read-host-profile-stage-ids.py"
$idsJson = python $readProfileScript $ProductSku
if ($LASTEXITCODE -ne 0) { throw "read-host-profile-stage-ids.py failed" }
$idsJsonText = ($idsJson -join "`n")
$parsedIds = $idsJsonText | ConvertFrom-Json
$expectedIds = New-Object System.Collections.Generic.List[string]
foreach ($item in @($parsedIds)) {
  if ($item -is [System.Array]) {
    foreach ($nested in $item) {
      $expectedIds.Add([string]$nested)
    }
  } else {
    $expectedIds.Add([string]$item)
  }
}

$erpMod = 'xcagi-erp-domain-bridge'

if (-not $UnpackedDir) {
  $ver = '10.0.0'
  if ($env:XCAGI_VERIFY_VERSION) { $ver = $env:XCAGI_VERIFY_VERSION }
  $UnpackedDir = Join-Path $Root "release\xcagi-v$ver\$ProductSku\win-unpacked\resources\backend\_internal\mods"
}

if (-not (Test-Path $UnpackedDir)) {
  throw "Mods dir not found (build installer first): $UnpackedDir"
}

$erpPath = Join-Path $UnpackedDir $erpMod
$hasErp = Test-Path $erpPath

switch ($ProductSku) {
  'personal' {
    if ($hasErp) { throw "personal SKU must NOT bundle $erpMod" }
    Write-Host "OK: personal has no ERP mod in installer"
  }
  'enterprise' {
    if (-not $hasErp) { throw "enterprise SKU must bundle $erpMod" }
    Write-Host "OK: enterprise includes ERP mod"
  }
}

$missing = @()
foreach ($mid in $expectedIds) {
  if ($mid -eq 'taiyangniao-pro' -or $mid -eq 'sz-qsm-pro') { continue }
  $p = Join-Path $UnpackedDir $mid
  if (-not (Test-Path $p)) {
    $missing += $mid
  }
}
if ($missing.Count -gt 0) {
  throw "Installer missing profile stage mods: $($missing -join ', ')"
}
Write-Host "OK: all $($expectedIds.Count) profile stage mod(s) present"

$verifyIndustryScript = Join-Path $PSScriptRoot "verify-industry-seeds.ps1"
if (Test-Path $verifyIndustryScript) {
  $internalDir = Split-Path $UnpackedDir -Parent
  $industryErrorCount = $Error.Count
  & $verifyIndustryScript -ProductSku $ProductSku -UnpackedInternalDir $internalDir
  if (-not $? -or $Error.Count -gt $industryErrorCount) {
    throw "verify-industry-seeds failed for $ProductSku"
  }
}
