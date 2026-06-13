param(
  [Parameter(Mandatory = $true)]
  [ValidateSet('personal', 'enterprise')]
  [string]$ProductSku
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$modsRoot = Join-Path $Root "mods"
$stageDir = Join-Path $Root "build\staged-industry-seeds-$ProductSku"

if ($ProductSku -ne 'enterprise') {
  if (Test-Path $stageDir) {
    Remove-Item $stageDir -Recurse -Force
  }
  New-Item -ItemType Directory -Force -Path $stageDir | Out-Null
  Write-Host "Skipped industry-seeds staging for SKU $ProductSku (enterprise only)"
  exit 0
}

$readScript = Join-Path $PSScriptRoot "read-open-industry-seed-ids.py"
$idsJson = (& python $readScript) -join "`n"
if ($LASTEXITCODE -ne 0) { throw "read-open-industry-seed-ids.py failed" }
$parsedIds = $idsJson | ConvertFrom-Json
$ids = @()
foreach ($id in $parsedIds) {
  $ids += [string]$id
}

if (Test-Path $stageDir) {
  Remove-Item $stageDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $stageDir | Out-Null

$missing = @()
foreach ($modId in $ids) {
  $src = Join-Path $modsRoot $modId
  if (-not (Test-Path $src)) {
    $missing += $modId
    Write-Warning "Industry seed mod not found, skip: $modId ($src)"
    continue
  }
  $dst = Join-Path $stageDir $modId
  Copy-Item -Path $src -Destination $dst -Recurse -Force
  Write-Host "Staged industry seed: $modId"
}

if ($missing.Count -gt 0) {
  throw "Missing industry seed mod(s) under mods/: $($missing -join ', ')"
}

Write-Host "Staged $($ids.Count) industry seed mod(s) for SKU $ProductSku -> $stageDir"
