param(
  [Parameter(Mandatory = $true)]
  [ValidateSet('personal', 'enterprise')]
  [string]$ProductSku,
  [string]$UnpackedInternalDir = ''
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")

if (-not $UnpackedInternalDir) {
  $ver = '10.0.0'
  if ($env:XCAGI_VERIFY_VERSION) { $ver = $env:XCAGI_VERIFY_VERSION }
  $UnpackedInternalDir = Join-Path $Root "release\xcagi-v$ver\$ProductSku\win-unpacked\resources\backend\_internal"
}

$modsDir = Join-Path $UnpackedInternalDir "mods"
$seedsDir = Join-Path $UnpackedInternalDir "industry-seeds"

if (-not (Test-Path $modsDir)) {
  throw "Mods dir not found: $modsDir"
}

$forbiddenInMods = @('taiyangniao-pro', 'sz-qsm-pro', 'coating-industry', 'attendance-industry')
foreach ($mid in $forbiddenInMods) {
  $p = Join-Path $modsDir $mid
  if (Test-Path $p) {
    throw "L2/L3 mod must NOT be in active mods/ seed: $mid"
  }
}

Get-ChildItem $modsDir -Directory -ErrorAction SilentlyContinue | ForEach-Object {
  if ($_.Name -like '*-industry') {
    throw "Industry mod must NOT be in active mods/ seed: $($_.Name)"
  }
}

Write-Host "OK: mods/ contains no industry or custom client mods"

if ($ProductSku -eq 'enterprise') {
  if (-not (Test-Path $seedsDir)) {
    throw "enterprise installer must include industry-seeds/: $seedsDir"
  }
  $readScript = Join-Path $PSScriptRoot "read-open-industry-seed-ids.py"
  $idsJson = python $readScript
  if ($LASTEXITCODE -ne 0) { throw "read-open-industry-seed-ids.py failed" }
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
  $missing = @()
  foreach ($mid in $expectedIds) {
    $p = Join-Path $seedsDir $mid
    if (-not (Test-Path $p)) {
      $missing += $mid
    }
  }
  if ($missing.Count -gt 0) {
    throw "industry-seeds/ missing open industry mod(s): $($missing -join ', ')"
  }
  Write-Host "OK: industry-seeds/ contains all $($expectedIds.Count) open industry mod(s)"
} else {
  Write-Host "OK: personal SKU industry-seeds check skipped"
}
